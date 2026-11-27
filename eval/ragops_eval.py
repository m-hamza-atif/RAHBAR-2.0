"""Three-level evaluation with explicit evidence and repeatable cache bypass."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

from run_eval import ask, citation_validity, golden_digest


def read_jsonl(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()]
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"{path} requires nonempty JSON object rows")
    return rows


def validate_golden(rows: list[dict]) -> None:
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("golden IDs must be unique")
    for row in rows:
        if row["author"] not in {"human", "synthetic"}:
            raise ValueError(f"invalid authorship on {row['id']}")
        if not isinstance(row["answered_from_context"], bool):
            raise ValueError(f"invalid answerability on {row['id']}")
        if not row["answered_from_context"]:
            if row["relevant"] or row["expected_facts"] or row.get("noise_test"):
                raise ValueError(f"abstention row has answer evidence on {row['id']}")
            continue
        if (not row["relevant"] or not row["expected_facts"]
                or any(not ref["document_id"] or int(ref["page"]) < 1 for ref in row["relevant"])):
            raise ValueError(f"missing ground truth on {row['id']}")
        pages = {(ref["document_id"], ref.get("source"), ref["page"]) for ref in row["relevant"]}
        if len(pages) != len(row["relevant"]):
            raise ValueError(f"duplicate gold pages on {row['id']}")
        for alternatives in row["expected_facts"]:
            if not isinstance(alternatives, list) or not alternatives:
                raise ValueError(f"empty fact alternatives on {row['id']}")
            for pattern in alternatives:
                re.compile(pattern)
    if (len(rows) < 25 or sum(q["answered_from_context"] for q in rows) < 15
            or sum(not q["answered_from_context"] for q in rows) < 5
            or sum(bool(q.get("hard")) for q in rows) < 5):
        raise ValueError("golden set requires 25 questions, 15 answerable, 5 abstention and 5 hard")


def stub_embedding(text: str, dimension: int) -> list[float]:
    vector = [0.0] * dimension
    for token in re.findall(r"\w+(?:\.\w+)*", text.lower()):
        digest = hashlib.sha256(token.encode()).digest()
        vector[int.from_bytes(digest[:4], "big") % dimension] += 1 if digest[4] % 2 else -1
    if not any(vector):
        vector[0] = 1.0
    return vector


def similarity(left: list[float], right: list[float]) -> float:
    return sum(x * y for x, y in zip(left, right, strict=True)) / (
        math.hypot(*left) * math.hypot(*right))


def make_embedder(client: httpx.Client, profile: dict):
    dimension = int(profile["embed_dim"])
    stub = profile["llm_provider"] == "stub" or profile["embed_model"] == "stub"
    model_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")

    def embed(text: str) -> list[float]:
        if stub:
            return stub_embedding(text, dimension)
        response = client.post(model_url + "/api/embed", json={
            "model": profile["embed_model"], "input": [text], "truncate": False,
        })
        response.raise_for_status()
        vector, = response.json()["embeddings"]
        if len(vector) != dimension or not any(vector) or not all(map(math.isfinite, vector)):
            raise ValueError("embedding response differs from the API profile")
        return vector

    return embed


def embedding_level(client: httpx.Client, pairs: list[dict], profile: dict) -> dict:
    embed = make_embedder(client, profile)
    timings = []
    vectors = {}
    for text in dict.fromkeys(row[key] for row in pairs for key in ("left", "right")):
        started = time.perf_counter()
        vectors[text] = embed(text)
        timings.append((time.perf_counter() - started) * 1000)
    scores = {label: [similarity(vectors[row["left"]], vectors[row["right"]])
                      for row in pairs if row["label"] == label]
              for label in ("paraphrase", "unrelated")}
    if any(len(group) < 15 for group in scores.values()):
        raise ValueError("embedding benchmark requires at least 15 pairs of each label")
    first = next(iter(vectors))
    delta = max(abs(a - b) for a, b in zip(embed(first), vectors[first], strict=True))
    positive, negative = (statistics.mean(scores[label]) for label in ("paraphrase", "unrelated"))
    return {"paraphrase_mean_cosine": positive, "unrelated_mean_cosine": negative,
            "separation_gap": positive - negative, "mean_embedding_ms": statistics.mean(timings),
            "max_absolute_repeat_difference": delta,
            "pair_counts": {label: len(group) for label, group in scores.items()}}


def match(reference: dict, hit: dict) -> bool:
    source = reference.get("source")
    if source and hit.get("source") != source:
        return False
    identity = hit.get("document_id") == reference["document_id"] or (
        bool(source) and hit.get("document_id") in {None, source})
    edition = not reference.get("document_version") or (
        hit.get("document_version") == reference["document_version"])
    return identity and edition and hit.get("page") == reference["page"]


def retrieval_scores(expected: list[dict], retrieved: list[dict]) -> dict:
    seen = set()
    gains = []
    for hit in retrieved:
        new = next((index for index, ref in enumerate(expected)
                    if index not in seen and match(ref, hit)), None)
        gains.append(int(new is not None))
        if new is not None:
            seen.add(new)
    ideal = sum(1 / math.log2(rank + 2) for rank in range(min(5, len(expected))))
    return {
        "recall_at_3": sum(gains[:3]) / len(expected),
        "recall_at_5": sum(gains[:5]) / len(expected),
        "mrr": 1 / (gains.index(1) + 1) if any(gains) else 0.0,
        "ndcg_at_5": sum(gain / math.log2(rank + 2) for rank, gain in enumerate(gains[:5])) / ideal,
    }


def reference_faithfulness(question: dict, response: dict) -> bool:
    """Conservative reference-based proxy: required facts and a gold-page citation."""
    answer = response.get("answer", "").casefold()
    facts = all(any(re.search(pattern, answer) for pattern in alternatives)
                for alternatives in question["expected_facts"])
    # A citation lacks a logical ID or version, so join it to its retrieved ref.
    citation_keys = {(row["source"], row["section"], row["page"]) for row in response["citations"]}
    grounded = any((hit["source"], hit["section"], hit.get("page")) in citation_keys
                   and any(match(ref, hit) for ref in question["relevant"])
                   for hit in response["retrieved"])
    return bool(response["answered_from_context"] and facts and grounded
                and citation_validity(response) == 1.0)


def typo(question: str) -> str:
    return re.sub(r"\b(\w)(\w)(\w)(\w{3,})\b",
                  lambda match: match[1] + match[3] + match[2] + match[4], question, count=1)


def average_metrics(rows: list[dict]) -> dict:
    return {name: statistics.mean(row[name] for row in rows) for name in rows[0]}


def ask_with_retry(client: httpx.Client, args: argparse.Namespace, question: str,
                   readiness: dict, bypass_cache: bool = True) -> dict:
    if not args.cluster_retry:
        return ask(client, args.api, question, bypass_cache)
    for delay in (0, 5, 15, 30):
        if delay:
            time.sleep(delay)
        try:
            response = client.get(args.api.rstrip("/") + "/readyz")
            response.raise_for_status()
            current = response.json()
            if (current["configuration"] != readiness["configuration"] or
                    current["index_revision"] != readiness["index_revision"]):
                raise ValueError("API configuration or index changed during evaluation")
            return ask(client, args.api, question, bypass_cache)
        except (httpx.HTTPStatusError, httpx.ConnectError, httpx.ConnectTimeout) as exc:
            if delay == 30 or (isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code != 503):
                raise
            print(f"Brief API dependency outage ({type(exc).__name__}); retrying", flush=True)
    raise AssertionError("Retry loop exited without a result")


def run_once(args: argparse.Namespace, questions: list[dict], pairs: list[dict]) -> dict:
    random.seed(42)
    headers = {"Host": args.host} if args.host else {}
    with httpx.Client(timeout=args.timeout) as embed_client, httpx.Client(
        timeout=args.timeout, headers=headers
    ) as client:
        ready = client.get(args.api.rstrip("/") + "/readyz")
        ready.raise_for_status()
        profile = ready.json()["configuration"]
        if (args.stochasticity_check and profile["llm_provider"].startswith("ollama")
                and profile.get("generation_seed") is None):
            raise ValueError("set GENERATION_SEED on the API before an Ollama stochasticity check")
        embedding = embedding_level(embed_client, pairs, profile)
        rows = []
        for question in questions:
            started = time.perf_counter()
            response = ask_with_retry(client, args, question["question"], ready.json(),
                                      bypass_cache=not args.use_cache)
            latency = (time.perf_counter() - started) * 1000
            row = {"id": question["id"], "response": response, "latency_ms": latency}
            if question["answered_from_context"]:
                row["retrieval"] = retrieval_scores(question["relevant"], response["retrieved"])
                row["faithful"] = reference_faithfulness(question, response)
            else:
                row["correct_abstention"] = not response["answered_from_context"] and not response["citations"]
            rows.append(row)
            print(f"  {row['id']:<12} {latency:8.1f} ms", flush=True)
        noise = []
        for question, row in zip(questions, rows, strict=True):
            if not question.get("noise_test"):
                continue
            noisy = typo(question["question"])
            if noisy == question["question"]:
                raise ValueError(f"noise mutation made no change for {row['id']}")
            response = ask_with_retry(client, args, noisy, ready.json())
            noisy_scores = retrieval_scores(question["relevant"], response["retrieved"])
            noise.append({"id": row["id"], "question": noisy, "clean": row["retrieval"],
                          "noisy": noisy_scores,
                          "delta": {key: val - row["retrieval"][key] for key, val in noisy_scores.items()}})
        end = client.get(args.api.rstrip("/") + "/readyz")
        end.raise_for_status()
        if end.json().get("index_revision") != ready.json().get("index_revision"):
            raise ValueError("index changed during evaluation")
    if len(noise) < 3:
        raise ValueError("at least three answerable questions must be marked noise_test")
    latency = sorted(row["latency_ms"] for row in rows)
    citation_count = sum(len(row["response"]["citations"]) for row in rows)
    valid_citations = sum(round((citation_validity(row["response"]) or 0)
                                * len(row["response"]["citations"])) for row in rows)
    return {
        "schema": "ragops-v1", "configuration": profile, "index_revision": ready.json()["index_revision"],
        "golden_sha256": args.golden_sha256, "pairs_sha256": args.pairs_sha256,
        "cache_bypass": not args.use_cache,
        "annotation_status": {
            "human_written": sum(q["author"] == "human" for q in questions),
            "synthetic_reviewed": sum(q["author"] == "synthetic" and q.get("reviewed_by_human") is True
                                      for q in questions),
        },
        "embedding": embedding, "retrieval": average_metrics([r["retrieval"] for r in rows if "retrieval" in r]),
        "noise": {"rows": noise, "mean_delta": average_metrics([row["delta"] for row in noise])},
        "end_to_end": {
            "faithfulness": statistics.mean(r["faithful"] for r in rows if "faithful" in r),
            "faithfulness_method": "reference_facts_and_gold_page_citation",
            "citation_validity": valid_citations / citation_count if citation_count else None,
            "citation_count": citation_count,
            "abstention_correctness": statistics.mean(r["correct_abstention"] for r in rows if "correct_abstention" in r),
            "p50_latency_ms": statistics.median(latency),
            "p95_latency_ms": latency[math.ceil(len(latency) * .95) - 1],
        },
        "rows": rows,
    }


def run(args: argparse.Namespace) -> int:
    args.golden = args.golden or Path(__file__).with_name("golden.jsonl")
    results_dir = Path(os.getenv("EVAL_RESULTS_DIR", "./eval/results"))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = args.out or results_dir / f"eval_{stamp}_{uuid4().hex[:8]}.json"
    try:
        args.golden_sha256 = golden_digest(args.golden)
        args.pairs_sha256 = golden_digest(args.embedding_pairs)
        questions, pairs = read_jsonl(args.golden), read_jsonl(args.embedding_pairs)
        if (args.golden_sha256 != golden_digest(args.golden)
                or args.pairs_sha256 != golden_digest(args.embedding_pairs)):
            raise ValueError("evaluation data changed during loading")
        validate_golden(questions)
        report = run_once(args, questions, pairs)
        if args.stochasticity_check:
            if args.cluster_retry:
                out.parent.mkdir(parents=True, exist_ok=True)
                first = out.with_name(out.stem + ".first-pass.json")
                first.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            repeat = run_once(args, questions, pairs)
            if (repeat["configuration"] != report["configuration"] or
                    repeat["index_revision"] != report["index_revision"]):
                raise ValueError("API configuration or index changed between repeat passes")
            if repeat["index_revision"] != report["index_revision"]:
                raise ValueError("index changed between repeat runs")
            differences = {}
            for group in ("embedding", "retrieval", "end_to_end"):
                differences[group] = {key: repeat[group][key] - value
                                      for key, value in report[group].items()
                                      if isinstance(value, (int, float)) and repeat[group][key] is not None}
            differences["noise_mean_delta"] = {
                key: repeat["noise"]["mean_delta"][key] - value
                for key, value in report["noise"]["mean_delta"].items()}
            report["stochasticity"] = {
                "client_seed": 42, "generation_seed": report["configuration"].get("generation_seed"),
                "metric_deltas": differences, "repeat": repeat,
                "note": "Latency varies with warm-up, scheduling and model load. "
                        "A fixed Ollama seed controls sampling, while hardware and batching may still vary.",
            }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print("\nLevel          Metric                              Value")
        for group in ("embedding", "retrieval", "end_to_end"):
            for name, value in report[group].items():
                if isinstance(value, (float, int)):
                    print(f"{group:<14} {name:<34} {value:>10.4f}")
        if "stochasticity" in report:
            print("\nRepeat minus original")
            for group, values in report["stochasticity"]["metric_deltas"].items():
                for name, delta in values.items():
                    print(f"{group:<14} {name:<34} {delta:>+10.4f}")
        print(f"Report written to {out}")
    except (OSError, ValueError, KeyError, TypeError, re.error, httpx.HTTPError) as exc:
        print(f"Evaluation failed: {exc}")
        return 1
    return 0
