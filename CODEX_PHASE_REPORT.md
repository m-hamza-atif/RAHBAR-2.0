# Partner B · Assignment 03 verification record

**Branch** `feat/ragops-k8s-report` · **base** `3a71ce97a9e3078e7362b239333d20b1eae73956` · **namespace** `rahbar` on `kind-rahbar-asg3`.

The original checkout was clean on `main`. After fetching the intended origin, local `dev` and `origin/dev` had the same SHA. Commit `eeff155` introduced the contract and `3a71ce9` supplied Partner A’s A–E implementation. The configured author email matches Partner B’s earlier repository commits and roll number. The workspace handoff, prompt and official five-page assignment were inspected. External references and Partner A’s tracking file are outside this change.

## Verification matrix

VERIFIED applies to the specific observation in the row. Partner A’s 42-question local experiment and Partner B’s fresh 48-question Kubernetes series use distinct provenance.

| ID | Requirement | Owner | Implementation | Verification / evidence | Status |
|---|---|---|---|---|---|
| A1 | Per-file reasons and quarantine | A | `indexer/pipeline/verify.py`, `indexer/pipeline/incremental.py` | Local 18-row report, five quarantines in `eval/results/drift_batch_b_verification_20261124-180937.json` | VERIFIED |
| A2 | Update, delete, no orphans, restore | A | `indexer/pipeline/incremental.py` | `indexer/tests/test_incremental.py` passed, saved Batch B report and Appendix A2 | VERIFIED |
| B1–B4 | Annotated questions, three levels, noise and repeat | A | `eval/golden.jsonl`, `eval/embedding_pairs.jsonl`, `eval/ragops_eval.py` | Local `eval/results/annotated-*`. 48 current questions; historical evaluation used 42. | VERIFIED |
| C1–C2 | Distinguish good/bad compatible reports | A | `eval/release_gate.py`, `eval/gate_config.yaml` | Saved local gate transcripts, scores and gates in report §3 | VERIFIED |
| C3 / F3 | Two API lanes, gated rollout, separate failure injection, undo and fresh trace | B | `k8s/overlays/asg3/{stable,candidate,api-services}.yaml`, `scripts/ragops_cluster.py` | Two independently indexed Services and actual bad-release undo verified (traces below). Normal promotion still needs an accepted fresh evaluation. | IMPLEMENTED — LIVE VERIFICATION PENDING |
| D1–D5 | Trace/inspection, metrics, rail action, five-line diagnosis | A | `api/app/services/trace.py`, `api/app/routes/metrics.py`, `scripts/{inspect_trace,summarize_traces}.py`, `docs/TRACE_ROOT_CAUSE_D5.md` | A’s D5 record and local probe IDs. B verified full live JSONL, exact reconstruction, post-restart persistence and stage metrics. See `traces/asg3-*.jsonl` and `docs/evidence/asg3-observability.txt`. Historical D5 screenshot still needs the original command. | VERIFIED |
| E1–E4 | Drift and test coverage | A | `corpus/batch_b/`, `eval/check_coverage.py`, `eval/live_queries.jsonl` | `eval/results/coverage_{before,after}.json`, local drift/probe files and `docs/RAGOPS_DRIFT.md` | VERIFIED |
| F1a | Persistent storage and independent seed | B | `k8s/base/{chroma,redis}.yaml`, `k8s/overlays/asg3/storage.yaml` | Six bound PVCs. Fresh pod read eight matching SHA-256s from each lake after both upload pods exited. `docs/evidence/asg3-{cluster,seeds}.txt` | VERIFIED |
| F1b / F4 | Serving replicas, trace persistence and metrics | B | Stable/candidate Deployments, inspection Deployment, `TRACE_DIR` | Two replicas replaced, original trace remained byte-equivalent as JSON, fresh trace matched stdout and PVC, loopback Service returned all five metric families. See `docs/evidence/asg3-{observability,port-forward}.txt` | VERIFIED |
| F2a | Lease-wrapped verified ingestion and weekly schedule | B | `k8s/overlays/asg3/{writer,candidate-writer,schedule}.yaml` | Completed stable, candidate, unchanged, isolated Batch B and June restore Jobs. CronJob spec matches the chosen lease-wrapped writer, with weekly schedule suspended during comparisons. | IMPLEMENTED — LIVE VERIFICATION PENDING |
| F2b | In-cluster suite and gate | B | `eval/{Dockerfile,cluster_job.py}`, `k8s/eval-job.yaml`, `k8s/overlays/asg3/gate.yaml` | Official standalone apply created rahbar-eval. Its evaluator was terminated on Docker shutdown during baseline scoring. New Job rahbar-eval-b2c5797b45 uses the original models, datasets and thresholds. | IMPLEMENTED — LIVE VERIFICATION PENDING |
| F2c | Threshold flip and restore on same image | B | `scripts/gate_threshold_demo.py` | Verified PASS → latency FAIL → restored PASS on archived 42-question scores, same image, plus degraded FAIL. Fresh 48-question pass/flip/restore remains a separate requirement. | IMPLEMENTED — LIVE VERIFICATION PENDING |
| F5 | Measure phases and justify resource bounds | B | Workload resources, `scripts/measure_k8s_resources.py` | Measured all six phases including concurrent, both APIs and the evaluator. See the actual timestamped series, `docs/evidence/asg3-concurrent-queries.txt` and report §3 | VERIFIED |
| CI1 | Original profiles and new objects | B | `.github/workflows/{ci,cd}.yml`, `scripts/validate_{manifests,asg3}.py`, `Makefile` | Local 3.12 tests and kubeconform; server dry-run of ASG3. Hosted CI remains a separate integration check. | VERIFIED |
| G1–G5 | Lifecycle, quality, measurements, six answers, contributions and AI | Both | `docs/REPORT_ASG3.md` | Reviewed official brief, paper §§3.2, 4.2, 5.1, 6.2 and local reports. Main-body QA print including the measured chart was five A4 pages before the fresh release comparison. | IMPLEMENTED — LIVE VERIFICATION PENDING |
| G6 | Full uncropped appendix and final PDF | Both | `appendix-screenshots/`, draft appendix, `k8s/README.md` | Feature-branch full-screen captures for A–F are under appendix-screenshots/cluster. Fresh quality-decision capture and post-merge evidence/PDF remain outstanding. | BLOCKED |
| V1 | Demonstration and viva preparation | B | `VIVA_GUIDE_PARTNER_B.md` | Timed 25-minute guide covering A–G and live failure modes; checked its commands against implemented CLIs | VERIFIED |

## Tests, boundaries and reproduction

- Python 3.14 on the host initially failed collection on missing dependencies. An isolated Python 3.12 environment with the repository pins resolved it. The original Windows suite passed 119 and skipped eight Linux/bash installer cases by design. Those eight passed independently in a Linux container. A Windows sandbox-only temporary-directory access error was resolved by running the suite with writable temporary files.
- The added tests exercise the actual rendered lanes, gate defaults, real CLI flags and propagation of both exit codes. `docs/evidence/asg3-tests.txt` records the final Windows suite. Kubeconform v0.6.7 passed all 30 objects for each legacy profile and 39 objects for ASG3 including the standalone Job and concrete model policy.
- The API, indexer and evaluator Docker builds use the original model configurations. Calico enforces the namespace policies on Kind v1.32.2. Only trusted API/indexer clients connect to Chroma; application code owns read versus write access. The stable and candidate writer use the same renewable lease.
- The cluster profile chooses a single top-k change (5 to 3 at floor 0.35), one of the official C1 variables. The older passing local floor experiment remains attributed to Partner A. API, indexer, evaluation references and Assignment 02’s default evaluator are preserved.
- The local-path provisioner requires one node for shared RWO traces and does not protect data from node/cluster deletion. Always export before cleanup. The model server uses its own private Docker volume outside the measured pod budgets.

## Screenshot checklist and final coordination

| Label | Actual command or source | Capture requirement |
|---|---|---|
| A1 | `python -m json.tool eval/results/drift_batch_b_verification_20261124-180937.json` | Include all checks and reasons, using consecutive full terminal views. |
| A2 | `python scripts/ragops_cluster.py index stable` repeated | Command, run ID and zero newly embedded chunks. |
| B | `kubectl -n rahbar logs job/rahbar-eval` | Module/component/end-to-end, noise report and repeat deltas. |
| C | `python scripts/ragops_cluster.py promote` with documented degraded and normal candidates | Rules, decisions, exit statuses and live revision before/after rejection. |
| D1–D2 | `python scripts/ragops_cluster.py trace` plus `kubectl -n rahbar exec deploy/ragops-inspect -- python scripts/inspect_trace.py --trace-id "$TRACE_ID"` | Full record and full reconstruction from the same ID. |
| E | The two coverage commands in the root README | Show golden inputs, command, both gate decisions and topics. |
| F1–F2 | `kubectl get all,pvc,configmap,cronjob,job -n rahbar`, `kubectl -n rahbar logs job/ACTUAL_JOB_NAME`, `python scripts/gate_threshold_demo.py` | Server inventory, ingestion and evaluation logs, patched thresholds and same image IDs. |
| F3–F5 | `python scripts/ragops_cluster.py bad-release-demo`, persisted ID after replacement, `kubectl -n rahbar top pods --containers` | Include actual rollout status, undo and fresh restored trace, measurement labels and limits. |

Nine existing A–E images are present. Several show selected fields or tables without the command. In particular A1 lacks reasons, D1 is abbreviated and E shows a summary. Partner A should supply original command-inclusive views and the full D trace/reconstruction, or the team should recapture from its own runs. No reconstructed screenshot is suitable.

After review, coordinate the merge to `dev`. Fetch the merged SHA and repeat the fresh-cluster runbook from that checkout using new images and result directories. Compare input hashes and revisions, collect screenshots, update the resource table and evidence matrix, then export one PDF and recheck the eight-page main limit. The later `dev` → `main` PR and submission belong to the team’s final coordination.

## Live milestones

- Docker Desktop allocated eight logical CPUs and about 7.6 GiB to the Linux engine. The laptop has an i7-1185G7, 16,872,693,760 bytes of system RAM and Intel Iris Xe graphics. Ollama reported CPU execution. The inspection pod verified both digests against the packaged manifest. See `docs/evidence/asg3-models.txt`.
- A new read-only pod verified all eight files on both persistent lakes after their seed pods were deleted. The host corpus contains 215 PDF pages. Chroma, Redis, metrics-server and Calico were ready. Both the rendered cluster resources and the official standalone Job passed server-side dry-run.
- Four Kubernetes Jobs ran the unmodified gate against archived **local 42-question reports**. The original candidate passed, setting the p95 ceiling to zero failed only latency, restoration passed, and the degraded report failed recall and faithfulness. All used the same container image ID. This isolates the ConfigMap effect independently of model timing. See `docs/evidence/asg3-historical-gate-replay.txt`. The fresh full-suite run is tracked separately.
- The updated workflows passed actionlint v1.7.7. API and indexer mypy checks passed on 27 and 13 source files respectively.

- Stable ingestion produced 875 chunks from eight files in 741.8 s. Its unchanged rerun finished in 3.3 s, embedded zero and reported zero orphans. Reports exported from the persistent state volume are under `eval/results/state-stable/`.
- A new in-cluster coverage run using the manifest model, untouched 40 queries and the original and extended golden sets reproduced 28/40 (expected exit 1) and 40/40 (exit 0). See `eval/results/k8s-coverage-{before,after}.json`.
- All 132 tests passed on Linux. Windows passed 124 and skipped eight Linux/bash installer cases. See `docs/evidence/asg3-{linux-tests,tests}.txt`.

- The independent candidate ingested the original eight files in 850.8 s, with 875 chunks and zero orphans. API, indexer, UI and evaluator images all built; see `docs/evidence/asg3-models.txt`. The final writer CPU request is 750m (previously 250m), with a 1500m limit, after observing a 1499m sampled peak. The model server has its own CPU/memory outside the pod budgets.
- Full-screen WSL xterm captures under `appendix-screenshots/cluster/` show the live commands for F2 ingestion, archived gate replay, both coverage datasets and complete trace/reconstruction. Each underlying PNG is the original capture, including the returned prompt. These supplement Partner A’s nine local images.

### Verified controlled rollback (C3/F3)

The operator ran `kubectl rollout undo deployment/rahbar-api` after exposing the intentionally bad release, waited for the stable Deployment, then checked a new query and reconstructed its trace. Before and after, the collection was `rahbar_policies` and the index revision was `dcfb2a4cde934baaaf968a2085aefa62`. The defective release used `rahbar_policies_candidate`, revision `7903cb132cb44d44a4785a99b8d9bb15`, k1/floor 0.99. Both collections used the same embedding digest. The restored answer used k5/floor 0.35, returned HTTP 200 and completed generation. Before, bad and restored trace IDs are respectively `3db555e992ac40b7b336b9394fd593cc`, `ca287eb9dc4044e39b80877b86251496` and `58a50ef8465046589110d1c0fb147e80`. See `docs/evidence/asg3-rollback.txt` and `traces/`.

## Recovery and live evidence

The archive experiment completed. The third, isolated lake verified five quarantines, six new chunks and zero orphans on Batch B. Its restore Job returned the June 2026 handbook to active status with no re-embedding. The four full reports are in `eval/results/drift-bcf7357e1f/`. The two simultaneous requests completed against independent revisions. Their retrieval configurations, status codes and stage timings are in `docs/evidence/asg3-concurrent-queries.txt`.

The official `kubectl apply -f k8s/eval-job.yaml` created the fresh 48-question Job. The Docker engine then stopped. Kubernetes recorded failure and the subprocess log shows SIGTERM during the baseline pass. Only the threshold snapshot was present in the result directory. The controller never reached the promotion patch. Evidence: `docs/evidence/asg3-interrupted-job.txt` and `docs/evidence/asg3-promotion.txt`. Docker, the same Kind node and model container recovered using their existing volumes. Both API Deployments became Ready and both model digests matched. The new comparison is `rahbar-eval-b2c5797b45`; the fresh gate decision and promotion verdict remain open until it finishes.

The final release review must check the fresh Job status, export its paired reports and gate decision, and keep an unsuccessful quality decision distinct from a transport or runtime failure. After comparisons, enable the weekly writer against the serving collection with `python scripts/ragops_cluster.py sync-cron`. The final main-body PDF and integration-branch screenshots follow the coordinated merge.
