"""Synchronize one collection with a verified lake while holding the writer lease."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .chunk import chunk
from .clean import clean
from .config import IndexerSettings
from .embed import embed
from .models import Chunk
from .run import _front_matter
from .store import get_client
from .verify import result, similarity, verify

SUPPORTED = {".pdf", ".html", ".htm", ".md", ".txt"}
ACADEMIC_EDITIONS = {
    "undergraduate-academic-rules-aug-2023.pdf",
    "academic-rules-handbook-jun-2026.pdf",
}


def inventory(lake: Path) -> dict[str, dict[str, Any]]:
    manifest = lake / "_index.json"
    entries = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else []
    metadata = {row["file"]: row for row in entries}
    found: dict[str, dict[str, Any]] = {}
    for path in sorted(lake.iterdir()):
        if (not path.is_file() or path.name.lower().startswith("readme")
                or path.suffix.lower() not in SUPPORTED):
            continue
        if path.is_symlink():
            raise ValueError(f"symbolic link in lake: {path.name}")
        row = metadata.get(path.name)
        if row is not None:
            found[path.name] = {
                "document_id": row.get("document_id") or (
                    "academic-rules" if path.name in ACADEMIC_EDITIONS else path.stem),
                "version": str(row.get("doc_version") or row.get("version") or row.get("date") or ""),
                "source": row.get("source") or row.get("url"),
                "title": row.get("title") or row.get("name"),
                "page_count": row.get(
                    "page_count", row.get("pages") if path.suffix.lower() == ".pdf" else 1),
                "bytes": row.get("bytes"),
                "sha256": row.get("sha256"),
            }
        else:
            try:
                found[path.name] = _front_matter(path) if path.suffix.lower() == ".md" else {}
                if not found[path.name].get("version") and found[path.name].get("date"):
                    found[path.name]["version"] = found[path.name]["date"]
            except UnicodeError:
                found[path.name] = {}
    return found


def fingerprint(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def archive_name(record: dict[str, Any]) -> str:
    return f'{record["content_hash"]}-{record["file"]}'


def copy_verified(source: Path, destination: Path, digest: str) -> None:
    """Publish the copy before any source removal, including across volumes."""
    if destination.exists() and fingerprint(destination) == digest:
        return
    temp = destination.with_name(f".{uuid4().hex}.tmp")
    try:
        shutil.copyfile(source, temp)
        if fingerprint(temp) != digest:
            raise RuntimeError(f"source changed while copying {source.name}")
        temp.replace(destination)
    finally:
        temp.unlink(missing_ok=True)


def version_key(record: dict[str, Any]) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", record["version"]))


def update(settings: IndexerSettings, rollback: tuple[str, str] | None = None) -> int:
    lake = Path(os.getenv("DATA_LAKE_DIR", "corpus/data_lake"))
    quarantine = Path(os.getenv("QUARANTINE_DIR", "corpus/quarantine"))
    archive = Path(os.getenv("ARCHIVE_DIR", "corpus/archive"))
    reports = Path(os.getenv("VERIFICATION_REPORT_DIR", "corpus/reports"))
    paths = {path.resolve() for path in (lake, quarantine, archive, reports)}
    if len(paths) != 4 or not lake.is_dir():
        raise ValueError("the data lake must exist and use separate output directories")
    for directory in (quarantine, archive, reports):
        directory.mkdir(parents=True, exist_ok=True)

    backend = "stub" if settings.llm_provider == "stub" or settings.embed_model == "stub" else "ollama"
    revision = os.getenv("EMBED_VERSION", "stub-v1" if backend == "stub" else "")
    if not revision.strip():
        raise ValueError("set EMBED_VERSION to the immutable model revision")
    signature = [settings.embed_model, revision, backend, settings.chunk_size,
                 settings.chunk_overlap, settings.chunk_strategy, settings.enable_ocr]
    client = get_client(settings)
    collection = client.get_or_create_collection(
        name=settings.collection, metadata={"hnsw:space": "cosine"})
    metadata = {k: v for k, v in (collection.metadata or {}).items() if not k.startswith("hnsw:")}
    state = json.loads(metadata.get("ragops_state", "{}"))
    if not state and collection.count():
        raise ValueError("incremental mode requires a fresh collection or an existing RAGOps collection")
    if state and state["signature"] != signature:
        raise ValueError("pipeline settings changed; use a fresh collection")
    previous = state.get("documents", {})
    pins = dict(state.get("pins", {}))
    entries = inventory(lake)
    marker = lake / ".ragops-lake-id"
    lake_id = marker.read_text(encoding="ascii").strip() if marker.is_file() else ""
    if metadata.get("ragops_lake_id") and metadata["ragops_lake_id"] != lake_id:
        raise ValueError("data lake identity differs from the indexed inventory")
    if not lake_id:
        if not entries:
            raise ValueError("cannot initialize an empty data lake")
        lake_id = uuid4().hex
        marker.write_text(lake_id, encoding="ascii")
    metadata["ragops_lake_id"] = lake_id
    if rollback is not None:
        doc_id, version = rollback
        matches = [record for record in previous.values()
                   if record["document_id"] == doc_id and record["version"] == version
                   and record["superseded"]]
        if len(matches) != 1:
            raise ValueError("expected exactly one archived document for that version")
        restored = matches[0]
        target = lake / restored["file"]
        if target.exists() and fingerprint(target) != restored["content_hash"]:
            raise ValueError(f"cannot overwrite changed lake file {target.name}")
        copy_verified(archive / archive_name(restored), target, restored["content_hash"])
        entries[target.name] = restored["input_metadata"]
        pins[doc_id] = version

    # Keep historical payloads and vectors while the corresponding family remains active.
    records = {key: record for key, record in previous.items() if record["superseded"]}
    chunks: dict[str, list[Chunk]] = {}
    moves: list[tuple[Path, Path, str]] = []
    rows = []
    unchanged = 0
    known_files = {record["file"] for record in previous.values()}
    for filename in sorted(entries, key=lambda name: (name not in known_files, name)):
        entry = entries[filename]
        path = lake / filename
        digest = fingerprint(path)
        key = json.dumps([entry.get("document_id"), entry.get("version")])
        old = previous.get(key)
        if old and old["file"] == filename and old["content_hash"] == digest and (
                old["input_metadata"] == entry):
            records[key] = old
            checks = old["checks"].copy()
            unchanged += 1
        else:
            document, checks, vector = verify(path, {**entry, "content_hash": digest}, settings)
            exact = next((record for record in records.values()
                          if record["content_hash"] == digest and record["file"] != filename), None)
            near = next((record for record in records.values()
                         if record["document_id"] != entry.get("document_id") and vector
                         and similarity(vector, record["verification_vector"]) >= 0.985), None)
            collision = key in records and records[key]["file"] != filename
            checks["uniqueness"] = result(
                not exact and not near and not collision,
                f'exact SHA-256 duplicate of {exact["file"]}' if exact else
                f'near duplicate of {near["file"]} (cosine >= 0.985)' if near else
                "logical ID and version collide" if collision else "no duplicate found")
            if document is None or any(check["status"] == "fail" for check in checks.values()):
                checks["recency"] = result(False, "excluded before version selection")
                moves.append((path, quarantine / f"{digest}-{filename}", digest))
                rows.append({"file": filename, "document_id": entry.get("document_id"),
                             "disposition": "quarantine", "checks": checks})
                continue
            pieces = chunk(clean(document), settings.chunk_size, settings.chunk_overlap,
                           settings.chunk_strategy)
            if not pieces:
                raise ValueError(f"verified document produced no chunks: {filename}")
            chunks[key] = pieces
            records[key] = {
                "file": filename, "document_id": entry["document_id"], "version": entry["version"],
                "content_hash": digest, "input_metadata": entry, "verification_vector": vector,
                "chunk_ids": [piece.id for piece in pieces], "superseded": False, "checks": checks,
            }
        rows.append({"file": filename, "document_id": entry["document_id"], "key": key})

    by_key = {row["key"]: row for row in rows if "key" in row}
    families: dict[str, list[str]] = {}
    for key in by_key:
        families.setdefault(records[key]["document_id"], []).append(key)
    records = {key: record for key, record in records.items() if record["document_id"] in families}
    pins = {doc_id: version for doc_id, version in pins.items() if doc_id in families}
    for doc_id, keys in families.items():
        winner = next((key for key in keys if records[key]["version"] == pins.get(doc_id)), None)
        if winner is None:
            pins.pop(doc_id, None)
            winner = max(keys, key=lambda key: (version_key(records[key]), records[key]["version"]))
        for key, record in list(records.items()):
            if record["document_id"] != doc_id:
                continue
            superseded = key != winner
            checks = {**record["checks"], "recency": result(
                not superseded, "archived older or inactive version" if superseded else
                "active version selected")}
            records[key] = {**record, "superseded": superseded, "checks": checks}
            if key in by_key:
                by_key[key].update(disposition="archive" if superseded else "active", checks=checks)
                if superseded:
                    moves.append((lake / record["file"], archive / archive_name(record),
                                  record["content_hash"]))

    # Stage all files before publishing state. A retry can reconcile an interrupted
    # Chroma write because the prior inventory is retained until the final modify().
    for source, destination, digest in moves:
        copy_verified(source, destination, digest)
    counts = write_changes(collection, metadata, records, chunks, signature, pins, settings, backend)
    for source, _, digest in moves:
        if fingerprint(source) == digest:
            source.unlink()
    counters = {
        "scanned": len(entries), "quarantined": sum(row["disposition"] == "quarantine" for row in rows),
        "unchanged": unchanged, "updated": len(chunks), "deleted": len(previous.keys() - records.keys()),
        "chunks_embedded": sum(map(len, chunks.values())), "orphan_chunks": 0,
    }
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    report = reports / f"verification_{timestamp}_{uuid4().hex[:8]}.json"
    report.write_text(json.dumps({"counts": counters, "chunks_by_document": counts,
                                  "documents": rows}, indent=2) + "\n", encoding="utf-8")
    print(f'{"Document":<55} {"Disposition":<12} Quality Completeness Recency Uniqueness')
    for row in rows:
        checks = row["checks"]
        statuses = " ".join(checks[name]["status"].ljust(width) for name, width in
                            (("quality", 7), ("completeness", 12), ("recency", 7), ("uniqueness", 10)))
        print(f'{row["file"]:<55} {row["disposition"]:<12} {statuses}')
    print(" ".join(f"{key}={value}" for key, value in counters.items()), flush=True)
    return sum(counts.values())


def write_changes(collection: Any, metadata: dict[str, Any], records: dict[str, Any],
                  chunks: dict[str, list[Chunk]], signature: list, pins: dict,
                  settings: IndexerSettings, backend: str) -> dict[str, int]:
    desired = {chunk_id: record for record in records.values() for chunk_id in record["chunk_ids"]}
    stored = collection.get(include=["metadatas"])
    actual = dict(zip(stored["ids"], stored["metadatas"], strict=True))
    batches = [piece for group in chunks.values() for piece in group]
    missing = desired.keys() - actual.keys() - {piece.id for piece in batches}
    if missing:
        raise RuntimeError("indexed inventory references missing Chroma chunks")
    vectors, dimension = embed([piece.text for piece in batches], settings) if batches else (
        [], metadata.get("embed_dim"))
    stale = sorted(actual.keys() - desired.keys())
    flags = [key for key in actual.keys() & desired.keys()
             if actual[key].get("superseded") != desired[key]["superseded"]]
    state = json.dumps({"signature": signature, "documents": records, "pins": pins}, sort_keys=True)
    if state != metadata.get("ragops_state") or stale or flags or batches or (
            metadata.get("index_state") != "ready"):
        empty_state = json.dumps({"signature": signature, "documents": {}, "pins": {}})
        collection.modify(metadata={"ragops_state": empty_state, **metadata, "index_state": "building"})
        for offset in range(0, len(batches), 100):
            batch = batches[offset:offset + 100]
            collection.upsert(ids=[piece.id for piece in batch],
                              documents=[piece.text for piece in batch],
                              embeddings=vectors[offset:offset + 100],
                              metadatas=[{**piece.metadata(),
                                          "document_id": desired[piece.id]["document_id"],
                                          "superseded": desired[piece.id]["superseded"]}
                                         for piece in batch])
        for offset in range(0, len(flags), 100):
            ids = flags[offset:offset + 100]
            collection.update(ids=ids, metadatas=[{"superseded": desired[key]["superseded"]}
                                                for key in ids])
        for offset in range(0, len(stale), 100):
            collection.delete(ids=stale[offset:offset + 100])
        if set(collection.get(include=[])["ids"]) != desired.keys():
            raise RuntimeError("stored chunks do not match the document inventory")
        published = {**metadata, "ragops_state": state, "index_state": "ready",
                     "index_revision": uuid4().hex, "embed_model": settings.embed_model,
                     "embed_version": signature[1], "embedding_backend": backend}
        if dimension is not None:
            published.update(embed_dim=dimension, dimension=dimension)
        collection.modify(metadata=published)
    counts: dict[str, int] = {}
    for record in desired.values():
        doc_id = record["document_id"]
        counts[doc_id] = counts.get(doc_id, 0) + 1
    return counts
