"""Build and verify the release bundle without rebuilding its container images.

Python uses only the standard library. Bundle verification also uses the Docker
Compose CLI to parse service images; it does not need a running Docker daemon.
The manifest binds the source commit, version, image digests and downloadable files.
"""

import argparse
import hashlib
import json
import re
import subprocess
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPOSITORY = "DeusMaximus/plamotrack"
IMAGE_PREFIX = "ghcr.io/deusmaximus/plamotrack-"
VERSION = re.compile(r"v(\d+\.\d+\.\d+)(?:-alpha(?:\.\d+)?)?")
SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
PAYLOADS = {"docker-compose.yml", ".env.example", "plamotrack-gunpla.zip"}


def run(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def validate_version(version: str, revision: str, root: Path = ROOT) -> None:
    match = VERSION.fullmatch(version)
    if not match or not SHA.fullmatch(revision):
        raise ValueError("expected vX.Y.Z[-alpha[.N]] and a full lowercase commit SHA")
    expected = match[1]
    project = tomllib.loads((root / "backend/pyproject.toml").read_text())
    lock = tomllib.loads((root / "backend/uv.lock").read_text())
    versions = [
        project["project"]["version"],
        next(p["version"] for p in lock["package"] if p["name"] == "plamotrack-backend"),
        re.search(r'__version__ = "([^"]+)"', (root / "backend/app/__init__.py").read_text())[1],
    ]
    if versions != [expected] * 3:
        raise ValueError(f"release {version} does not match application versions {versions}")


def image_ref(component: str, value: str) -> str:
    prefix = IMAGE_PREFIX + component if component != "db" else "postgres"
    if not value.startswith(prefix + "@") or not DIGEST.fullmatch(value[len(prefix) + 1 :]):
        raise ValueError(f"{component} must name {prefix}@sha256:<64 lowercase hex digits>")
    return value


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bundle(
    out: Path, version: str, revision: str, images: dict[str, str], root: Path = ROOT
) -> dict:
    validate_version(version, revision, root)
    images = {key: image_ref(key, images[key]) for key in ("api", "web", "db")}
    # Refuse to mix files from two candidates on a rerun.
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError("bundle output directory must be empty")
    compose = (root / "docker-compose.yml").read_text()
    for key, fallback in (
        ("api", IMAGE_PREFIX + "api:unreleased"),
        ("web", IMAGE_PREFIX + "web:unreleased"),
        ("db", "postgres:16"),
    ):
        marker = "${PLAMOTRACK_" + key.upper() + "_IMAGE:-" + fallback + "}"
        if compose.count(marker) != (2 if key == "api" else 1):
            raise ValueError(f"unexpected {key} image slots in Compose template")
        compose = compose.replace(marker, images[key])
    (out / "docker-compose.yml").write_text(
        f"# plamotrack {version}; source {revision}\n" + compose
    )
    (out / ".env.example").write_bytes((root / "release.env.example").read_bytes())
    # Only tracked skill files: no .DS_Store, local archives or editor leftovers.
    files = run("git", "-C", str(root), "ls-files", "skills/plamotrack-gunpla").splitlines()
    if "skills/plamotrack-gunpla/SKILL.md" not in files:
        raise ValueError("tracked skill entry point missing")
    with zipfile.ZipFile(out / "plamotrack-gunpla.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            path = root / name
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"skill entry is not a regular file: {name}")
            entry = zipfile.ZipInfo(str(Path(name).relative_to("skills")), (1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, path.read_bytes())
    manifest = {
        "schema": 1,
        "repository": REPOSITORY,
        "version": version,
        "revision": revision,
        "platforms": ["linux/amd64", "linux/arm64"],
        "images": images,
        "assets": {name: checksum(out / name) for name in sorted(PAYLOADS)},
    }
    (out / "release.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (out / "SHA256SUMS").write_text(
        "".join(f"{checksum(out / name)}  {name}\n" for name in sorted(PAYLOADS | {"release.json"}))
    )
    return manifest


def verify(out: Path) -> dict:
    manifest = json.loads((out / "release.json").read_text())
    if manifest["schema"] != 1 or manifest["repository"] != REPOSITORY:
        raise ValueError("unrecognised release manifest")
    if not VERSION.fullmatch(manifest["version"]) or not SHA.fullmatch(manifest["revision"]):
        raise ValueError("invalid version or revision")
    if manifest["platforms"] != ["linux/amd64", "linux/arm64"]:
        raise ValueError("both release platforms are required")
    if set(manifest["assets"]) != PAYLOADS or set(manifest["images"]) != {"api", "web", "db"}:
        raise ValueError("unexpected release assets or images")
    if {p.name for p in out.iterdir()} != PAYLOADS | {"release.json", "SHA256SUMS"}:
        raise ValueError("unexpected files in release bundle")
    for key, value in manifest["images"].items():
        image_ref(key, value)
    for name, expected in manifest["assets"].items():
        if checksum(out / name) != expected:
            raise ValueError(f"checksum mismatch: {name}")
    sums = "".join(
        f"{checksum(out / name)}  {name}\n" for name in sorted(PAYLOADS | {"release.json"})
    )
    if (out / "SHA256SUMS").read_text() != sums:
        raise ValueError("SHA256SUMS mismatch")
    # Check each service, not just whether a digest occurs somewhere in the
    # file: API and migrate deliberately repeat the API digest. Explicit file
    # and project selection ignore the caller's source checkout. Release images
    # must be literal pins; do not interpolate them or require an operator .env.
    config = json.loads(
        run(
            "docker",
            "compose",
            "-p",
            "plamotrack-release-verify",
            "-f",
            str((out / "docker-compose.yml").resolve()),
            "config",
            "--no-interpolate",
            "--no-env-resolution",
            "--format",
            "json",
        )
    )
    for service, component in (("db", "db"), ("migrate", "api"), ("api", "api"), ("web", "web")):
        if config["services"].get(service, {}).get("image") != manifest["images"][component]:
            raise ValueError(f"{service} Compose image does not match manifest")
    return manifest


def verify_running(revision: str, version: str | None = None) -> None:
    """Check stopped migrate too; it must have run precisely the API's image."""
    config = json.loads(run("docker", "compose", "config", "--format", "json"))

    def refusal(message: str) -> ValueError:
        images = ", ".join(
            f"{service}={config['services'][service]['image']}"
            for service in ("api", "migrate", "web")
        )
        return ValueError(
            f"{message}. Resolved Compose project {config['name']!r}: {images}. "
            "Run from the same directory and with the same COMPOSE_FILE, "
            "COMPOSE_PROJECT_NAME and PLAMOTRACK_SOURCE_TAG used to start the stack."
        )

    ids = {}
    for service in ("api", "migrate", "web"):
        container = run("docker", "compose", "ps", "-aq", service)
        [details] = json.loads(run("docker", "inspect", container))
        [image] = json.loads(
            run("docker", "image", "inspect", config["services"][service]["image"])
        )
        if details["Image"] != image["Id"]:
            raise refusal(f"{service} is not running the configured image")
        labels = details["Config"]["Labels"]
        if labels.get("org.opencontainers.image.revision") != revision:
            raise refusal(f"{service} did not come from the reviewed source revision")
        if version and labels.get("org.opencontainers.image.version") != version:
            raise refusal(f"{service} version label mismatch")
        if service == "migrate" and (
            details["State"]["Status"] != "exited" or details["State"]["ExitCode"] != 0
        ):
            raise refusal("migrations did not complete successfully")
        ids[service] = details["Image"]
    if ids["api"] != ids["migrate"]:
        raise refusal("API and migrations ran different images")
    print("running API, web and completed migrations match the configured artifacts and source")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("bundle")
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--version", required=True)
    build.add_argument("--revision", required=True)
    for component in ("api", "web", "db"):
        build.add_argument("--" + component, required=True)
    check = sub.add_parser("verify")
    check.add_argument("directory", type=Path)
    check = sub.add_parser("version")
    check.add_argument("version")
    check.add_argument("revision")
    check = sub.add_parser("running")
    check.add_argument("revision")
    check.add_argument("--version")
    args = parser.parse_args()
    if args.command == "bundle":
        bundle(
            args.out,
            args.version,
            args.revision,
            {key: getattr(args, key) for key in ("api", "web", "db")},
        )
    elif args.command == "verify":
        verify(args.directory)
        print("release bundle checksums and manifest verified")
    elif args.command == "version":
        validate_version(args.version, args.revision)
    else:
        verify_running(args.revision, args.version)


if __name__ == "__main__":
    main()
