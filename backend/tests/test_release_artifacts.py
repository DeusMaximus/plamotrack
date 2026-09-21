"""Distribution boundaries: bundle identity, pull/source isolation, promotion gates."""

import json
import os
import subprocess
import tomllib
import zipfile
from pathlib import Path

import pytest

import release_artifacts as release
from deployment_gate import Host
from promote_release import eligible

ROOT = Path(__file__).resolve().parents[2]
REVISION = "a" * 40
VERSION = (
    "v"
    + tomllib.loads((ROOT / "backend/pyproject.toml").read_text())["project"]["version"]
    + "-alpha"
)
IMAGES = {
    "api": release.IMAGE_PREFIX + "api@sha256:" + "1" * 64,
    "web": release.IMAGE_PREFIX + "web@sha256:" + "2" * 64,
    "db": "postgres@sha256:" + "3" * 64,
}


@pytest.fixture
def packaged(tmp_path):
    out = tmp_path / "bundle"
    release.bundle(out, VERSION, REVISION, IMAGES)
    return out


def test_bundle_is_reproducible_and_skill_has_parent(packaged, tmp_path):
    other = tmp_path / "second"
    release.bundle(other, VERSION, REVISION, IMAGES)
    for file in packaged.iterdir():
        assert file.read_bytes() == (other / file.name).read_bytes()
    assert release.verify(packaged)["images"] == IMAGES
    with zipfile.ZipFile(packaged / "plamotrack-gunpla.zip") as archive:
        assert "plamotrack-gunpla/SKILL.md" in archive.namelist()
        assert all(name.startswith("plamotrack-gunpla/") for name in archive.namelist())
        assert (
            archive.read("plamotrack-gunpla/SKILL.md")
            == (ROOT / "skills/plamotrack-gunpla/SKILL.md").read_bytes()
        )


@pytest.mark.parametrize(
    "name",
    ["docker-compose.yml", ".env.example", "plamotrack-gunpla.zip", "release.json", "SHA256SUMS"],
)
def test_changed_asset_is_refused(packaged, name):
    with (packaged / name).open("ab") as file:
        file.write(b" ")
    with pytest.raises(ValueError, match="checksum mismatch|SHA256SUMS mismatch"):
        release.verify(packaged)


@pytest.mark.parametrize("bad", ["latest", "v0.0.0-alpha", "v1.2.3;echo bad", "v1.2.3-beta"])
def test_invalid_or_mismatched_version_is_refused(bad):
    with pytest.raises(ValueError):
        release.validate_version(bad, REVISION)


@pytest.mark.parametrize(
    "bad",
    [
        "ghcr.io/deusmaximus/plamotrack-api:latest",
        "sha256:" + "1" * 64,
        "ghcr.io/other/api@sha256:" + "1" * 64,
    ],
)
def test_only_digest_in_correct_repository_is_accepted(bad):
    with pytest.raises(ValueError, match="must name"):
        release.image_ref("api", bad)


def test_existing_bundle_is_never_replaced(packaged):
    with pytest.raises(ValueError, match="must be empty"):
        release.bundle(packaged, VERSION, REVISION, IMAGES)


def compose_config(directory, *files, env=None):
    command = ["docker", "compose", "--project-directory", str(directory)]
    for file in files:
        command += ["-f", str(file)]
    return json.loads(
        subprocess.check_output(
            [*command, "config", "--format", "json"],
            cwd=directory,
            env={**os.environ, "POSTGRES_PASSWORD": "test-only", **(env or {})},
            text=True,
        )
    )


def test_downloaded_compose_needs_no_checkout_and_cannot_float(packaged):
    (packaged / ".env").write_text("POSTGRES_PASSWORD=temporary\n")
    services = compose_config(
        packaged,
        packaged / "docker-compose.yml",
        env={
            "PLAMOTRACK_API_IMAGE": "wrong:latest",
            "PLAMOTRACK_WEB_IMAGE": "wrong:latest",
            "PLAMOTRACK_DB_IMAGE": "wrong:latest",
        },
    )["services"]
    assert all("build" not in value for value in services.values())
    for component in ("api", "web", "db"):
        assert services[component]["image"] == IMAGES[component]
    assert services["migrate"]["image"] == IMAGES["api"]
    assert not services["api"].get("ports") and not services["db"].get("ports")
    assert services["web"]["ports"][0]["host_ip"] == "127.0.0.1"


def test_source_override_ignores_published_images(tmp_path):
    for name in ("docker-compose.yml", "docker-compose.build.yml"):
        (tmp_path / name).write_bytes((ROOT / name).read_bytes())
    (tmp_path / ".env").write_text("POSTGRES_PASSWORD=temporary\n")
    services = compose_config(
        tmp_path,
        tmp_path / "docker-compose.yml",
        tmp_path / "docker-compose.build.yml",
        env={
            "PLAMOTRACK_API_IMAGE": IMAGES["api"],
            "PLAMOTRACK_WEB_IMAGE": IMAGES["web"],
            "PLAMOTRACK_SOURCE_TAG": "review",
            "PLAMOTRACK_SOURCE_REVISION": REVISION,
        },
    )["services"]
    for service, component in (("api", "api"), ("migrate", "api"), ("web", "web")):
        assert services[service]["image"] == f"plamotrack-{component}:review"
        assert services[service]["pull_policy"] == "build"
        assert services[service]["build"]["args"]["SOURCE_REVISION"] == REVISION


def candidate():
    return {
        "path": ".github/workflows/release-candidate.yml",
        "event": "workflow_dispatch",
        "status": "completed",
        "run_attempt": 1,
        "conclusion": "success",
        "head_sha": REVISION,
        "repository": {"full_name": "DeusMaximus/plamotrack"},
    }


def test_successful_candidate_at_exact_revision_can_be_promoted(packaged):
    eligible(candidate(), release.verify(packaged))


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("path", ".github/workflows/ci.yml"),
        ("event", "pull_request"),
        ("status", "in_progress"),
        ("run_attempt", 2),
        ("conclusion", "failure"),
        ("conclusion", "cancelled"),
        ("head_sha", "b" * 40),
        ("repository", {"full_name": "other/plamotrack"}),
    ],
)
def test_ungated_or_different_candidate_is_refused(packaged, key, value):
    record = candidate()
    record[key] = value
    with pytest.raises(ValueError, match="successful release-candidate"):
        eligible(record, release.verify(packaged))


@pytest.mark.parametrize("source", [False, True])
def test_deployment_gate_selects_source_explicitly(monkeypatch, source):
    commands = []
    monkeypatch.setattr(Host, "run", lambda self, command, **kwargs: commands.append(command))
    Host("unused", "/unused", source_build=source).up()
    assert len(commands) == 1
    assert ("-f docker-compose.build.yml" in commands[0]) is source
    assert ("--build" in commands[0]) is source
    assert ("--no-build" in commands[0]) is not source


@pytest.mark.parametrize(
    "block", [None, "tag", "head", "existing-release", "web-conflict", "registry-error"]
)
def test_promotion_preflights_every_image_before_copying(monkeypatch, packaged, tmp_path, block):
    import sys
    from types import SimpleNamespace

    import promote_release as promote

    writes = []
    monkeypatch.setattr(sys, "argv", ["promote_release.py", "123", str(packaged)])
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setattr(promote, "api", lambda path: candidate())

    def read(*args):
        if args == ("git", "rev-parse", "FETCH_HEAD^{commit}"):
            return "b" * 40 if block == "tag" else REVISION
        if args == ("git", "rev-parse", "HEAD"):
            return "b" * 40 if block == "head" else REVISION
        assert args[:2] == ("gh", "api")
        return json.dumps([[{"tag_name": VERSION}]] if block == "existing-release" else [[]])

    def invoke(args, **kwargs):
        if args[:3] == ["git", "fetch", "origin"]:
            return SimpleNamespace(returncode=0)
        if args[:4] == ["docker", "buildx", "imagetools", "inspect"]:
            if block == "web-conflict" and "plamotrack-web:" in args[4]:
                return SimpleNamespace(returncode=0, stdout=json.dumps("sha256:" + "9" * 64))
            if block == "registry-error":
                return SimpleNamespace(returncode=1, stderr="connection refused")
            return SimpleNamespace(returncode=1, stderr="manifest unknown")
        writes.append(args)
        return SimpleNamespace(returncode=0)

    def inspect(reference):
        component = "web" if "plamotrack-web" in reference else "api"
        return IMAGES[component].split("@")[1]

    monkeypatch.setattr(promote, "run", read)
    monkeypatch.setattr(promote.subprocess, "run", invoke)
    monkeypatch.setattr(promote, "digest", inspect)
    if block:
        with pytest.raises(ValueError):
            promote.main()
        assert writes == [], "a failed preflight must not copy even the first image"
    else:
        promote.main()
        assert len(writes) == 3
        for command, component in zip(writes[:2], ("api", "web"), strict=True):
            assert command == [
                "docker",
                "buildx",
                "imagetools",
                "create",
                "--prefer-index=false",
                "--tag",
                release.IMAGE_PREFIX + component + ":" + VERSION,
                IMAGES[component],
            ]
        assert writes[2][:4] == ["gh", "release", "create", VERSION]
        assert "--draft" in writes[2] and "--prerelease" in writes[2]
        assert "--verify-tag" in writes[2]
        for name in release.PAYLOADS | {"release.json", "SHA256SUMS"}:
            assert str(packaged / name) in writes[2]
