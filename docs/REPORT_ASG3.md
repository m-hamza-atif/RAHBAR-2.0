# RAHBAR 2.0 · Assignment 03 — RAGOps

**National University of Computer and Emerging Sciences, Islamabad**

Department of Software Engineering · CS4032 Software Construction and Development · Fall 2026

**M. Hamza Atif (24I-3160) · M. Huzaima (24I-3014)**

**Submission · 27 November 2026.** The normal Kubernetes candidate completed the 48-question comparison and was rejected because p95 latency was 48.66 s against a 20 s limit. The stable revision remains in service. Partner A’s separate 42-question local comparison produced a passing candidate.

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

**Parts A and E · local data changes.** Batch B supplied 11 synthetic inputs. Of 18 active-lake files scanned, seven were unchanged, six updated, five quarantined, six chunks embedded and zero orphans remained. The June academic handbook moved to the archive. A second run on identical input is shown in Appendix A2. An isolated Kubernetes archive restoration reactivated the June edition with zero new chunks. The expected behavior for deletion, updates and restore is exercised by `indexer/tests/test_incremental.py`.

| Frozen 42-question drift comparison | Batch A | After Batch B |
|---|---:|---:|
| Recall@3 / recall@5 | 1.000 / 1.000 | 0.297 / 0.297 |
| MRR / nDCG@5 | 0.968 / 0.974 | 0.279 / 0.284 |
| Faithfulness / citation validity | 0.703 / 1.000 | 0.216 / 1.000 |
| p50 / p95 seconds | 3.58 / 7.42 | 5.24 / 22.70 |

![Local experiments. Recall and faithfulness fell after Batch B, while adding six golden questions raised coverage from 28 of 40 to 40 of 40.](figures/ragops-local-results.png)

The fictional November edition omitted previously labeled sections. Historical filtering uses years, so a month-specific question can retrieve the wrong edition. Coverage at cosine ≥0.78 rose from **28/40 (70%)** to **40/40 (100%)** after six questions addressing printing, lost property, music equipment, prayer rooms, sports bookings and visitor parking. The coverage target was 85%. The 0.78 cosine cutoff admits semantically similar questions when their wording differs. The in-cluster checker reproduced both coverage counts and decisions. Sources are `docs/RAGOPS_DRIFT.md` and `eval/results/coverage_{before,after}.json`.

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

Three typo probes produced zero mean change on all four retrieval metrics. Repeating the stable suite with seed 42 preserved all quality metrics and increased p50 by 2.43 s and p95 by 4.30 s. Seeded sampling cannot fix scheduling or model warm-up. Faithfulness uses reference facts and gold-page citations. Source files are the `eval/results/annotated-*` reports and gate transcripts dated 20261124.

### Parts B and C · 48-question Kubernetes comparison

Each profile used the same golden and embedding-pair hashes, pinned models, seed 42 and cache bypass. Stable and normal candidate each scored 48 questions and three typo probes twice. The degraded profile was scored in a separate run and compared with the stable first pass.

| Measurement | Stable k5 / 0.35 | Normal k3 / 0.35 | Degraded k1 / 0.99 |
|---|---:|---:|---:|
| Paraphrase / unrelated cosine / gap | 0.698 / 0.411 / 0.287 | 0.698 / 0.411 / 0.287 | 0.698 / 0.411 / 0.287 |
| Mean embedding ms / largest repeat difference | 288.51 / 0 | 84.05 / 0 | 186.56 / 0 |
| Recall@3 / recall@5 | 1.000 / 1.000 | 1.000 / 1.000 | 0.000 / 0.000 |
| MRR / nDCG@5 | 0.968 / 0.974 | 0.968 / 0.974 | 0.000 / 0.000 |
| Faithfulness / abstention correctness | 0.730 / 1.000 | 0.703 / 0.909 | 0.000 / 1.000 |
| Citation validity (count) | 1.000 (58) | 1.000 (84) | Undefined (0) |
| End-to-end p50 / p95, seconds | 30.81 / 102.20 | 29.30 / 48.66 | 1.26 / 4.94 |

| Seeded repeat minus first pass | Stable | Normal candidate |
|---|---:|---:|
| Mean embedding time, ms | −215.18 | −13.69 |
| End-to-end p50 / p95, seconds | +8.42 / −19.52 | +4.67 / +4.81 |
| Every other numeric metric | 0 | 0 |

The three typo probes produced zero mean deltas for Recall@3, Recall@5, MRR and nDCG@5 in every scored pass. The seeded repeats preserved embedding similarity and determinism, retrieval scores, answer quality, citation counts and abstention correctness. Timing varied across passes. Fixed seeds control sampling, while warm-up, host load and scheduling affect latency.

**Release decision · reject.** The normal candidate preserved Recall@5 (loss 0.0000 against a 0.02 maximum) and passed faithfulness (0.7027 against 0.70) and abstention (0.9091 against 0.80). Its p95 of 48.661 s exceeded the 20 s ceiling by 28.661 s. Both reports were written before the evaluator returned exit 1 through the Kubernetes Job. The separate degraded Job failed recall and faithfulness. After the normal gate, stable still served `rahbar_policies` at k5. A successful fresh normal-candidate Kubernetes promotion and post-promotion trace remain unverified. The successful local gate and previous bad-release undo are recorded separately.

Source reports and gate output are under `eval/results/5df892be-9cef-4988-934a-0be12c072f24/`. The degraded report is `eval/results/degraded-resume-a97d3f74.json`.

### Part D · five-line trace-only diagnosis

1. Trace `4044ec61c6a84c4685da7be954b8f043` asked about attendance, excused absence and consequences.
2. The prompt included June handbook clauses 1.21 and 1.22 from physical page 10.
3. Clause 1.22 gave two consequences, exam ineligibility and an F/A grade.
4. Generation cited clause 1.22 and returned only exam ineligibility.
5. The omission arose during generation. The missing fact was already in the context.

Source `docs/TRACE_ROOT_CAUSE_D5.md`. In a 60-minute cluster window, two academic-warning requests had top-1 similarity 0.808, zero cache hits and zero injection flags. One timed out during concurrent indexing, giving a 50% abstention rate. Stage p95 was 5.54 s for embedding, 0.42 s for retrieval, 0.31 ms for reranking, 242.50 s for generation and 243.04 s overall. A later request completed generation, and its stdout and PVC records matched. Sample size limits generalization. See `docs/evidence/asg3-trace-summary.json`.

**Part F · cluster evidence.** The stable Service and the candidate Service select disjoint API pods. The cluster experiment changes one assigned variable, top-k from 5 to 3, at a fixed 0.35 floor. Both use `nomic-embed-text` and `llama3.2:3b`. The evaluator snapshots the thresholds and runs the full suite twice per Service. A failed Job prevents promotion. The separate bad-release drill switched live to the retained candidate collection, k1/floor 0.99, which abstained. After `kubectl rollout undo`, trace `58a50ef8465046589110d1c0fb147e80` answered from stable `rahbar_policies`, revision `dcfb2a4cde934baaaf968a2085aefa62`, at k5/floor 0.35. The embedding version stayed fixed.

| Workload | CPU request / limit | Memory request / limit | Measurement basis |
|---|---:|---:|---|
| Stable and candidate API, each | 100m / 500m | 128 / 512 Mi | Stable reached 489m / 114 Mi, candidate 59m / 100 Mi during the measured request and rollout windows. The 500m cap accommodates the startup burst. |
| Chroma | 250m / 1000m | 256 / 1024 Mi | Sampled peaks reached 297m / 172 Mi. The 1000m limit accommodates bursts above the 250m request. |
| Redis | 100m / 500m | 64 / 256 Mi | Cache and lease activity reached 280m / 17 Mi. The 500m limit accommodates short CPU bursts. |
| Ingestion and schedule | 750m / 1500m | 512 / 1536 Mi | Stable ingestion reached 1499m and 346 Mi. The 750m request reserves half the measured CPU peak. The 1500m limit accommodates OCR bursts. |
| Evaluation | 100m / 500m | 128 / 384 Mi | Sampled peaks reached 485m / 44 Mi. The 500m limit allows CPU bursts above the request. |

Each independent Batch A Job embedded 875 chunks with zero orphans. The unchanged stable run embedded zero in 3.3 s. The CronJob controller also launched an unchanged repeat on the isolated lake. An attempted competing writer exited before indexing because the Redis lease was held. Sampled peak values come from `docs/evidence/k8s_resources_asg3.txt`. Ollama uses resources outside these Pod limits.

The ConfigMap experiment replayed the archived 42-question scores on one evaluator image. The Job passed at the original 20 s p95 ceiling, failed when the ConfigMap set it to zero, then passed after restoration. The deliberately degraded 48-question Job was scored and gated separately. The completed normal run resumed from its persistent PVC after the original Job exhausted its retries during an infrastructure outage. By the time of resumption, the stable first pass and six repeat answers were saved. The replacement began at q07 of the stable repeat on the same Vulkan model endpoint and completed the remaining work. The normal-candidate latency rejection preserved the stable Deployment.

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
| M. Huzaima · 24I-3014 | Kubernetes integration, persistent volumes, Job orchestration and recovery, release and rollback, resource measurements, CI/CD, and report and appendix preparation. |

Codex assisted with Kubernetes manifests, integration scripts, tests, evidence collection and report drafting.

The reported measurements and screenshots come from repository evidence and the team’s own runs.

## Appendix · uncropped terminal evidence

Each capture shows an actual terminal session. Archived reads and fresh cluster commands are labeled with their provenance. The normal comparison logs and rejection appear below. The accepted historical gate and the controlled undo exercise have their own captures.

### A1 · Batch B verification

The isolated cluster report gives all four checks and their reasons for each scanned input.

![Batch B verification](../appendix-screenshots/cluster/verification.png)

### A2 / F2a · Completed unchanged ingestion

The stable Job reports zero newly embedded chunks and zero orphans.

![Completed unchanged ingestion](../appendix-screenshots/cluster/unchanged.png)

### B1 · Historical three-level evaluation

The terminal reads Partner A’s 42-question report and shows the module, component, end-to-end, noise and seeded repeat metrics.

![Historical three-level evaluation](../appendix-screenshots/cluster/stored-evaluation.png)

### B2 / F2b · Completed 48-question degraded evaluator

The first Pod saved three answers. A replacement resumed at q04 and completed the evaluation of the degraded test profile.

![Completed 48-question degraded evaluator](../appendix-screenshots/cluster/resumable-evaluator.png)

### B3 / F2c · Completed normal scoring (1/3)

This full terminal view shows lines 1–76 of the Job log. Together the three captures preserve the resumed scoring output, both repeat summaries and the release decision.

![Normal evaluation Job log, part 1](../appendix-screenshots/cluster/normal-evaluation-log-1.png)

### B3 / F2c · Completed normal scoring (2/3)

This full terminal view shows lines 77–152 of the Job log. Together the three captures preserve the resumed scoring output, both repeat summaries and the release decision.

![Normal evaluation Job log, part 2](../appendix-screenshots/cluster/normal-evaluation-log-2.png)

### B3 / F2c · Completed normal scoring (3/3)

This full terminal view shows lines 153–224 of the Job log. Together the three captures preserve the resumed scoring output, both repeat summaries and the release decision.

![Normal evaluation Job log, part 3](../appendix-screenshots/cluster/normal-evaluation-log-3.png)

### C1 / C2 · Archived pass and rejection

Kubernetes gate Jobs used archived 42-question reports. The table includes the mounted rule outcomes, evaluator image IDs and exits.

![Archived pass and rejection](../appendix-screenshots/cluster/gates.png)

### C2b · Fresh 48-question degraded rejection

This gate compared the stable first pass with the isolated degraded report. It failed recall and faithfulness.

![Fresh 48-question degraded rejection](../appendix-screenshots/cluster/fresh-degraded-gate.png)

### C2c · Normal-candidate latency rejection

The normal scorer finished all four passes. The Job failed the latency rule, and the post-gate readiness output shows the original stable collection and index revision.

![Normal gate and preserved stable profile](../appendix-screenshots/cluster/normal-release-rejection.png)

### D1 · Full JSONL trace

The academic-warning request returned trace 7d5d7fff6ee3440cbdd44577aeee8337. The terminal prints its complete stored record.

![Full JSONL trace](../appendix-screenshots/cluster/trace.png)

### D2 · Exact prompt and context

The inspector reconstructs the complete recorded prompt and evidence for the D1 trace ID.

![Exact prompt and context](../appendix-screenshots/cluster/reconstruction.png)

### E1 / E2 · Coverage before and after

The cluster checker used the same 40 queries and embedding model. The first gate failed at 28/40 and passed at 40/40 after the additions.

![Coverage before and after](../appendix-screenshots/cluster/coverage.png)

### F1 · Namespace inventory

The original cluster terminal output shows Services, Deployments, Jobs, CronJobs, ConfigMaps and PVCs.

![Namespace inventory](../appendix-screenshots/cluster/inventory.png)

### F3 · ConfigMap threshold change

The terminal opens the original saved kubectl patch transcript. Its three archived-score decisions are pass, fail and pass, using one evaluator image. C1/C2 shows the image IDs and exits.

![ConfigMap threshold change](../appendix-screenshots/cluster/archived-threshold-transcript.png)

### F4 · Controlled rollout and undo

The deliberately bad release used k1 and floor 0.99. The terminal shows successful status for the bad rollout, the undo, and successful status after restoration.

![Controlled rollout and undo](../appendix-screenshots/cluster/undo.png)

### F5 · Fresh post-rollback trace check

The three genuine trace records show the original, bad, and restored profiles. The restored record uses the original collection, embedding version and index revision.

![Fresh post-rollback trace check](../appendix-screenshots/cluster/restored-trace.png)

### F6 · Persistent trace and metrics

The inspection Pod recovered a trace created before the serving Pods were replaced and summarized the shared trace volume.

![Persistent trace and metrics](../appendix-screenshots/cluster/persistence.png)

### F7 · Sampled container resources

The standard metrics-server query measured each currently running container. The timestamped series supports the report’s resource table.

![Sampled container resources](../appendix-screenshots/cluster/resources.png)
