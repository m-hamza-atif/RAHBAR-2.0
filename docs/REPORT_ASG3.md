# RAHBAR 2.0 · Assignment 03 — RAGOps

**National University of Computer and Emerging Sciences, Islamabad**
Department of Software Engineering · CS4032 Software Construction and Development · Fall 2026
**M. Hamza Atif (24I-3160) · M. Huzaima (24I-3014)**

**Decision under review.** Partner A’s 42-question local experiment accepted the higher retrieval floor and rejected a deliberately degraded pipeline. The current golden set has 48 questions. The Kubernetes release requires a new compatible pair of reports. The two experiments use separate result series.

## 1. Lifecycle mapping

RAHBAR answers questions about university policies. Its answer can change when a handbook is superseded, even if the application image stays the same. Figure 3 connects this data lifecycle with the lifecycle of the query pipeline. Sections 3.2 and 4.2 distinguish request processing, data management, offline testing and coverage. Table 1 motivates testing at multiple levels. [Xu et al., RAGOps, Figure 3 and Tables 1–2](https://arxiv.org/html/2506.03401v1)

| Stage | RAHBAR implementation and source | Boundary |
|---|---|---|
| Ingest | `corpus/fetch.py` downloads the eight entries in `corpus/sources.yaml`. `scripts/ragops_cluster.py` verifies the manifest before seeding each lake. | The upstream site can revise bytes. |
| Verify | `indexer/pipeline/verify.py` and `incremental.py` check extraction, metadata, duplicate content and editions before chunking. | Readable malicious instructions can pass document verification. |
| Update data lake | `indexer/pipeline/incremental.py` archives old bytes, quarantines failures and checks the persisted lake ID. | The active directory represents the full current inventory. |
| Update retrieval sources | `indexer/entrypoint.py` takes the Redis lease. `incremental.py` reconciles Chroma chunks and publishes the revision. | Changing an embedding signature requires a fresh collection. |
| Offline testing | `eval/ragops_eval.py` measures embeddings, ranked retrieval and answers. `eval/release_gate.py` checks compatible reports. | Label coverage and regex-based scoring limit the conclusions. |
| Live testing | `k8s/eval-job.yaml`, `k8s/overlays/asg3/candidate.yaml` and `scripts/ragops_cluster.py` compare two in-cluster Services and inspect a fresh trace. | Candidate traffic consists of test queries. |
| Check coverage | `eval/check_coverage.py` matches each live query to its nearest golden question. | Simulated usage and semantic similarity do not establish answer correctness. |

## 2. Quality attributes

| Quality | Measure and decision criterion | Evidence and interpretation |
|---|---|---|
| Adaptability | Unchanged input should embed zero new chunks. Superseded bytes must remain restorable. | Local Batch B added six chunks with zero orphans. `eval/results/drift_batch_b_verification_20261124-180937.json` |
| Monitorability | Recall@5 loss ≤0.02 and p95 ≤20 s. Two percentage points limit retrieval regression. The latency ceiling is above both measured local p95 values. | `eval/gate_config.yaml` and the two local gate transcripts. |
| Observability | Check abstention, cache hits, top-1 similarity, stage p95 and injection flags. An injected instruction must produce a recorded rail action when encountered. | `scripts/summarize_traces.py`, `api/app/routes/metrics.py`. Local transcript probe recorded `injection_text_removed`. |
| Traceability | One trace ID per processed query, with retrievable prompt/context and the collection, model and index revisions. | `api/app/services/trace.py`, `scripts/inspect_trace.py` and the D5 instance below. |
| Reliability | Readiness requires a usable index and Redis. The rollout permits zero unavailable replicas. Measure workload CPU and memory against configured budgets during operation. | `api/app/services/readiness.py`, `k8s/overlays/asg3/stable.yaml` and F5 evidence below. |

Faithfulness ≥0.70 holds the reference score near the observed local baseline of 0.703. Abstention correctness ≥0.80 requires four of five historical negatives to abstain. The implemented abstention rule is an absolute floor. These are application choices. Section 6.2 of the paper explains the difficulty of choosing comparable evaluation metrics. [Xu et al., §6.2](https://arxiv.org/html/2506.03401v1#S6.SS2)

## 3. Experimental results

**Parts A and E · local data changes.** Batch B supplied 11 synthetic inputs. Of 18 active-lake files scanned, seven were unchanged, six updated, five quarantined, six chunks embedded and zero orphans remained. The June academic handbook moved to the archive. A second run on identical input is shown in Appendix A2. The expected behavior for deletion, updates and restore is exercised by `indexer/tests/test_incremental.py`.

| Frozen 42-question drift comparison | Batch A | After Batch B |
|---|---:|---:|
| Recall@3 / recall@5 | 1.000 / 1.000 | 0.297 / 0.297 |
| MRR / nDCG@5 | 0.968 / 0.974 | 0.279 / 0.284 |
| Faithfulness / citation validity | 0.703 / 1.000 | 0.216 / 1.000 |
| p50 / p95 seconds | 3.58 / 7.42 | 5.24 / 22.70 |

![Local experiments. Recall and faithfulness fell after Batch B, while adding six golden questions raised coverage from 28 of 40 to 40 of 40.](figures/ragops-local-results.png)

The fictional November edition omitted previously labeled sections. Historical filtering uses years, so a month-specific question can retrieve the wrong edition. Coverage at cosine ≥0.78 rose from **28/40 (70%)** to **40/40 (100%)** after six questions addressing printing, lost property, music equipment, prayer rooms, sports bookings and visitor parking. The target was 85%. Sources are `docs/RAGOPS_DRIFT.md` and `eval/results/coverage_{before,after}.json`.

**Parts B and C · Partner A’s local comparison.** Each column uses the same 42 questions and embedding-pair hash. Each embedding group contained 15 pairs. The current 48-question dataset contains eight human-authored items and eight reviewed synthetic items.

| Local measurement | Stable 0.35 / k5 | Candidate 0.42 / k5 | Degraded 0.99 / k1 |
|---|---:|---:|---:|
| Paraphrase / unrelated cosine | 0.699 / 0.411 | 0.699 / 0.411 | 0.699 / 0.411 |
| Embedding gap / maximum repeat difference | 0.287 / 0 | 0.287 / 0 | 0.287 / 0 |
| Mean embedding time, ms | 63.05 | 112.11 | 45.29 |
| Recall@3 / @5 | 1 / 1 | 1 / 1 | 0 / 0 |
| MRR / nDCG@5 | 0.968 / 0.974 | 0.968 / 0.974 | 0 / 0 |
| Faithfulness / abstention correctness | 0.703 / 1 | 0.703 / 1 | 0 / 1 |
| Citation validity | 1 (61 citations) | 1 (61) | Undefined (0) |
| End-to-end p50 / p95, seconds | 3.58 / 7.42 | 5.01 / 10.85 | 0.28 / 0.33 |
| Local release gate | Reference | Pass, all four rules | Reject, recall and faithfulness |

Three typo probes produced zero mean change on all four retrieval metrics. Repeating the stable suite with seed 42 preserved all quality metrics and increased p50 by 2.43 s and p95 by 4.30 s. Seeded sampling cannot fix scheduling or model warm-up. Source files are the `eval/results/annotated-*` reports and gate transcripts dated 20261124.

**Part D · five-line trace-only diagnosis.**

1. Trace `4044ec61c6a84c4685da7be954b8f043` asked about attendance, excused absence and consequences.
2. The prompt included June handbook clauses 1.21 and 1.22 from physical page 10.
3. Clause 1.22 gave two consequences, exam ineligibility and an F/A grade.
4. Generation cited clause 1.22 and returned only exam ineligibility.
5. The omission arose during generation. The missing fact was already in the context.

Source `docs/TRACE_ROOT_CAUSE_D5.md`. In a 60-minute cluster window, two academic-warning requests had top-1 similarity 0.808, zero cache hits and zero injection flags. One abstained after a timeout during concurrent indexing. Stage p95 was 5.54 s for embedding, 0.42 s for retrieval and 242.50 s for generation. A later request completed generation, and its stdout and PVC records matched. Sample size limits generalization. See `docs/evidence/asg3-trace-summary.json`.

**Part F · cluster evidence.** The stable Service and the candidate Service select disjoint API pods. The cluster experiment changes one assigned variable, top-k from 5 to 3, at a fixed 0.35 floor. Both use `nomic-embed-text` and `llama3.2:3b`. The evaluator snapshots the thresholds and runs the full suite twice per Service. A failed Job prevents promotion. The separate bad-release drill switched live to the retained candidate collection, k1/floor 0.99, which abstained. After `kubectl rollout undo`, trace `58a50ef8465046589110d1c0fb147e80` answered from stable `rahbar_policies`, revision `dcfb2a4cde934baaaf968a2085aefa62`, at k5/floor 0.35. The embedding version stayed fixed.

| Workload | CPU request / limit | Memory request / limit | Measurement basis |
|---|---:|---:|---|
| Stable and candidate API, each | 100m / 500m | 128 / 512 Mi | Stable reached 489m / 114 Mi, candidate 59m / 100 Mi during the measured request and rollout windows. The 500m cap accommodates the startup burst. |
| Chroma | 250m / 1000m | 256 / 1024 Mi | Indexing and queries reached 201m / 120 Mi. The 250m CPU reservation covers this sampled demand. |
| Redis | 100m / 500m | 64 / 256 Mi | Cache and lease activity reached 280m / 16 Mi. The 500m limit accommodates short CPU bursts. |
| Ingestion and schedule | 750m / 1500m | 512 / 1536 Mi | Stable ingestion reached 1499m and 346 Mi. Increase the request from 250m to reserve half the measured CPU peak while allowing OCR to use the full limit. |
| Evaluation | 100m / 500m | 128 / 384 Mi | Early active sample reached 141m / 44 Mi. The 500m limit allows CPU bursts above the request. |

The two independent Batch A Jobs embedded 875 chunks each and left zero orphans. The stable unchanged rerun embedded zero in 3.3 s. In a third lake, Batch B quarantined five files and embedded six chunks. The archive Job restored the June handbook, with zero newly embedded chunks. The CronJob controller launched a repeat on the isolated lake and produced zero new chunks and zero orphans. Concurrent requests completed on both Services (184.10 s stable and 211.73 s candidate). These timings include workload contention. Four Jobs replaying the archived 42-question scores produced PASS, latency FAIL after patch, restored PASS and degraded FAIL on the same evaluator image. The first fresh 48-question Job received SIGTERM on Docker shutdown before it wrote scores. The recovery Job `rahbar-eval-b2c5797b45` scored all 48 stable questions in its first pass. A Redis restart returned HTTP 503 during the repeat, before the reports and gate were written. All 48 first-pass stable requests exceeded 20 s, with p95 111.50 s. The current evaluator preserves first-pass reports and includes bounded dependency retry time in latency. A separate Windows Intel Vulkan replay of one recorded prompt took 71.41 s cold and 21.46 s warm with the same model and prompt options.

## 4. Short answers

**4(a).** Uniqueness caused three quarantines (two hash matches and one semantic duplicate). Completeness caused two. Recency has six recorded failures, including five downstream exclusions, so counting raw failure flags overstates its role. The injected prose passed ingestion. A content-level injection detector could flag it before indexing. The existing retrieval rail acted on it at query time.

**4(b).** The degraded candidate retained a 0.287 embedding gap and exact repeatability. Its retrieval settings eliminated all gold hits, dropping recall@5 and faithfulness to zero.

**4(c).** We archive superseded versions and filter them from ordinary retrieval. Deletion would remove the bytes needed to restore an edition and weaken reproducibility of historical answers.

**4(d).** Reference faithfulness is the least trustworthy measure. Its patterns can reject a valid paraphrase or accept required facts while overlooking an extra unsupported claim. Citation validity stayed perfect after Batch B despite worse answers.

**4(e).** Coordinating data changes with release decisions was the hardest part of this design. We adapted the paper’s live-testing cycle to a classroom workload with parallel collections, fixed golden questions, a hash-compatible gate and a trace check after rollback. Simulated usage constrains what this can prove about real users.

**4(f).** Jobs perform ingestion and evaluation. A CronJob schedules the writer and Redis serializes competing invocations. The Chroma StatefulSet owns durable vectors. PVCs retain input, history, results and traces. Deployments and their Services isolate stable and candidate reads. A mounted ConfigMap supplies thresholds, and Deployment revisions carry rollback settings.

## 5. Contributions and AI use

| Member | Scope |
|---|---|
| M. Hamza Atif · 24I-3160 | Data verification and incremental state, three-level evaluation, local change experiment and gate, traces, coverage, drift and A–E handoff. |
| M. Huzaima · 24I-3014 | Partner B branch for cluster integration, persistent volumes, orchestration, release procedure, CI and report preparation with Codex assistance. Live evidence status is recorded separately. |

Codex assisted with Kubernetes manifests, integration scripts, tests, evidence collection and report drafting.
The experimental tables use repository results. The team must review the final figures and capture the terminal appendix.

## Appendix · uncropped terminal evidence

The following positions belong after the eight-page main report. Use multiple full terminal views for long outputs, preserving the command and the entire output.

| Label | Required image | Existing material / completion |
|---|---|---|
| A1–A2 | Batch B reasons and unchanged counters | Cluster captures `verification.png` and `unchanged.png`. |
| B1–B2 | Three levels, noise and seeded repeat | `stored-evaluation.png` inspects Partner A’s saved baseline. |
| C1–C2 | Both gate decisions and four rules | `gates.png` shows the archived reports scored inside Kubernetes. |
| D1–D2 | Complete record and exact reconstruction | `trace.png` and `reconstruction.png` use the same cluster ID. |
| E1–E2 | Both coverage decisions | `coverage.png` shows the live checker and inputs. |
| F1 | Namespace inventory | `inventory.png` shows the actual cluster after restart. |
| F2 | Completed writer, evaluation and threshold edit | `unchanged.png` and `gates.png` cover ingestion and archived gate replay. Fresh quality run tracked in the audit. |
| F3 | Rollout, undo, restored trace | `rollout.png`, `undo.png` and `restored-trace.png`. |
| F4–F5 | Trace after replacement and measured resources | `persistence.png`, `resources.png` and the timestamped sampling log. |

### Partner A’s existing local captures

**A-1 · Batch B disposition summary**

![Batch B disposition summary](../appendix-screenshots/Appendix-A-1.png)

**A-2 · Unchanged ingestion counters**

![Unchanged ingestion counters](../appendix-screenshots/Appendix-A-2.png)

**B-1 · Three evaluation levels**

![Three evaluation levels](../appendix-screenshots/Appendix-B-1.png)

**B-2 · Noise and seeded repeat**

![Noise and seeded repeat](../appendix-screenshots/Appendix-B-2.png)

**C-1 · Accepted local candidate**

![Accepted local candidate](../appendix-screenshots/Appendix-C-1.png)

**C-2 · Rejected local candidate**

![Rejected local candidate](../appendix-screenshots/Appendix-C-2.png)

**D-1 · Selected trace fields**

![Selected trace fields](../appendix-screenshots/Appendix-D-1.png)

**D-2 · Prompt reconstruction**

![Prompt reconstruction](../appendix-screenshots/Appendix-D-2.png)

**E · Coverage before and after**

![Coverage before and after](../appendix-screenshots/Appendix-E.png)

### Partner B’s feature-branch cluster captures

Each image is a full-screen capture of the interactive xterm running the displayed command against the assignment cluster or reading its exported public demonstration trace. The underlying PNGs retain their original resolution.

**A-2 / F2 · Unchanged incremental Job.** The completed writer reports seven unchanged files, zero newly embedded chunks and zero orphans.

![Completed unchanged ingestion Job](../appendix-screenshots/cluster/unchanged.png)

**C / F2 · Archived 42-question reports, gate executed in Kubernetes.** Four Jobs show the initial threshold, its zero-latency modification, the restored threshold and the degraded local candidate. The evaluator image ID and exit code appear beside each Job.

![Gate outcomes and evaluator image IDs](../appendix-screenshots/cluster/gates.png)

**D-1 · Complete public JSONL trace.** The stable API returned trace `7d5d7fff6ee3440cbdd44577aeee8337` for the academic-warning question. The full trace is also under `traces/`.

![Full exported cluster trace](../appendix-screenshots/cluster/trace.png)

**D-2 · Exact context and prompt.** The inspection pod reconstructed the same ID from the shared trace volume.

![Complete in-cluster prompt reconstruction](../appendix-screenshots/cluster/reconstruction.png)

**E · Coverage before and after six additional golden questions.** Both commands used the pinned embedding model and the same 40-query sample.

![Coverage before and after in the inspection pod](../appendix-screenshots/cluster/coverage.png)

**B · Partner A's archived baseline.** The terminal reads the stored report and displays its three evaluation levels, noise deltas and seeded repeat deltas.

![Historical evaluation levels and repeat](../appendix-screenshots/cluster/stored-evaluation.png)

**F3 · Stable rollout status and revision history.**

![Stable rollout status](../appendix-screenshots/cluster/rollout.png)

**F5 · Container usage during the archive and rollout exercise.** The complete time series and configured budgets are under `docs/evidence/k8s_resources_asg3.txt`.

![Metrics-server container measurements](../appendix-screenshots/cluster/resources.png)

**F3 · Deliberate release and actual rollback.** Both rollout-status commands completed. The following image shows the command that changed the live template and Kubernetes' response to the undo.

![Actual rollback and both rollout waits](../appendix-screenshots/cluster/undo.png)

**F4 · Trace persistence.** The original trace predates the serving pods shown above its inspection output. The summary reads the same persistent volume.

![Replacement pod creation times, original trace and summary](../appendix-screenshots/cluster/persistence.png)

**A1 · Batch B verification.** All four checks and reasons for every scanned file come from the isolated cluster Job’s persisted report.

![Batch B check reasons](../appendix-screenshots/cluster/verification.png)

**F1 · Cluster inventory after recovery.** The inventory includes the independently seeded lakes, experiment PVC, Services and original interrupted evaluation Job.

![Actual cluster inventory](../appendix-screenshots/cluster/inventory.png)

**F3 · Restored index, embedding and query configuration.** The operator inspected the before, defective and restored trace records in order.

![Verified trace fields from each release stage](../appendix-screenshots/cluster/restored-trace.png)

**F2 · Genuine 48-question degraded scoring Job.** This Job scored k1/floor 0.99 on a separate API Service. The paired gate compares these scores with the current stable report.

![Degraded evaluator’s complete terminal output](../appendix-screenshots/cluster/quality-degraded-score-458eb765.png)

**F2 · Scheduled writer.** Kubernetes automatically created this Job from the isolated CronJob template.

![Automatically scheduled writer’s complete terminal output](../appendix-screenshots/cluster/quality-asg3-schedule-proof-29929280.png)

**F2 · Recovery from a temporary dependency outage.** The new evaluator retried the isolated Service after an observed connection timeout.

![Cluster Job recovered and returned a fresh trace](../appendix-screenshots/cluster/quality-verify-retry-87def221.png)
