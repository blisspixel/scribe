"""Security boundaries for optional metadata and universal registry auditing."""

import json
import subprocess
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from scripts import audit_lock

ROOT = Path(__file__).resolve().parents[2]
SECURITY_RELEASES = {
    "mako": ("1.4.1", "1.4.2"),
    "multidict": ("6.9.0", "6.9.1"),
    "pytorch-lightning": ("2.6.5", "2.6.6"),
}


def test_published_optional_metadata_excludes_vulnerable_releases():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    requirements = {
        canonicalize_name(requirement.name): requirement
        for requirement in map(Requirement, project["optional-dependencies"]["diarize"])
    }
    for name, (vulnerable, fixed) in SECURITY_RELEASES.items():
        requirement = requirements[name]
        assert requirement.marker is None  # The security floor covers every platform.
        assert vulnerable not in requirement.specifier
        assert fixed in requirement.specifier
    assert "7.0.0" not in requirements["multidict"].specifier
    base_names = {canonicalize_name(Requirement(item).name) for item in project["dependencies"]}
    assert base_names.isdisjoint(SECURITY_RELEASES)


def test_unused_whisperx_extra_is_retired_without_removing_whisper_models():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert "whisperx" not in project["optional-dependencies"]
    base_names = {canonicalize_name(Requirement(item).name) for item in project["dependencies"]}
    assert "faster-whisper" in base_names
    packages, _ = audit_lock.registry_inventory(ROOT / "uv.lock")
    assert {name for name, _ in packages}.isdisjoint({"whisperx", "nltk"})


def test_every_locked_variant_meets_primary_advisory_floors():
    packages, _ = audit_lock.registry_inventory(ROOT / "uv.lock")
    for name, (_, fixed) in SECURITY_RELEASES.items():
        versions = [Version(version) for package, version in packages if package == name]
        assert versions
        assert all(version >= Version(fixed) for version in versions)
    assert all(Version(version) < Version("7") for name, version in packages if name == "multidict")


def test_registry_inventory_keeps_inactive_markers_and_reports_vcs(tmp_path):
    lock = tmp_path / "uv.lock"
    lock.write_text(
        '[[package]]\nname="sample"\nversion="1"\nsource={registry="https://pypi.org/simple"}\n'
        "resolution-markers=[\"sys_platform == 'win32'\"]\n"
        '[[package]]\nname="sample"\nversion="2"\nsource={registry="https://pypi.org/simple"}\n'
        '[[package]]\nname="local"\nversion="1"\nsource={editable="."}\n'
        '[[package]]\nname="upstream"\nversion="1"\nsource={git="https://example.test/repo#sha"}\n'
    )
    packages, other = audit_lock.registry_inventory(lock)
    assert packages == [("sample", "1"), ("sample", "2")]
    assert len(other) == 2
    batches = audit_lock.requirement_batches(packages)
    assert batches == [[("sample", "1")], [("sample", "2")]]


@pytest.mark.parametrize(
    ("dependencies", "returncode", "expected"),
    [
        ([{"name": "sample", "version": "1", "vulns": []}], 0, True),
        (
            [{"name": "sample", "version": "1", "vulns": [{"id": "TEST-1", "fix_versions": []}]}],
            1,
            False,
        ),
    ],
)
def test_audit_reports_advisories_without_ignores(
    monkeypatch, tmp_path, capsys, dependencies, returncode, expected
):
    def run(command, **kwargs):
        assert "--disable-pip" in command
        assert "--no-deps" in command
        requirements = Path(command[-1]).read_text()
        assert requirements == "sample==1\n"
        return subprocess.CompletedProcess(
            command, returncode, json.dumps({"dependencies": dependencies}), ""
        )

    monkeypatch.setattr(audit_lock.subprocess, "run", run)
    assert audit_lock.audit_batch([("sample", "1")], tmp_path, 0) is expected
    if not expected:
        assert "TEST-1 (fix: no released fix)" in capsys.readouterr().out


@pytest.mark.parametrize(
    "response",
    [
        {"dependencies": []},
        {"dependencies": [{"name": "sample", "version": "1", "skip_reason": "unsupported"}]},
        {"dependencies": [{"name": "sample", "version": "2", "vulns": []}]},
    ],
)
def test_audit_fails_closed_on_skipped_or_missing_versions(monkeypatch, tmp_path, response):
    monkeypatch.setattr(
        audit_lock.subprocess,
        "run",
        lambda *args, **_kwargs: subprocess.CompletedProcess(args, 0, json.dumps(response), ""),
    )
    with pytest.raises(ValueError, match="Incomplete registry audit"):
        audit_lock.audit_batch([("sample", "1")], tmp_path, 0)


def test_audit_continues_other_python_versions_after_a_finding(monkeypatch, tmp_path):
    lock = tmp_path / "uv.lock"
    lock.write_text(
        '[[package]]\nname="sample"\nversion="1"\nsource={registry="https://pypi.org/simple"}\n'
        '[[package]]\nname="sample"\nversion="2"\nsource={registry="https://pypi.org/simple"}\n'
    )
    called = []

    def audit(packages, directory, index):
        called.append(packages)
        return index != 0

    monkeypatch.setattr(audit_lock, "audit_batch", audit)
    monkeypatch.setattr("sys.argv", ["audit_lock.py", str(lock)])
    assert audit_lock.main() == 1
    assert called == [[("sample", "1")], [("sample", "2")]]
