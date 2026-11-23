# RAGOps interface contract

Phase 0 coordination for Partner A (ingestion, API, evaluation and tracing) and Partner B (Kubernetes, release orchestration and evidence). The Assignment 03 commands below are implementation targets. Keep the Assignment 02 CLI and CI callers working during the transition.

## Shared storage

| Environment variable | Repo-root default | Kubernetes path |
| --- | --- | --- |
| `DATA_LAKE_DIR` | `./corpus/data_lake` | `/data/lake` |
| `QUARANTINE_DIR` | `./corpus/quarantine` | `/data/quarantine` |
| `ARCHIVE_DIR` | `./corpus/archive` | `/data/archive` |
| `VERIFICATION_REPORT_DIR` | `./corpus/reports` | `/data/reports` |
| `TRACE_DIR` | `./traces` | `/data/traces` |
| `EVAL_RESULTS_DIR` | `./eval/results` | `/data/eval-results` |

Local commands run from the repo root. Kubernetes sets absolute paths and persists outputs across Jobs and pod restarts. Grant the indexer write access to lake, quarantine, archive and reports, the API write access to traces, and the evaluator write access to results. Account for concurrent trace writers across API replicas and node scheduling when selecting storage. Mount trace data read-only in inspection Jobs and keep it internal.

## Shared settings

| Variable | Meaning and default |
| --- | --- |
| `CHROMA_COLLECTION` | Stable uses `rahbar_policies`. Candidate reader and writer both use `rahbar_policies_candidate`. |
| `EMBED_MODEL`, `EMBED_VERSION` | Model name and immutable model revision. Use `nomic-embed-text` for the real profile, with the verified model digest as the revision. Keep the existing `EMBED_DIM` pin. Writer and reader must agree on all three. Use an explicit stub revision in fixtures. |
| `CHUNK_SIZE`, `CHUNK_OVERLAP` | Whitespace tokens, default `512` and `64`. A change requires the target collection to be reindexed. |
| `TOP_K`, `RELEVANCE_FLOOR`, `CACHE_THRESHOLD` | Real-profile defaults `5`, `0.35`, `0.90`. Keep cache identity scoped to collection and index revision so stable and candidate can share Redis safely. |
| `LLM_PROVIDER` | `ollama-host` for real runs and `stub` for fixture CI. |
| `GATE_CONFIG_PATH` | Default `./eval/gate_config.yaml`. Mount ConfigMap `rahbar-gate-config` as a directory and set the path to `/etc/rahbar/gate/gate_config.yaml`. Each Job reads the current file at startup. |
| `COVERAGE_THRESHOLD` | Minimum fraction of covered live queries, default `0.85`. Separate from the cosine match threshold, default `0.78`. |

## CLI and outputs

Run these from the repo root under WSL. Kubernetes Jobs invoke the same Python entrypoints with their absolute volume paths and container Python. Keep forwarding flags through the writer lease wrapper. The current indexer image uses `python /app/entrypoint.py`, so its Job passes the same flags to that entrypoint. Package the eval scripts and their pinned dependencies in the evaluator image.

| Operation | Command | Output and exit behavior |
| --- | --- | --- |
| Verify and incrementally ingest | `uv run python -m indexer.entrypoint --incremental` | Writes `verification_<UTC-run-id>.json` and a stdout summary with per-document checks and the counters `scanned`, `quarantined`, `unchanged`, `updated`, `deleted`, `chunks_embedded`, `orphan_chunks`. Exit 0 after a successful update, including handled quarantines. Exit 1 on pipeline, consistency or lease failure. |
| Restore archived version | `uv run python -m indexer.entrypoint --rollback-doc DOC_ID --to-version VERSION` | Uses the same writer lease and target collection. Exit 0 after restoring the requested version and updating the active index revision, 1 if the archive entry is unavailable or restoration fails. |
| Run three-level evaluation | `uv run python eval/run_eval.py --suite ragops --api "$API_URL" --golden eval/golden.jsonl --embedding-pairs eval/embedding_pairs.jsonl` | Writes `eval_<UTC-run-id>.json` under `EVAL_RESULTS_DIR`. Optional `--out "$EVAL_RESULTS_DIR/candidate_<UTC-run-id>.json"` gives the Job a known path. `--host HOST` is available for Ingress. Exit 0 for a complete report, 1 on execution failure. Quality decisions use the separate gate. |
| Decide release | `uv run python eval/release_gate.py --baseline "$BASELINE_JSON" --candidate "$CANDIDATE_JSON" --config "$GATE_CONFIG_PATH"` | Prints pass/fail per rule. Exit 0 on pass, 1 on threshold failure or unusable input. Config defaults to `GATE_CONFIG_PATH` or the repo default when `--config` is omitted. Run after evaluation in the same Job and propagate its exit status. |
| Reconstruct a trace | `uv run python scripts/inspect_trace.py --trace-id TRACE_ID` | Prints the exact context and prompt recorded for that query. Exit 0 when the trace is found, 1 on a missing ID or unreadable trace store. For cache hits or early abstentions, record when generation was skipped. |
| Summarize traces | `uv run python scripts/summarize_traces.py --minutes 60` | Summarizes top-1 similarity, abstention, cache hits, p95 stage latency and injection flags over the UTC window. Exit 0 on a successful read and summary, 1 on data read or parse failure. |
| Check query coverage | `uv run python eval/check_coverage.py --live eval/live_queries.jsonl --golden eval/golden.jsonl --similarity-threshold 0.78` | Reports coverage fraction and uncovered topics. Exit 0 at or above `COVERAGE_THRESHOLD`, 1 below it or on execution error. Run the evaluation suite before and after Batch B for the separate drift comparison. |

Invalid CLI syntax exits 2. All run IDs use UTC and must avoid filename collisions. The gate compares reports from the same dataset and evaluation profile. Reports expose `retrieval.recall_at_5`, `end_to_end.faithfulness`, `end_to_end.p95_latency_ms` and `end_to_end.abstention_correctness`, with gate rules `max_recall5_drop`, `min_faithfulness`, `max_p95_latency_ms` and `min_abstention_correctness`. Rates use fractions and latency uses milliseconds.

Ingestion uses stable logical document IDs and explicit versions. An unchanged lake embeds zero chunks. Deletions remove the document's chunks. Archived superseded versions remain available for rollback and are excluded from normal retrieval. An incremental run treats the lake as the complete active inventory, so add Batch B to the existing lake before running it. Guard against a missing lake mount before processing deletions.

Each processed query emits the same JSONL trace record to stdout and persistent storage, keyed by `trace_id`. Include UTC timestamp, user and rewritten queries, collection and model versions, chunk IDs and scores, filters and ranking, exact context and prompt, response and citations, guardrail actions, per-stage latency and cache status. Include `trace_id` in the API response for evaluation and rollout evidence.
