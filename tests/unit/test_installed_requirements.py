"""Fresh-install metadata floors, independent of uv.lock."""

from scripts.check_installed_requirements import floor_failures


def test_installed_requirement_floors_accept_patched_metadata():
    assert (
        floor_failures(
            [
                "Pillow>=13.0.0",
                "Pillow>=13.0.0 ; extra == 'tray'",
                "filelock>=4.2.1",
                "setuptools>=84.1.0",
                "deal>=4.1",
            ]
        )
        == []
    )


def test_installed_requirement_floors_reject_pillow_12():
    failures = floor_failures(
        [
            "Pillow>=10.0.0",
            "filelock>=4.2.1",
            "setuptools>=84.1.0",
        ]
    )
    assert any("Pillow>=10.0.0" in failure for failure in failures)
    assert any(">=13.0.0" in failure for failure in failures)
