"""Read the shared trace JSONL from the repository root or configured directory."""
from collections.abc import Iterator
import json
import os
from pathlib import Path
from typing import Any


def read_records() -> Iterator[dict[str, Any]]:
    path = Path(os.environ.get("TRACE_DIR", "./traces")) / "queries.jsonl"
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError("expected a JSON object")
            except ValueError as exc:
                raise ValueError(f"{path}:{number}: {exc}") from exc
            yield record
