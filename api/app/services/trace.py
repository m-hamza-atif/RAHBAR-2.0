"""One JSONL record per processed query, with the actual model message payload."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from ..config import Settings
from ..logjson import request_id_var

log = logging.getLogger("rahbar.trace")
STAGES = ("cache", "embed", "retrieve", "rerank", "generate", "total")
CURRENT_TRACE: ContextVar[QueryTrace | None] = ContextVar("query_trace", default=None)
_output_lock = threading.Lock()


class QueryTrace:
    def __init__(self, question: str, settings: Settings, provider: str) -> None:
        self.started = perf_counter()
        self.trace_id = uuid4().hex
        self.timing = dict.fromkeys((f"{stage}_ms" for stage in STAGES), 0.0)
        self.actions: list[dict[str, Any]] = []
        self.attempts: list[dict[str, Any]] = []
        self.filters: dict[str, Any] = {"relevance_floor": settings.relevance_floor}
        self.record: dict[str, Any] = {
            "trace_id": self.trace_id,
            "request_id": request_id_var.get(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_query": question,
            "rewritten_query": question,
            "embedding_model": settings.embed_model,
            "embedding_version": settings.embed_version or None,
            "collection_name": settings.collection,
            "index_revision": None,
            "retrieved_chunks": [],
            "filters_applied": self.filters,
            "reranked_order": [],
            "top1_similarity": None,
            "context_passages": [],
            "prompt_hash": None,
            "full_prompt": None,
            "prompt_attempts": self.attempts,
            "generation_status": "skipped",
            "generation_skip_reason": None,
            "generation_question": None,
            "provider": provider,
            "model": "stub" if provider == "stub" else settings.llm_model,
            "model_params": {"temperature": settings.temperature, "top_k": settings.top_k,
                             "relevance_floor": settings.relevance_floor,
                             "seed": settings.generation_seed},
            "response": None,
            "citations": [],
            "guardrail_actions": self.actions,
            "latency_per_stage": self.timing,
            "cache_hit": False,
            "cache_source_trace_id": None,
            "abstained": None,
            "status": 500,
        }

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        started = perf_counter()
        try:
            yield
        finally:
            self.timing[f"{name}_ms"] += (perf_counter() - started) * 1000

    def finish(self) -> None:
        self.timing["total_ms"] = (perf_counter() - self.started) * 1000
        for stage, duration in self.timing.items():
            self.timing[stage] = round(duration, 3)

    def emit(self, directory: str) -> bool:
        # O_APPEND and one write keep a complete line together across replicas
        # sharing a filesystem with POSIX atomic append semantics.
        payload = json.dumps(self.record, ensure_ascii=True, separators=(",", ":")) + "\n"
        stdout_ok = True
        with _output_lock:
            try:
                sys.stdout.write(payload)
                sys.stdout.flush()
            except OSError:
                log.exception("trace_stdout_failed", extra={"trace_id": self.trace_id})
                stdout_ok = False
            try:
                path = Path(directory) / "queries.jsonl"
                path.parent.mkdir(parents=True, exist_ok=True)
                flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0)
                fd = os.open(path, flags, 0o600)
                try:
                    data = payload.encode("utf-8")
                    if os.write(fd, data) != len(data):
                        raise OSError("incomplete trace append")
                finally:
                    os.close(fd)
            except OSError:
                log.exception("trace_write_failed", extra={"trace_id": self.trace_id})
                return False
        return stdout_ok


def record_prompt(prompt: list[dict[str, str]]) -> None:
    trace = CURRENT_TRACE.get()
    if trace is not None:
        canonical = json.dumps(prompt, ensure_ascii=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        trace.record.update(full_prompt=prompt, prompt_hash=digest)
        trace.attempts.append({"prompt_hash": digest, "messages": prompt})


def record_retrieval_filter(scope: str, where: dict | None) -> None:
    trace = CURRENT_TRACE.get()
    if trace is not None:
        trace.filters.update(version_scope=scope, chroma_where=where)
