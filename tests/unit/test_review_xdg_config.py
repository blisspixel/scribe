"""Review configuration follows real fresh-process Linux XDG precedence."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform != "linux", reason="Linux XDG config integration")
@pytest.mark.parametrize(
    "current_exists,env_override", [(True, False), (True, True), (False, False)]
)
def test_fresh_process_review_config_and_legacy_reads(tmp_path, current_exists, env_override):
    home = tmp_path / "home"
    current = tmp_path / "configuration" / "scribe" / "config.toml"
    legacy = home / ".scribe" / "config.toml"
    current.parent.mkdir(parents=True)
    legacy.parent.mkdir(parents=True)
    legacy_text = (
        '[transcription]\nquality="accurate"\nverification="off"\nverification_model="small"\n'
    )
    legacy.write_text(legacy_text)
    current_text = (
        '[transcription]\nquality="max"\nverification="best-effort"\nverification_model="medium"\n'
    )
    if current_exists:
        current.write_text(current_text)
    env = {key: value for key, value in os.environ.items() if not key.startswith("SCRIBE_")}
    env.update(
        HOME=str(home),
        XDG_CONFIG_HOME=str(current.parent.parent),
        XDG_STATE_HOME=str(tmp_path / "state"),
        XDG_DATA_HOME=str(tmp_path / "data"),
        PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"),
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    if env_override:
        env.update(
            SCRIBE_TRANSCRIPTION_QUALITY="accurate",
            SCRIBE_TRANSCRIPTION_VERIFICATION="required",
            SCRIBE_VERIFICATION_MODEL="large-v3",
        )
    code = """
import json, socket

def reject(*args, **kwargs):
    raise AssertionError('Config must not contact a model or endpoint')

socket.socket.connect = reject
socket.socket.connect_ex = reject
socket.getaddrinfo = reject
from scribe import config_file
from scribe.models.config import ScribeConfig
config = ScribeConfig(_env_file=None)
print(json.dumps({'path': str(config_file.config_read_path()), 'quality': config.transcription_quality, 'verification': config.transcription_verification, 'model': config.verification_model, 'log_folder': str(config.log_folder)}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    actual = json.loads(result.stdout)
    assert actual["path"] == str(current if current_exists else legacy)
    assert actual["log_folder"] == str(tmp_path / "state" / "scribe" / "logs")
    expected = (
        ("accurate", "required", "large-v3")
        if env_override
        else ("max", "best-effort", "medium")
        if current_exists
        else ("accurate", "off", "small")
    )
    assert (actual["quality"], actual["verification"], actual["model"]) == expected
    assert legacy.read_text() == legacy_text
    assert current.exists() is current_exists
    if current_exists:
        assert current.read_text() == current_text
