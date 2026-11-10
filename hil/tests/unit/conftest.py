"""Unit tests never write into the real reports directory (a hardware run's reports live there)."""

import pytest


@pytest.fixture(autouse=True)
def _isolated_reports_dir(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("HIL_REPORTS_DIR", str(tmp_path_factory.mktemp("reports")))
