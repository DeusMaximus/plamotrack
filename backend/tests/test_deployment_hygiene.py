"""The packaged worker budget and the ingress harness's secret outputs (#193)."""

import errno
import importlib
import json
import os
import stat
from pathlib import Path

import pytest
from click.testing import CliRunner
from uvicorn import Config

from ingress_matrix import write_private


@pytest.mark.parametrize(
    "web_workers,uvicorn_workers", [(None, None), ("4", None), (None, "4"), ("4", "8")]
)
def test_packaged_worker_count_ignores_environment(web_workers, uvicorn_workers, monkeypatch):
    """Exercise Uvicorn's real CLI, including its two environment defaults."""
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
    (line,) = [line for line in dockerfile.read_text().splitlines() if line.startswith("CMD ")]
    command = json.loads(line.removeprefix("CMD "))
    assert command[0] == "uvicorn"
    module = importlib.import_module("uvicorn.main")
    observed = []

    def capture(app, **kwargs):
        observed.append(Config(app, workers=kwargs["workers"]).workers)

    monkeypatch.setattr(module, "run", capture)
    result = CliRunner().invoke(
        module.main,
        command[1:],
        env={"WEB_CONCURRENCY": web_workers, "UVICORN_WORKERS": uvicorn_workers},
    )
    assert result.exit_code == 0, result.output
    assert observed == [1]


@pytest.mark.parametrize("previous", [None, "", "a longer previous synthetic value"])
def test_private_output_creates_or_restricts_a_file(tmp_path, previous):
    path = tmp_path / "secret"
    if previous is not None:
        path.write_text(previous)
        path.chmod(0o644)
    assert write_private(str(path), "test-value\n") == path
    assert path.read_text() == "test-value\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("existing_target", [True, False])
def test_private_output_refuses_symlinks_without_touching_the_target(tmp_path, existing_target):
    target = tmp_path / "target"
    if existing_target:
        target.write_text("unchanged")
        target.chmod(0o644)
    path = tmp_path / "secret"
    path.symlink_to(target)
    with pytest.raises(OSError) as error:
        write_private(str(path), "synthetic-secret")
    assert error.value.errno == errno.ELOOP
    assert path.is_symlink()
    if existing_target:
        assert target.read_text() == "unchanged"
        assert stat.S_IMODE(target.stat().st_mode) == 0o644
    else:
        assert not target.exists()


def test_private_output_keeps_the_open_file_when_the_path_is_replaced(tmp_path, monkeypatch):
    """Pin a path swap between restricting the file and writing its secret."""
    path = tmp_path / "secret"
    opened = tmp_path / "opened"
    target = tmp_path / "target"
    target.write_text("unchanged")
    fchmod = os.fchmod

    def replace_path(fd, mode):
        fchmod(fd, mode)
        path.rename(opened)
        path.symlink_to(target)

    monkeypatch.setattr(os, "fchmod", replace_path)
    write_private(str(path), "synthetic-secret")
    assert opened.read_text() == "synthetic-secret"
    assert stat.S_IMODE(opened.stat().st_mode) == 0o600
    assert target.read_text() == "unchanged"
