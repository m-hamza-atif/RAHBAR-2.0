import pytest


@pytest.fixture(autouse=True)
def isolated_trace_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("TRACE_DIR", str(tmp_path / "traces"))
