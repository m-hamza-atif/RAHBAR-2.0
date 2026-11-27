"""Regression coverage for page-level scoring, distinct ranks and gate inputs."""
from argparse import Namespace
from copy import deepcopy
import importlib
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def evaluation(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
    return importlib.import_module("ragops_eval"), importlib.import_module("release_gate")


def test_page_metrics_deduplicate_and_reject_the_wrong_version(evaluation):
    suite, _ = evaluation
    expected = [
        {"document_id": "rules", "source": "2026.pdf", "page": 19},
        {"document_id": "rules", "source": "2023.pdf", "page": 14},
    ]
    hits = [
        {"document_id": "rules", "source": "2023.pdf", "page": 19},
        expected[0], expected[0], {}, expected[1],
    ]
    scores = suite.retrieval_scores(expected, hits)
    assert scores["recall_at_3"] == .5
    assert scores["recall_at_5"] == 1
    assert scores["mrr"] == .5
    assert 0 < scores["ndcg_at_5"] < 1


def test_faithfulness_requires_facts_and_a_valid_gold_page_citation(evaluation):
    suite, _ = evaluation
    ref = {"document_id": "rules", "source": "rules.pdf", "section": "4.3", "page": 19}
    question = {"expected_facts": [["final.year"], ["additional|one more"]], "relevant": [ref]}
    response = {"answer": "A final-year student may take one additional course.",
                "answered_from_context": True, "retrieved": [ref], "citations": [ref]}
    assert suite.reference_faithfulness(question, response)
    assert not suite.reference_faithfulness(question, {**response, "answer": "Any student may add a course."})
    assert not suite.reference_faithfulness(question, {**response, "citations": [{**ref, "page": 20}]})


def test_release_gate_pass_fail_and_cross_dataset_rejection(evaluation):
    _, gate = evaluation
    profile = dict(embed_model="nomic", embed_dim=768, embed_version="immutable",
                   llm_provider="ollama-host", llm_model="llama3.2", temperature=.1, generation_seed=42)
    baseline = dict(schema="ragops-v1", cache_bypass=True, golden_sha256="golden", pairs_sha256="pairs",
                    configuration=profile, retrieval={"recall_at_5": .9},
                    end_to_end=dict(faithfulness=.8, p95_latency_ms=1000, abstention_correctness=1,
                                    faithfulness_method="reference_facts_and_gold_page_citation"))
    config = dict(max_recall5_drop=.02, min_faithfulness=.7, max_p95_latency_ms=2000,
                  min_abstention_correctness=.8)
    assert all(passed for _, passed, _ in gate.evaluate(baseline, deepcopy(baseline), config))
    decision = gate.evaluate(baseline, {**baseline, "retrieval": {"recall_at_5": .1}}, config)
    assert [passed for _, passed, _ in decision] == [False, True, True, True]
    with pytest.raises(ValueError, match="golden_sha256"):
        gate.evaluate(baseline, {**baseline, "golden_sha256": "other"}, config)


def test_draft_and_embedding_pairs_meet_content_counts(evaluation):
    suite, _ = evaluation
    directory = Path(__file__).resolve().parents[1]
    suite.validate_golden(suite.read_jsonl(directory / "golden.jsonl"))
    pairs = suite.read_jsonl(directory / "embedding_pairs.jsonl")
    assert {label: sum(pair["label"] == label for pair in pairs)
            for label in ("paraphrase", "unrelated")} == {"paraphrase": 15, "unrelated": 15}


@pytest.mark.parametrize("revision_changed", [False, True])
def test_cluster_retry_requires_same_revision(evaluation, monkeypatch, revision_changed):
    suite, _ = evaluation
    profile = {"configuration": {"top_k": 3}, "index_revision": "original"}
    requests = []
    delays = []
    monkeypatch.setattr(suite.time, "sleep", delays.append)

    def respond(request):
        requests.append(request)
        if request.url.path == "/readyz":
            if revision_changed and len(requests) == 3:
                return httpx.Response(200, json={**profile, "index_revision": "new"})
            return httpx.Response(200, json=profile)
        if len(requests) == 2:
            return httpx.Response(503)
        return httpx.Response(200, json={"trace_id": "fresh"})

    args = Namespace(api="http://candidate", cluster_retry=True)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        if revision_changed:
            with pytest.raises(ValueError, match="index changed"):
                suite.ask_with_retry(client, args, "Question", profile)
        else:
            assert suite.ask_with_retry(client, args, "Question", profile) == {"trace_id": "fresh"}
            assert requests[-1].headers["X-Cache-Bypass"] == "true"
    assert delays == [5]


def test_coverage_uses_nearest_question_and_inclusive_threshold(evaluation):
    coverage = importlib.import_module("check_coverage")
    model = {"loan renewal": [1, 0], "registration": [0, 1],
             "extend loan": [1, 0], "open pool": [-1, -1]}
    golden = [{"id": "a", "question": "loan renewal"}, {"id": "b", "question": "registration"}]
    live = [{"id": "1", "question": "extend loan", "topic": "library"},
            {"id": "2", "question": "open pool", "topic": "pool"}]
    covered, uncovered = coverage.score_coverage(live, golden, model.__getitem__, 1.0)
    assert covered["nearest_golden_id"] == "a" and covered["covered"]
    assert not uncovered["covered"]
