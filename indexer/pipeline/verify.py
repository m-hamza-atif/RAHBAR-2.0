"""Pre-chunking checks for the incremental data lake."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from pdfminer.pdfparser import PDFSyntaxError
from pdfplumber.utils.exceptions import PdfminerException

from .config import IndexerSettings
from .embed import embed
from .extract import extract
from .models import Document


def result(passed: bool, reason: str) -> dict[str, str]:
    return {"status": "pass" if passed else "fail", "reason": reason}


def verify(path: Path, meta: dict[str, Any], settings: IndexerSettings
           ) -> tuple[Document | None, dict[str, dict[str, str]], list[float]]:
    document = None
    extraction_error = ""
    try:
        document = extract(str(path), meta.get("version", ""), False, settings.enable_ocr)
    except (PDFSyntaxError, PdfminerException, UnicodeError, ValueError) as exc:
        extraction_error = f"extraction failed ({type(exc).__name__})"
    text = "\n".join(page.text for page in document.pages) if document else ""
    visible = [char for char in text if not char.isspace()]
    readable = bool(visible) and sum(char.isalpha() for char in visible) / len(visible) >= 0.35
    garbled = bool(visible) and sum(char == "\ufffd" or not char.isprintable()
                                  for char in visible) / len(visible) > 0.02
    quality = not extraction_error and readable and not garbled and len(visible) >= 40
    required = ("document_id", "source", "title", "version", "page_count")
    missing = [key for key in required if not meta.get(key)]
    expected_size = meta.get("bytes")
    expected_hash = meta.get("sha256")
    complete = (not missing and document is not None
                and str(meta["page_count"]) == str(len(document.pages))
                and (expected_size is None or str(expected_size) == str(path.stat().st_size))
                and (expected_hash is None or expected_hash == meta["content_hash"])
                and not text.rstrip().endswith("[TRUNCATED]"))
    checks = {
        "quality": result(quality, "readable extracted text" if quality else
                          extraction_error or "empty, too short or garbled text"),
        "completeness": result(complete, "required metadata and expected extent match" if complete else
                               f"missing metadata: {', '.join(missing)}" if missing else
                               "extraction, page count, size, checksum or end marker mismatch"),
    }
    if not quality or not complete:
        return document, checks, []
    # Use a bounded document sample so verification stays separate from chunk embeddings.
    normalized = " ".join(text.split())
    sample = normalized if len(normalized) <= 960 else normalized[:480] + " " + normalized[-480:]
    vectors, _ = embed([sample], settings)
    return document, checks, vectors[0]


def similarity(first: list[float], second: list[float]) -> float:
    return sum(a * b for a, b in zip(first, second, strict=True)) / (
        math.hypot(*first) * math.hypot(*second))
