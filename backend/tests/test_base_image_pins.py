"""Base images are pinned by digest, one pin per image, and the pin check moves them (#344)."""

import hashlib
import json
import re
import shutil
import tomllib
from pathlib import Path

import pytest

import base_image_pins as pins
import release_artifacts as release

ROOT = Path(__file__).resolve().parents[2]
DIGEST = r"sha256:[0-9a-f]{64}"

# Read straight from the files, not through either script's parser: these are the
# three places PostgreSQL is named, and the test is that they cannot disagree.
COMPOSE_DB = re.compile(r"^\s*image: \$\{PLAMOTRACK_DB_IMAGE:-(postgres:[^}]+)\}$", re.M)
CI_SERVICE = re.compile(r"^\s+postgres:\n\s+image: (\S+)$", re.M)

# Every image a source build or CI pulls, where it is named. Written out by hand so
# an inventory that finds nothing, or misses one, fails rather than passing empty.
EXPECTED = [
    ("backend/Dockerfile", "docker/dockerfile:1"),
    ("backend/Dockerfile", "python:3.12-slim-bookworm"),
    ("backend/Dockerfile", "ghcr.io/astral-sh/uv:0.5"),
    ("backend/Dockerfile", "python:3.12-slim-bookworm"),
    ("frontend/Dockerfile", "docker/dockerfile:1"),
    ("frontend/Dockerfile", "node:22-slim"),
    ("frontend/Dockerfile", "nginx:1.27-alpine"),
    ("docker-compose.yml", "postgres:16"),
    (".github/workflows/ci.yml", "postgres:16"),
]


def _version() -> tuple[str, str]:
    version = tomllib.loads((ROOT / "backend/pyproject.toml").read_text())["project"]["version"]
    return "v" + version + "-alpha", "a" * 40


def only(pattern: re.Pattern, path: str) -> str:
    found = pattern.findall((ROOT / path).read_text())
    assert len(found) == 1, (path, found)
    return found[0]


def test_postgres_is_one_pin_in_compose_and_ci():
    compose = only(COMPOSE_DB, "docker-compose.yml")
    service = only(CI_SERVICE, ".github/workflows/ci.yml")
    assert re.fullmatch(r"postgres:16@" + DIGEST, compose), compose
    assert service == compose, (
        "ci.yml's Postgres service and docker-compose.yml's default are one pin; "
        "move both with backend/base_image_pins.py --update"
    )


def test_the_release_bundle_ships_the_compose_pin(tmp_path):
    workflow = (ROOT / ".github/workflows/release-candidate.yml").read_text()
    # It names no Postgres of its own to resolve on release day.
    assert "postgres" not in workflow and "--db" not in workflow
    compose = only(COMPOSE_DB, "docker-compose.yml")
    manifest = release.bundle(
        tmp_path / "bundle",
        *_version(),
        {
            "api": release.IMAGE_PREFIX + "api@sha256:" + "1" * 64,
            "web": release.IMAGE_PREFIX + "web@sha256:" + "2" * 64,
        },
    )
    assert manifest["images"]["db"] == "postgres@" + compose.split("@")[1]
    bundled = (tmp_path / "bundle/docker-compose.yml").read_text()
    assert "    image: " + manifest["images"]["db"] + "\n" in bundled
    assert "PLAMOTRACK_DB_IMAGE" not in bundled


def test_the_bundle_refuses_a_postgres_other_than_the_pin(tmp_path):
    with pytest.raises(ValueError, match="db must be the repository's PostgreSQL pin"):
        release.bundle(
            tmp_path / "bundle",
            *_version(),
            {
                "api": release.IMAGE_PREFIX + "api@sha256:" + "1" * 64,
                "web": release.IMAGE_PREFIX + "web@sha256:" + "2" * 64,
                "db": "postgres@sha256:" + "3" * 64,
            },
        )
    assert not (tmp_path / "bundle").exists()  # refused before anything was written


def test_every_base_image_is_pinned_and_listed():
    found = pins.inventory(ROOT)
    assert [(pin.path, pin.image) for pin in found] == EXPECTED
    assert all(re.fullmatch(DIGEST, pin.digest or "") for pin in found), found
    assert pins.rules(found) == []
    assert pins.main(["--offline"], root=ROOT) == 0


# --- the rules, on a copy of the pinned files ------------------------------------------


@pytest.fixture
def tree(tmp_path):
    for relative in (*pins.DOCKERFILES, *pins.COMPOSE_FILES):
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, tmp_path / relative)
    shutil.copytree(ROOT / pins.WORKFLOW_DIR, tmp_path / pins.WORKFLOW_DIR)
    return tmp_path


def snapshot(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): path.read_text() for path in root.rglob("*") if path.is_file()
    }


def test_a_pin_changed_by_hand_in_one_place_is_refused(tree):
    ci = tree / ".github/workflows/ci.yml"
    compose_digest = only(COMPOSE_DB, "docker-compose.yml").split("@")[1]
    ci.write_text(ci.read_text().replace(compose_digest, "sha256:" + "4" * 64))
    [problem] = pins.rules(pins.inventory(tree))
    assert problem.startswith("postgres:16 is pinned to 2 digests")
    assert pins.main(["--offline"], root=tree) == 1


@pytest.mark.parametrize(
    ("path", "line", "named"),
    [
        ("backend/Dockerfile", "FROM busybox:1.36 AS extra\n", "busybox:1.36 has no digest"),
        ("frontend/Dockerfile", "COPY --from=alpine:3.20 /etc/os-release /x\n", "alpine:3.20"),
        (".github/workflows/ci.yml", "        image: redis:7\n", "redis:7 has no digest"),
        ("backend/Dockerfile", "FROM python@sha256:" + "5" * 64 + "\n", "but no tag"),
    ],
)
def test_a_reference_without_a_digest_or_tag_is_refused(tree, path, line, named):
    with (tree / path).open("a") as file:
        file.write(line)
    problems = pins.rules(pins.inventory(tree))
    assert len(problems) == 1 and named in problems[0], problems


def test_a_stage_name_is_not_an_image(tree):
    # backend/Dockerfile copies the venv --from=build; that is a stage, not a pull.
    assert "COPY --from=build " in (tree / "backend/Dockerfile").read_text()
    assert all(pin.name != "build" for pin in pins.inventory(tree))


def test_an_interpolated_reference_is_refused(tree):
    with (tree / "frontend/Dockerfile").open("a") as file:
        file.write("FROM node:${NODE_VERSION} AS later\n")
    with pytest.raises(pins.PinError, match="interpolated"):
        pins.inventory(tree)


def test_a_compose_image_the_check_does_not_know_is_refused(tree):
    compose = tree / "docker-compose.yml"
    compose.write_text(compose.read_text() + "  cache:\n    image: redis:7\n")
    with pytest.raises(pins.PinError, match="does not know how to pin"):
        pins.inventory(tree)


# --- the check and the rewrite, against a registry of the test's own -------------------


class FakeRegistry:
    """Every tag's index is its pin, except the ones the test moves."""

    def __init__(self, moved: dict[str, str], refuse: str | None = None, root: Path = ROOT):
        self.moved = moved
        self.refuse = refuse
        self.asked: list[str] = []
        self.checked: list[tuple[str, str]] = []
        self.pinned = {pin.image: pin.digest for pin in pins.inventory(root)}

    def current(self, name: str, tag: str) -> str:
        self.asked.append(f"{name}:{tag}")
        return self.moved.get(f"{name}:{tag}", self.pinned[f"{name}:{tag}"])

    def check_index(self, name: str, digest: str) -> None:
        self.checked.append((name, digest))
        if name == self.refuse:
            raise pins.PinError(f"{name}@{digest} has no linux/arm64 image; a release builds both")


NEW = "sha256:" + "6" * 64


def test_a_current_inventory_passes_and_asks_once_per_image(tree, capsys):
    registry = FakeRegistry({})
    before = snapshot(tree)
    assert pins.main([], root=tree, registry=registry) == 0
    assert sorted(registry.asked) == sorted({image for _, image in EXPECTED})
    assert snapshot(tree) == before
    assert "all 9 pins name their tag's current index" in capsys.readouterr().out


def test_a_stale_pin_fails_the_check_and_writes_nothing(tree, capsys):
    before = snapshot(tree)
    assert pins.main([], root=tree, registry=FakeRegistry({"postgres:16": NEW})) == 1
    assert snapshot(tree) == before
    out, err = capsys.readouterr()
    assert out.count("  stale") == 2 and out.count("  current") == 7
    assert f"now {NEW}" in out
    assert "2 of 9 pins are behind their tag" in err


def test_update_rewrites_the_stale_pins_and_nothing_else(tree):
    before = snapshot(tree)
    moving = {"postgres:16": NEW, "node:22-slim": NEW, "python:3.12-slim-bookworm": NEW}
    registry = FakeRegistry(moving)
    assert pins.main(["--update"], root=tree, registry=registry) == 0
    # Each new index is read before anything is written, once per image.
    assert sorted(registry.checked) == [("node", NEW), ("postgres", NEW), ("python", NEW)]
    after = snapshot(tree)
    changed = {name for name in after if after[name] != before[name]}
    assert changed == {
        "docker-compose.yml",
        ".github/workflows/ci.yml",
        "frontend/Dockerfile",
        "backend/Dockerfile",
    }
    lines_moved = {"backend/Dockerfile": 2}  # both stages; one pin each elsewhere
    for name in changed:
        old = before[name].splitlines()
        new = after[name].splitlines()
        assert len(old) == len(new)
        edits = [(a, b) for a, b in zip(old, new, strict=True) if a != b]
        assert len(edits) == lines_moved.get(name, 1), (name, edits)
        for a, b in edits:
            assert NEW in b and NEW not in a and re.sub(DIGEST, "", a) == re.sub(DIGEST, "", b)
    # Every pin of a moved image moved, and the rest are as they were.
    for pin in pins.inventory(tree):
        assert (pin.digest == NEW) == (pin.image in moving), pin
    # The result is a passing check.
    assert pins.main([], root=tree, registry=FakeRegistry({}, root=tree)) == 0


def test_update_refuses_an_index_without_both_platforms(tree, capsys):
    before = snapshot(tree)
    registry = FakeRegistry({"postgres:16": NEW, "node:22-slim": NEW}, refuse="postgres")
    assert pins.main(["--update"], root=tree, registry=registry) == 2
    assert snapshot(tree) == before  # neither image moved: the refusal comes first
    assert "has no linux/arm64 image" in capsys.readouterr().err


# --- the registry client's own judgements ----------------------------------------------


@pytest.mark.parametrize(
    ("name", "host", "repository"),
    [
        ("python", "registry-1.docker.io", "library/python"),
        ("docker/dockerfile", "registry-1.docker.io", "docker/dockerfile"),
        ("ghcr.io/astral-sh/uv", "ghcr.io", "astral-sh/uv"),
        ("docker.io/library/postgres", "registry-1.docker.io", "library/postgres"),
        ("localhost:5000/mine", "localhost:5000", "mine"),
    ],
)
def test_registry_names(name, host, repository):
    assert pins._registry(name) == (host, repository)


class CannedRegistry(pins.Registry):
    def __init__(self, headers: dict[str, str], body: bytes = b""):
        super().__init__()
        self.answer = (headers, body)

    def _request(self, method, host, repository, reference):
        return self.answer


def _index(*platforms: tuple[str, str]) -> bytes:
    return json.dumps(
        {
            "schemaVersion": 2,
            "manifests": [
                {"digest": "sha256:" + "7" * 64, "platform": {"os": os, "architecture": arch}}
                for os, arch in platforms
            ],
        }
    ).encode()


def test_a_tag_that_names_a_single_platform_image_is_refused():
    registry = CannedRegistry(
        {"content-type": pins.MANIFEST_TYPES[0], "docker-content-digest": NEW}
    )
    with pytest.raises(pins.PinError, match="not a multi-platform index"):
        registry.current("python", "3.12-slim-bookworm")


def test_the_current_digest_is_the_index_digest():
    registry = CannedRegistry({"content-type": pins.INDEX_TYPES[0], "docker-content-digest": NEW})
    assert registry.current("python", "3.12-slim-bookworm") == NEW


@pytest.mark.parametrize(
    ("platforms", "honest", "message"),
    [
        ((("linux", "amd64"), ("linux", "arm64")), True, None),
        ((("linux", "amd64"),), True, "no linux/arm64 image"),
        ((("linux", "amd64"), ("linux", "arm64")), False, "not that digest's content"),
    ],
)
def test_an_index_is_checked_against_its_digest_and_both_platforms(platforms, honest, message):
    body = _index(*platforms)
    digest = "sha256:" + hashlib.sha256(body).hexdigest() if honest else NEW
    registry = CannedRegistry({}, body)
    if message is None:
        registry.check_index("postgres", digest)
    else:
        with pytest.raises(pins.PinError, match=message):
            registry.check_index("postgres", digest)
