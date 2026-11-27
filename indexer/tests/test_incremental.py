import json
import shutil
from pathlib import Path

import pytest

from pipeline.config import get_settings
from pipeline import incremental
from pipeline.incremental import update
from test_pipeline import FakeClient


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    lake = tmp_path / "lake"
    lake.mkdir()
    monkeypatch.setenv("DATA_LAKE_DIR", str(lake))
    monkeypatch.setenv("ARCHIVE_DIR", str(tmp_path / "archive"))
    monkeypatch.setenv("QUARANTINE_DIR", str(tmp_path / "quarantine"))
    monkeypatch.setenv("VERIFICATION_REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("CHROMA_COLLECTION", "ragops-test")
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("EMBED_MODEL", "stub")
    client = FakeClient()
    monkeypatch.setattr(incremental, "get_client", lambda settings: client)
    return lake, get_settings(), client.collection


def write_policy(lake, file, body, version="2026-06"):
    (lake / file).write_text(
        f"---\ndocument_id: academic-rules\nsource: fixture\ntitle: Academic Rules\n"
        f"version: {version}\npage_count: 1\n---\n\n{body}\n", encoding="utf-8")


def latest(lake):
    report = sorted((lake.parent / "reports").glob("*.json"))[-1]
    return json.loads(report.read_text(encoding="utf-8"))


def test_batch_b_update_delete_and_rollback(workspace):
    lake, settings, collection = workspace
    write_policy(lake, "academic-old.md",
                 "In the June rules, candidates attend three quarters of lectures to sit examinations.")
    assert update(settings) > 0
    first_revision = collection.metadata["index_revision"]
    first_ids = set(collection.get()["ids"])

    assert update(settings) == len(first_ids)
    assert latest(lake)["counts"]["chunks_embedded"] == 0
    assert collection.metadata["index_revision"] == first_revision

    for sample in (Path(__file__).resolve().parents[2] / "corpus" / "batch_b").glob("*.md"):
        shutil.copyfile(sample, lake / sample.name)
    update(settings)
    report = latest(lake)
    assert report["counts"]["quarantined"] == 5
    decisions = {row["file"]: row for row in report["documents"]}
    assert decisions["07-truncated.md"]["checks"]["completeness"]["status"] == "fail"
    assert decisions["08-missing-metadata.md"]["checks"]["completeness"]["status"] == "fail"
    assert decisions["zz-near-duplicate.md"]["checks"]["uniqueness"]["status"] == "fail"
    assert decisions["zz-copy-registration.md"]["checks"]["uniqueness"]["reason"].startswith(
        "exact SHA-256 duplicate")
    assert decisions["academic-old.md"]["disposition"] == "archive"
    assert not (lake / "academic-old.md").exists()
    assert first_ids <= set(collection.get(where={"superseded": True})["ids"])

    (lake / "02-library.md").unlink()
    update(settings)
    report = latest(lake)
    assert report["counts"]["deleted"] == 1
    assert report["counts"]["orphan_chunks"] == report["counts"]["chunks_embedded"] == 0
    assert collection.get(where={"document_id": "library-loans"})["ids"] == []

    update(settings, ("academic-rules", "2026-06"))
    assert first_ids <= set(collection.get(where={"superseded": False})["ids"])
    assert (lake / "academic-old.md").exists()
    assert not (lake / "06-academic-rules.md").exists()
    assert latest(lake)["counts"]["chunks_embedded"] == 0


def test_changed_document_replaces_only_its_chunks(workspace):
    lake, settings, collection = workspace
    write_policy(lake, "rules.md",
                 "Students apply for special examinations through the department office before classes end.")
    (lake / "library.md").write_text(
        "---\ndocument_id: library\nsource: fixture\ntitle: Library\ndate: 2026\n"
        "page_count: 1\n---\n\nBorrowers return printed journals to the library circulation desk.\n",
        encoding="utf-8")
    update(settings)
    old = set(collection.get(where={"document_id": "academic-rules"})["ids"])
    library_ids = collection.get(where={"document_id": "library"})["ids"]
    write_policy(lake, "rules.md",
                 "An examination fee receipt and course identifiers are required with the revised application.")
    update(settings)
    assert old.isdisjoint(collection.get()["ids"])
    assert collection.get(where={"document_id": "library"})["ids"] == library_ids
    assert latest(lake)["counts"]["updated"] == 1


def test_unreadable_document_is_quarantined(workspace):
    lake, settings, _ = workspace
    (lake / "broken.pdf").write_bytes(b"%PDF-1.7\n incomplete PDF")
    assert update(settings) == 0
    decision = latest(lake)["documents"][0]
    assert decision["checks"]["quality"]["status"] == "fail"
    assert decision["disposition"] == "quarantine"


def test_missing_lake_mount_cannot_delete_index(workspace, monkeypatch):
    lake, settings, collection = workspace
    write_policy(lake, "rules.md",
                 "Students apply for special examinations through the department office before classes end.")
    update(settings)
    original_ids = collection.get()["ids"]
    empty_mount = lake.parent / "empty-mount"
    empty_mount.mkdir()
    monkeypatch.setenv("DATA_LAKE_DIR", str(empty_mount))
    with pytest.raises(ValueError, match="data lake identity differs"):
        update(settings)
    assert collection.get()["ids"] == original_ids
