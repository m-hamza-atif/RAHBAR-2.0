# Partner B viva · a 25-minute rehearsal

Use a running assignment cluster and the dedicated kubeconfig. One partner drives while the other explains which observation would disprove each claim. The [Kubernetes runbook](k8s/README.md) contains the fresh-cluster procedure and full commands.

## Minutes 0–3 · state the problem and locate the services

Assignment 02 answered university policy questions with retrieval, generation, citations, a semantic cache and a Kubernetes deployment. Assignment 03 adds the data lifecycle. A university can replace a handbook between two application releases. The same question and image can then produce a different answer. We need to identify which document changed, decide whether old answers still work and reproduce which version a user saw.

Hamza owns data management, evaluation, tracing and coverage. Huzaima owns the Kubernetes integration, C3, F and report preparation. Both partners should explain how a local drift result differs from a live release decision.

```bash
kubectl config current-context
kubectl get all,pvc,configmap,cronjob,job -n rahbar
kubectl -n rahbar get endpoints rahbar-api rahbar-api-candidate
```

The live Service selects pods with `app=api,lane=stable`. After promotion those same labels can identify pods reading the candidate collection. Callers keep their existing Service address. Locate the stable and candidate Deployments, stateful Chroma instance, Redis and PVCs in the output.

## Minutes 3–7 · follow one document

1. The fetcher records filenames, metadata and hashes. Seeding checks every committed manifest entry. A temporary non-root pod writes a staging directory and renames it to `/data/lake` only when this lane has no existing lake.
2. The writer Job runs `python /app/entrypoint.py --incremental`, takes Redis key `rahbar:indexer:writer` and renews its 120-second lease while the child pipeline is running. Lease loss stops the child. A manually launched Job uses the same key.
3. Before chunking, quality and completeness checks can quarantine a broken document. Hash and semantic duplicate checks avoid indexing redundant material. An unchanged file contributes zero new chunk embeddings.
4. A new handbook can archive the previous edition while retaining its version. The lake ID prevents an incorrect mount from being treated as the current inventory. Otherwise a missing directory could look like a mass deletion.
5. The writer reconciles document-scoped chunks and publishes a ready index revision. Readers verify their embedding settings and use revision-aware cache identity.

Run `python scripts/ragops_cluster.py index stable` twice. Identify scanned, unchanged, newly embedded and orphan counts. The unchanged run must actually report zero new chunks. CronJob concurrency controls overlap within that schedule. The global lease covers manual and candidate writers too.

**Why seed the second lake from the original download?** Initial ingestion can already have moved an older edition into the stable archive. Copying that active lake would start the experiment with different data.

## Minutes 7–10 · follow one query

Run `python scripts/ragops_cluster.py trace`. The live Service routes a cache-bypassed question to a ready API pod. Retrieval embeds the question, reads Chroma, filters document versions and ranks passages. The generator receives the assembled messages. The API validates citations and can abstain. Redis carries cache entries and the writer lease. Chroma retains vectors, source metadata and the revision.

The response has a trace ID. Inspect scores, document versions and exact messages before judging the answer. In the documented attendance failure, the context contained both consequences but the response omitted the F/A grade. This locates the error in generation.

```bash
kubectl -n rahbar exec deploy/ragops-inspect -- python scripts/inspect_trace.py --trace-id "$TRACE_ID" --record
kubectl -n rahbar exec deploy/ragops-inspect -- python scripts/inspect_trace.py --trace-id "$TRACE_ID"
```

The API emits one JSON line to stdout and issues one `O_APPEND` write per record on the persistent file. The thread lock covers one process. Local POSIX append semantics cover different processes. All replicas use the same UID. Only the API writes to the trace volume, and the inspection pod mounts it read-only. Explain why RWO permits multiple pods on this one node and why a multi-node deployment needs a different arrangement.

## Minutes 10–14 · read a gate decision

```bash
kubectl -n rahbar get configmap rahbar-gate-config -o yaml
kubectl apply -f k8s/eval-job.yaml
kubectl -n rahbar get jobs
kubectl -n rahbar logs job/rahbar-eval
```

Module tests ask whether paraphrases embed more similarly than unrelated pairs and how reproducible the result is. Component tests measure the rank of gold pages. End-to-end tests examine reference facts, valid citations, abstention and latency. A model can produce deterministic vectors and still retrieve nothing if the relevance floor is too high.

Both Services are scored with the same packaged golden and embedding-pair files, cache bypass and seed 42. Current data has 48 questions. Partner A’s saved comparison used 42. The gate rejects incompatible hashes or model profiles. Show each rule and its observed value. Thresholds come from a mounted ConfigMap. A new Job picks up a changed threshold without building an image. A failing rule returns exit 1 and fails the Job immediately. An interruption during scoring can trigger a replacement pod that resumes from the request checkpoint after verifying the same dataset and index revision. A connection error is a failed Job but gives no evidence of a quality rejection.

The local candidate used a higher floor. The cluster experiment changes top-k from 5 to 3 at a fixed floor. The old pass cannot decide this release. The 20-second latency budget still applies when CPU inference is slow.

## Minutes 14–18 · promote and recover

```bash
python scripts/ragops_cluster.py promote
kubectl rollout status deployment/rahbar-api -n rahbar
kubectl -n rahbar rollout history deployment/rahbar-api
```

The helper runs a fresh gate, verifies evaluated index revisions, templates and threshold revision, and applies the candidate pod spec only after a pass. The live Service selector stays in place. The prior ReplicaSet retains the old image and explicit environment values. If both revisions inherited collection and embedding settings solely from a mutable ConfigMap, rollback could bring back the previous image with the wrong settings.

One surge pod allows a new replica to become ready while previous replicas continue serving. Zero unavailable replicas requires node capacity and correct readiness probes. Readiness checks the data dependencies and a usable index. Liveness checks the process. After rollout inspect a fresh trace to determine which collection served the request.

The separately invoked bad-release demonstration starts with a recorded working profile, changes collection and retrieval settings, makes a query and invokes rollout undo. Compare the fresh rollback trace with the earlier collection, embedding version, revision, top-k and floor. Both collections share an embedding version. Rollback of code cannot recover destroyed vectors. Keep both collections and their owning lakes.

## Minutes 18–21 · explain capacity and observability

```bash
kubectl -n rahbar top pods --containers
python scripts/measure_k8s_resources.py concurrent
kubectl -n rahbar exec deploy/ragops-inspect -- python scripts/summarize_traces.py --minutes 60
```

A CPU request affects scheduling and CPU sharing. A limit can throttle a busy container. Exceeding the memory limit can terminate it. A sampled peak depends on the sample interval, duration and workload. Find a sample containing a running indexer or evaluator before claiming to have measured it. Model inference happens outside these pod budgets. Missing active phases leave the sizing provisional.

Prometheus counters reset on a pod restart. Persistent JSONL supports a window across replicas and revisions. Port-forward the live Service and request `/metrics`. Locate the top-1 histogram, outcome counters, cache hits, per-stage latency and flagged injection counters. Explain which values belong to one pod and which can be reconstructed across the cluster.

## Minutes 21–25 · examiner follow-ups

| Prompt | Answer to demonstrate |
|---|---|
| Why did citation validity remain perfect during drift? | A citation matched a retrieved passage, yet the response could still omit or invent a fact. Recall@5 fell from 1.00 to 0.297 after the fictional edition replaced labeled material. |
| What did coverage add? | Twelve simulated queries were outside the earlier test topics. Six new golden questions raised coverage from 28/40 to 40/40. This measures test representation, not source completeness. |
| Can repeated Jobs overwrite results? | Each run writes a UTC-and-UUID directory. The fixed-name Job runs once per object. The helper creates a new Job for every comparison. |
| What proves persistence? | Read an earlier trace by ID from a replacement pod, inspect unchanged ingestion against its prior lake ID and check the Chroma revision. |
| What if only latency misses its gate? | A single failed rule rejects the release. Keep the live Deployment, preserve the timing and investigate CPU/model pressure. |
| Why does the indexer own vector writes? | Only its application path mutates Chroma. Kubernetes network policy restricts client connections; it cannot authorize individual Chroma HTTP methods. This deployment trusts its application pods. |
| How do we handle unseen documents? | Add them to a separate experiment lake while preserving the rest of its inventory. Run the same lease-wrapped Job and inspect quarantine, archive, counts and revision. |
| What is incomplete? | Read the phase report. Identify the specific gate, measurement, screenshot or coordinated merge still outstanding. |

Finish by opening a complete trace, a failed gate and the before/after revision. Together they tie an individual answer to its data and release decision.

## Numbers to explain from the feature branch

- The two separately seeded indexes each ingested eight files and retained 875 chunks. The stable rerun embedded zero in 3.3 seconds. Point to each writer’s JSON report before explaining incremental ingestion.
- The full Linux suite passed 135 tests. The corresponding Windows run passed 127 and skipped eight Linux/bash installer cases.
- On the CPU-only model server, one academic-warning query timed out during concurrent indexing. The next stable query completed and its stdout record matched the trace volume. The query-stage summary covers two requests; use the separate evaluation report for release latency.
- Increasing the writer request from 250m to 750m reserves CPU for OCR without raising its 1500m cap. The observed stable peak was 1499m and 346 MiB.
- The in-cluster coverage check rose from 28/40 to 40/40 at the same 0.78 similarity threshold. The same evaluator image accepted, rejected and accepted the archived 42-question comparison as the latency threshold changed and was restored. Identify the fresh comparison separately.
