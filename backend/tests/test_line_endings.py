"""The files the nginx image sources or renders check out with LF (#255).

Git for Windows' installer defaults to ``core.autocrlf=true``, which converts every
text file to CRLF on checkout unless the repository's ``.gitattributes`` says
otherwise. The nginx entrypoint sources ``frontend/nginx/*.envsh`` with the shell's
dot command under ``set -e``; a CRLF copy fails to parse, the ``web`` container
exits, and the documented ``docker compose up -d --build --wait`` fails.

Every CI runner checks out with LF, so the bytes of the working tree prove nothing
here. The guard is the *effective* attribute, read through git from the working
tree's ``.gitattributes``: it fails on a checkout of this repository without the
rule, on any platform, which the byte check alone never would.
"""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
NGINX_DIR = REPO_ROOT / "frontend" / "nginx"

# What the image consumes from frontend/nginx/: ``*.envsh`` is sourced by the
# entrypoint, ``*.template`` is rendered by envsubst into the live config. Listed
# by hand, not globbed, so the parametrize below can never be empty (an empty
# parametrize is a skip, not a failure); ``test_every_nginx_input_is_listed``
# makes a new file here a deliberate addition.
IMAGE_INPUTS = (
    "frontend/nginx/15-plamotrack-server-names.envsh",
    "frontend/nginx/default.conf.template",
)

# The attribute pair the rule must resolve to: ``text=auto`` leaves binary
# detection to git, ``eol=lf`` fixes the checkout ending whatever
# ``core.autocrlf`` the clone carries.
EXPECTED_ATTRIBUTES = {"text": "auto", "eol": "lf"}


def effective_attributes(path: str) -> dict[str, str]:
    """``text`` and ``eol`` as git resolves them for ``path`` from the working tree.

    ``check-attr`` matches patterns, so the path need not exist — which is what
    lets ``test_the_rule_is_repository_wide`` ask about a file nobody has added.
    """
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-attr", "text", "eol", "--", path],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    attributes: dict[str, str] = {}
    for line in out.splitlines():
        # "<path>: <attribute>: <value>"
        _, attribute, value = line.rsplit(": ", 2)
        attributes[attribute] = value
    return attributes


def test_every_nginx_input_is_listed() -> None:
    on_disk = {
        p.relative_to(REPO_ROOT).as_posix()
        for p in [*NGINX_DIR.glob("*.envsh"), *NGINX_DIR.glob("*.template")]
    }
    assert on_disk == set(IMAGE_INPUTS)


@pytest.mark.parametrize("path", IMAGE_INPUTS)
def test_nginx_image_inputs_check_out_with_lf(path: str) -> None:
    assert effective_attributes(path) == EXPECTED_ATTRIBUTES


@pytest.mark.parametrize("path", IMAGE_INPUTS)
def test_nginx_image_inputs_are_lf_in_this_checkout(path: str) -> None:
    # Vacuous on a Linux runner, real on a Windows checkout of the fixed repository.
    assert b"\r" not in (REPO_ROOT / path).read_bytes()


def test_the_rule_is_repository_wide() -> None:
    # A path that does not exist: only a ``*`` rule can answer for it. A rule
    # narrowed to the nginx directory would leave the next sourced script exposed.
    assert effective_attributes("deploy/not-yet-written.sh") == EXPECTED_ATTRIBUTES
