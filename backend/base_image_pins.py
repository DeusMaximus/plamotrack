"""List, check and bump the base images a source build pulls, each pinned by digest (#344).

Every image a source build or CI pulls by name is written ``name:tag@sha256:<index>``:
the Dockerfiles' ``# syntax=``, ``FROM`` and ``COPY --from=`` lines, the Compose
default for PostgreSQL, and the workflows' service images. The digest decides what
is pulled; the tag says which upstream line the pin follows. This script is how a
pin moves:

    python3 backend/base_image_pins.py            # report; exit 1 if a pin is behind its tag
    python3 backend/base_image_pins.py --update   # rewrite the ones that are; review the diff
    python3 backend/base_image_pins.py --offline  # the inventory and its own rules, no network

A check asks each registry, anonymously, which multi-platform index the tag names now
(a ``HEAD`` request, which Docker Hub does not count as a pull). ``--update`` reads the
new index first and refuses one that is not content-addressed to its digest or lacks
``linux/amd64`` or ``linux/arm64``, the two platforms a release builds. Standard library
only, so it runs from the repository root on any Python 3.11+ without ``uv``.

Two rules hold offline too, and ``tests/test_base_image_pins.py`` holds them in CI: every
reference in the pinned files carries a digest, and one tag carries one digest everywhere
it appears (PostgreSQL's Compose default and CI's service image are the same pin, as are
the backend's two stages). ``release_artifacts.py`` reads the PostgreSQL pin from the
Compose file for the release bundle, so it has no third spelling.

The inventory fails closed. A Dockerfile pulls through ``# syntax=``, ``FROM``, ``COPY
--from=`` and ``RUN --mount=…,from=``; a workflow through ``image:``, a scalar
``container:`` and ``uses: docker://``, quoted or not. A line that looks as if it names an
image in any other way (a ``${{ … }}`` expression, a flow mapping, a value on the next
line) is refused, never skipped. What no line check can see is a pull inside a shell
command (``run: docker pull …``): keep those out of the pinned files, or pin them by hand.
"""

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Each file that names an image a source build or CI pulls, and how a reference is
# spelled in it. A new file that does belongs here, or the pin is outside the check.
DOCKERFILES = ("backend/Dockerfile", "frontend/Dockerfile")
COMPOSE_FILES = ("docker-compose.yml",)
WORKFLOW_DIR = ".github/workflows"

DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
# name[:tag][@sha256:…] — the name may carry a registry host and a path.
COMPONENT = r"[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*"
REFERENCE = re.compile(
    rf"(?P<name>(?:[a-z0-9.-]+(?::[0-9]+)?/)?{COMPONENT}(?:/{COMPONENT})*)"
    r"(?::(?P<tag>[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}))?"
    r"(?:@(?P<digest>sha256:[0-9a-f]{64}))?"
)
DOCKERFILE_LINES = (
    re.compile(r"^#\s*syntax\s*=\s*(?P<ref>\S+)\s*$", re.IGNORECASE),
    re.compile(r"^FROM\s+(?:--platform=\S+\s+)?(?P<ref>\S+)(?:\s+AS\s+(?P<stage>\S+))?\s*$", re.I),
    re.compile(r"^COPY\s+(?:--\S+\s+)*?--from=(?P<ref>\S+)\s", re.IGNORECASE),
)
# RUN --mount=type=bind,from=<image>,… pulls an image too (or names a stage).
DOCKERFILE_MOUNT = re.compile(r"--mount=(?P<options>\S+)", re.IGNORECASE)
MOUNT_FROM = re.compile(r"(?:^|,)from=(?P<ref>[^,]+)", re.IGNORECASE)
COMPOSE_LINE = re.compile(r"^\s*image:\s*\$\{PLAMOTRACK_DB_IMAGE:-(?P<ref>[^}]+)\}\s*$")
# The application images are the release's own, written in by release_artifacts.py.
COMPOSE_OWN = re.compile(r"^\s*image:\s*\$\{PLAMOTRACK_(?:API|WEB)_IMAGE:-[^}]+\}\s*$")
# A workflow names an image as a job's or a service's `image:`, a job's scalar
# `container:`, or a step's `uses: docker://…`, one per line, quoted or not.
WORKFLOW_LINES = (
    re.compile(
        r"""^\s*(?:-\s+)?(?:image|container):\s*(?P<q>["']?)(?P<ref>[^\s"'#]+)(?P=q)\s*(?:#.*)?$"""
    ),
    re.compile(
        r"""^\s*(?:-\s+)?uses:\s*(?P<q>["']?)docker://(?P<ref>[^\s"'#]+)(?P=q)\s*(?:#.*)?$"""
    ),
)
# `container:` opening a mapping names no image itself; its `image:` line does.
WORKFLOW_OPENER = re.compile(r"^\s*(?:-\s+)?container:\s*(?:#.*)?$")
# Fail closed (#344, Greptile on PR #398): a line that looks as if it names an image
# but is in none of the forms above — an expression, a flow mapping, a value on the
# next line — is refused, never skipped, since a skip is an unpinned pull no one sees.
IMAGE_KEY = re.compile(r"""(?:^|[\s{,"'])(?:image|container)["']?\s*:|docker://""")
COMPOSE_IMAGE_KEY = re.compile(r"""(?:^|[\s{,"'])image["']?\s*:""")
COMMENT = re.compile(r"^\s*#")

INDEX_TYPES = (
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
)
MANIFEST_TYPES = (
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
)
PLATFORMS = {("linux", "amd64"), ("linux", "arm64")}


class PinError(ValueError):
    """A pinned file breaks a rule this script holds, or a registry answered badly."""


@dataclass(frozen=True)
class Pin:
    path: str  # relative to the repository root
    line: int  # 1-based
    name: str
    tag: str | None
    digest: str | None

    @property
    def image(self) -> str:
        return f"{self.name}:{self.tag}" if self.tag else self.name

    @property
    def where(self) -> str:
        return f"{self.path}:{self.line}"


def parse_reference(text: str, where: str) -> tuple[str, str | None, str | None]:
    match = REFERENCE.fullmatch(text)
    if not match:
        raise PinError(f"{where}: cannot read an image reference from {text!r}")
    return match["name"], match["tag"], match["digest"]


def _files(root: Path) -> list[str]:
    workflows = sorted(
        str(path.relative_to(root))
        for path in (root / WORKFLOW_DIR).glob("*.y*ml")
        if path.suffix in {".yml", ".yaml"}
    )
    return [*DOCKERFILES, *COMPOSE_FILES, *workflows]


def inventory(root: Path = ROOT) -> list[Pin]:
    """Every image reference in the pinned files, in file order."""
    pins: list[Pin] = []
    for relative in _files(root):
        stages: set[str] = set()
        for number, line in enumerate((root / relative).read_text().splitlines(), start=1):
            where = f"{relative}:{number}"
            refs: list[str] = []
            if relative in DOCKERFILES:
                found: list[str] = []
                for pattern in DOCKERFILE_LINES:
                    match = pattern.match(line.strip())
                    if not match:
                        continue
                    if "stage" in pattern.groupindex and match["stage"]:
                        stages.add(match["stage"].lower())
                    found.append(match["ref"])
                if re.match(r"^\s*RUN\s", line, re.IGNORECASE):
                    for mount in DOCKERFILE_MOUNT.finditer(line):
                        found += [m["ref"] for m in MOUNT_FROM.finditer(mount["options"])]
                # A stage name or a stage index is not an image.
                refs += [ref for ref in found if ref.lower() not in stages and not ref.isdigit()]
            elif relative in COMPOSE_FILES:
                match = COMPOSE_LINE.match(line)
                if match:
                    refs.append(match["ref"])
                elif (
                    COMPOSE_IMAGE_KEY.search(line)
                    and not COMMENT.match(line)
                    and not COMPOSE_OWN.match(line)
                ):
                    raise PinError(f"{where}: an image this script does not know how to pin")
            elif not COMMENT.match(line):
                match = next((m for p in WORKFLOW_LINES if (m := p.match(line))), None)
                if match:
                    refs.append(match["ref"])
                elif "${{" in line and IMAGE_KEY.search(line):
                    raise PinError(
                        f"{where}: an image named by a workflow expression cannot be checked; "
                        "write it literally as name:tag@sha256:…"
                    )
                elif IMAGE_KEY.search(line) and not WORKFLOW_OPENER.match(line):
                    raise PinError(
                        f"{where}: an image reference this script cannot read; write it on "
                        "one line as `image: name:tag@sha256:…`"
                    )
            for ref in refs:
                if "$" in ref:
                    raise PinError(f"{where}: {ref!r} is interpolated; a pin must be literal")
                pins.append(Pin(relative, number, *parse_reference(ref, where)))
    return pins


def rules(pins: list[Pin]) -> list[str]:
    """What is wrong with the inventory without asking a registry."""
    problems = [
        f"{pin.where}: {pin.image} has no digest; pin it as {pin.image}@sha256:…"
        for pin in pins
        if pin.digest is None
    ]
    problems += [
        f"{pin.where}: {pin.name} has a digest but no tag; the tag is what --update follows"
        for pin in pins
        if pin.tag is None
    ]
    by_image: dict[str, set[str]] = {}
    for pin in pins:
        if pin.digest:
            by_image.setdefault(pin.image, set()).add(pin.digest)
    for image, digests in sorted(by_image.items()):
        if len(digests) > 1:
            places = ", ".join(p.where for p in pins if p.image == image)
            problems.append(f"{image} is pinned to {len(digests)} digests ({places}); keep one")
    return problems


# --- the registry ---------------------------------------------------------------------


def _registry(name: str) -> tuple[str, str]:
    first, _, rest = name.partition("/")
    if rest and ("." in first or ":" in first or first == "localhost"):
        host, repository = first, rest
    else:
        host, repository = "registry-1.docker.io", name
    if host in {"docker.io", "index.docker.io"}:
        host = "registry-1.docker.io"
    if host == "registry-1.docker.io" and "/" not in repository:
        repository = "library/" + repository
    return host, repository


def _challenge(header: str) -> dict[str, str]:
    scheme, _, params = header.partition(" ")
    if scheme.lower() != "bearer":
        raise PinError(f"the registry asked for {scheme or 'nothing'}, not a bearer token")
    return dict(re.findall(r'(\w+)="([^"]*)"', params))


def _open(request: urllib.request.Request) -> tuple[int, dict[str, str], bytes]:
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers.items()), error.read()


class Registry:
    """An anonymous OCI distribution client: just enough to resolve a tag to its index."""

    def __init__(self) -> None:
        self._tokens: dict[tuple[str, str], str] = {}

    def _request(self, method: str, host: str, repository: str, reference: str):
        url = f"https://{host}/v2/{repository}/manifests/{reference}"
        accept = ", ".join(INDEX_TYPES + MANIFEST_TYPES)
        for _attempt in range(2):
            headers = {"Accept": accept, "User-Agent": "base-image-pins"}
            token = self._tokens.get((host, repository))
            if token:
                headers["Authorization"] = "Bearer " + token
            status, response, body = _open(
                urllib.request.Request(url, headers=headers, method=method)
            )
            lowered = {key.lower(): value for key, value in response.items()}
            if status == 401 and "www-authenticate" in lowered and not token:
                self._tokens[(host, repository)] = self._token(
                    lowered["www-authenticate"], repository
                )
                continue
            if status != 200:
                raise PinError(f"{host}/{repository}:{reference}: the registry answered {status}")
            return lowered, body
        raise PinError(f"{host}/{repository}:{reference}: the registry refused the token")

    def _token(self, header: str, repository: str) -> str:
        challenge = _challenge(header)
        query = {"scope": challenge.get("scope", f"repository:{repository}:pull")}
        if "service" in challenge:
            query["service"] = challenge["service"]
        url = challenge["realm"] + "?" + urllib.parse.urlencode(query)
        status, _, body = _open(
            urllib.request.Request(url, headers={"User-Agent": "base-image-pins"})
        )
        if status != 200:
            raise PinError(f"the token endpoint {challenge['realm']} answered {status}")
        payload = json.loads(body)
        return payload.get("token") or payload["access_token"]

    def current(self, name: str, tag: str) -> str:
        """The digest of the multi-platform index ``name:tag`` names now."""
        host, repository = _registry(name)
        headers, _ = self._request("HEAD", host, repository, tag)
        media = headers.get("content-type", "").split(";")[0].strip()
        if media not in INDEX_TYPES:
            raise PinError(f"{name}:{tag} is {media or 'untyped'}, not a multi-platform index")
        digest = headers.get("docker-content-digest", "")
        if not DIGEST.fullmatch(digest):
            raise PinError(f"{name}:{tag}: the registry gave no usable digest ({digest!r})")
        return digest

    def check_index(self, name: str, digest: str) -> None:
        """Refuse an index that is not this digest's content or lacks a release platform."""
        host, repository = _registry(name)
        _, body = self._request("GET", host, repository, digest)
        if "sha256:" + hashlib.sha256(body).hexdigest() != digest:
            raise PinError(f"{name}@{digest}: the registry's index is not that digest's content")
        index = json.loads(body)
        found = {
            (entry["platform"].get("os"), entry["platform"].get("architecture"))
            for entry in index.get("manifests", [])
            if isinstance(entry.get("platform"), dict)
        }
        missing = PLATFORMS - found
        if missing:
            spelled = ", ".join(f"{os}/{arch}" for os, arch in sorted(missing))
            raise PinError(f"{name}@{digest} has no {spelled} image; a release builds both")


# --- the report and the rewrite -------------------------------------------------------


def check(pins: list[Pin], resolve: Callable[[str, str], str]) -> dict[str, str]:
    """Each pinned image's current digest, asked once per image."""
    current: dict[str, str] = {}
    for pin in pins:
        if pin.image not in current:
            current[pin.image] = resolve(pin.name, pin.tag)
    return current


def update(root: Path, pins: list[Pin], current: dict[str, str]) -> list[Pin]:
    """Rewrite every stale pin to its tag's current digest; return the ones rewritten."""
    stale = [pin for pin in pins if pin.digest != current[pin.image]]
    by_file: dict[str, list[Pin]] = {}
    for pin in stale:
        by_file.setdefault(pin.path, []).append(pin)
    for relative, file_pins in by_file.items():
        path = root / relative
        lines = path.read_text().splitlines(keepends=True)
        for pin in file_pins:
            old = f"{pin.image}@{pin.digest}"
            new = f"{pin.image}@{current[pin.image]}"
            if lines[pin.line - 1].count(old) != 1:
                raise PinError(f"{pin.where}: expected {old} exactly once on the line")
            lines[pin.line - 1] = lines[pin.line - 1].replace(old, new)
        path.write_text("".join(lines))
    return stale


def main(argv: list[str] | None = None, root: Path = ROOT, registry: Registry | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--update", action="store_true", help="rewrite the pins that are behind")
    mode.add_argument("--offline", action="store_true", help="the inventory and its rules only")
    args = parser.parse_args(argv)
    # The report and its verdict interleave in order through a pipe or a CI log.
    sys.stdout.reconfigure(line_buffering=True)

    try:
        pins = inventory(root)
    except PinError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    problems = rules(pins)
    width = max(len(pin.where) for pin in pins)
    image_width = max(len(pin.image) for pin in pins)
    if args.offline or problems:
        for pin in pins:
            print(f"{pin.where:<{width}}  {pin.image:<{image_width}}  {pin.digest or 'UNPINNED'}")
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1 if problems else 0

    registry = registry or Registry()
    try:
        current = check(pins, registry.current)
    except (PinError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    stale = [pin for pin in pins if pin.digest != current[pin.image]]
    for pin in pins:
        state = "stale" if pin in stale else "current"
        print(f"{pin.where:<{width}}  {pin.image:<{image_width}}  {pin.digest[:19]}…  {state}")
        if pin in stale:
            print(f"{'':<{width}}  {'':<{image_width}}  now {current[pin.image]}")

    if not stale:
        print(f"all {len(pins)} pins name their tag's current index")
        return 0
    if not args.update:
        print(
            f"{len(stale)} of {len(pins)} pins are behind their tag; "
            "run with --update and open a PR with the diff",
            file=sys.stderr,
        )
        return 1
    try:
        for image in sorted({pin.image for pin in stale}):
            pin = next(p for p in stale if p.image == image)
            registry.check_index(pin.name, current[image])
        update(root, pins, current)
    except (PinError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"rewrote {len(stale)} pins; review the diff and open a PR — CI builds from it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
