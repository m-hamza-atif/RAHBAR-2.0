# Run Assignment 03 on a fresh single-node Kind cluster

Run from the repository root. Commands below use Bash, Python 3.12, Docker with Linux containers, Kind 0.27, kubectl with Kustomize, curl and PyYAML. Python helpers also run on Windows. On PowerShell set `$env:KUBECONFIG="$pwd\.artifacts\asg3-kubeconfig"` and invoke the same Python commands. The context is always `kind-rahbar-asg3`. Keep the model service on the private Docker network. Allow space for container layers, model weights and local volumes.

## Start the node and load images

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r api/requirements-dev.txt -r indexer/requirements-dev.txt -r corpus/requirements-dev.txt
bash scripts/install_ci_tools.sh kind kubeconform
export PATH="$PWD/.tools:$PATH"
export KUBECONFIG="$PWD/.artifacts/asg3-kubeconfig"
python scripts/cluster.py --name rahbar-asg3 --kubeconfig "$KUBECONFIG"
kubectl config current-context
docker build --provenance=false -t rahbar-api:asg3 api
docker build --provenance=false -f indexer/Dockerfile -t rahbar-indexer:asg3 .
docker build --provenance=false -f eval/Dockerfile -t rahbar-eval:asg3 .
kind load docker-image --name rahbar-asg3 rahbar-api:asg3 rahbar-indexer:asg3 rahbar-eval:asg3
python scripts/validate_manifests.py
```

The shared cluster helper enables Calico, metrics-server and a local ingress controller. Assignment 03 uses private ClusterIP Services and loopback port-forwarding. Before rebuilding an image for a subsequent experiment, finish the current comparison, use new image tags in the workload templates, and verify the running image IDs.

## Configure the model and storage

When a reachable Ollama service already has both pinned model digests, use its trusted private IPv4 address as `MODEL_IP`. The following starts a dedicated service on the Kind network with a named model volume. It publishes no host ports.

```bash
docker run -d --restart unless-stopped --name rahbar-asg3-model --network kind -v rahbar-asg3-models:/root/.ollama ollama/ollama:0.40.15
docker exec rahbar-asg3-model ollama pull nomic-embed-text
docker exec rahbar-asg3-model ollama pull llama3.2:3b
MODEL_IP=$(docker inspect --format '{{(index .NetworkSettings.Networks "kind").IPAddress}}' rahbar-asg3-model)
python scripts/ragops_cluster.py infra --model-ip "$MODEL_IP"
kubectl -n rahbar get pvc,deploy,statefulset
kubectl apply --dry-run=server -k k8s/overlays/asg3
kubectl apply --dry-run=server -f k8s/eval-job.yaml
```

The helper applies only the infrastructure first, allows port 11434 to the selected /32, and verifies the model digests in `eval/model-manifest.json` from the inspection workload. Use an isolated kubeconfig and keep the model IP stable during a run. All volumes use RWO on the one node. RWO allows multiple same-node mounts. The local filesystem and Partner A’s one-write `O_APPEND` trace emitter support concurrent API replicas. A cluster deletion destroys local-path data. Export evidence first.

## Seed and index (Part A, F1–F2)

The fetcher regenerates a manifest. Run it in ignored staging and compare against the committed one. Each lake must be seeded **once**, before either writer changes its own active inventory. The helper refuses to overwrite an existing lake.

```bash
mkdir -p .artifacts/public
cp corpus/fetch.py corpus/sources.yaml .artifacts/public/
python .artifacts/public/fetch.py
cp corpus/MANIFEST.md .artifacts/public/MANIFEST.md
python .artifacts/public/fetch.py --verify
python scripts/ragops_cluster.py seed stable --source .artifacts/public/raw
python scripts/ragops_cluster.py seed candidate --source .artifacts/public/raw
python scripts/ragops_cluster.py index stable
python scripts/ragops_cluster.py index stable
python scripts/ragops_cluster.py reports stable
python scripts/ragops_cluster.py deploy stable
kubectl -n rahbar rollout status deployment/rahbar-api
python scripts/ragops_cluster.py index candidate
python scripts/ragops_cluster.py reports candidate
python scripts/ragops_cluster.py deploy candidate
kubectl -n rahbar get all,pvc,configmap,cronjob,job
```

The data lake, archive, quarantine, verification reports and lake ID reside on each lane’s `state-*` claim under `/data`. Chroma and Redis retain their original claims. The writer carries the Redis lease even for manual and archive-restore Jobs. Keep the schedule suspended during comparisons. The steady-state `sync-cron` command below selects the active collection and enables weekly reindexing.

## Evaluate and decide (Parts B and C)

```bash
kubectl apply -f k8s/eval-job.yaml
kubectl -n rahbar get job rahbar-eval -w
# After Complete or Failed, stop the watch with Ctrl-C.
kubectl -n rahbar logs job/rahbar-eval
python scripts/ragops_cluster.py eval
```

On a fresh cluster, `python scripts/ragops_cluster.py promote --official-job` combines the literal standalone apply, result export and guarded promotion into one comparison. It requires the fixed-name Job to be absent. An evaluation-only first run accepts `eval --official-job`. The 24-hour Job limit accommodates four passes on CPU-only machines. Per-request timeouts and all quality thresholds still apply.

A repeat `apply` to a finished Job retains that execution. The Python command creates a uniquely named Job each time and records logs, reports and the exact threshold snapshot. Each attempt evaluates the stable Service first, then the candidate Service, with identical packaged data, cache bypass and seed 42. The code runs two passes per Service. The local 42-question reports cannot substitute for the current 48-question series.

For the deliberately degraded candidate, record the live Deployment revision before and after. The normal promotion path runs the gate again. A failed Job terminates it before any live template change. Watch actual failures for failed metric rules; a connection error does not demonstrate a quality rejection.

```bash
kubectl -n rahbar rollout history deployment/rahbar-api
kubectl -n rahbar set env deployment/rahbar-api-candidate RELEVANCE_FLOOR=0.99 TOP_K=1
kubectl -n rahbar rollout status deployment/rahbar-api-candidate
python scripts/ragops_cluster.py promote
kubectl -n rahbar rollout history deployment/rahbar-api
kubectl -n rahbar set env deployment/rahbar-api-candidate RELEVANCE_FLOOR=0.35 TOP_K=3
kubectl -n rahbar rollout status deployment/rahbar-api-candidate
python scripts/gate_threshold_demo.py
python scripts/ragops_cluster.py promote
kubectl rollout status deployment/rahbar-api -n rahbar
```

The threshold demonstration starts with an actual pass, patches `max_p95_latency_ms` to zero, checks for that failed rule and restores the original YAML in a finally block. A third full Job must pass, with the same evaluator image ID throughout. If the original candidate fails the real quality budget, record the rejection and diagnose the candidate. The deployment remains on its previous revision.

If Docker shuts down during evaluation, first check `kubectl -n rahbar get job,pod`, `kubectl -n rahbar logs job/JOB_NAME` and the Job’s results directory on the inspection volume. A terminated evaluator can leave only its threshold snapshot. Keep that Job and its logs. The current evaluator records the result directory before scoring and saves the completed first pass before starting the repeat. The cluster run retries HTTP 503 and connection failures up to three times, with 5, 15 and 30 s delays. It checks the same configuration and index revision before sending each request. Any wait is included in latency. Use `python scripts/ragops_cluster.py collect-job JOB_NAME` to recover the logs and completed files after a controller interruption. After both Deployments are Ready and the inspector verifies both model digests, run `python scripts/ragops_cluster.py promote` for a new, independently gated comparison.

## Rollback, traces and measurements (C3, D, F3–F5)

```bash
python scripts/ragops_cluster.py bad-release-demo
kubectl -n rahbar rollout history deployment/rahbar-api
python scripts/ragops_cluster.py trace
kubectl -n rahbar logs -l app=api,lane=stable --tail=5 --prefix=false
kubectl -n rahbar exec deploy/ragops-inspect -- python scripts/summarize_traces.py --minutes 60
kubectl -n rahbar port-forward svc/rahbar-api 18001:8000
# In a second terminal
curl --fail http://127.0.0.1:18001/metrics
```

The isolated bad-release exercise saves a working trace, switches collection and retrieval settings, then runs `kubectl rollout undo deployment/rahbar-api -n rahbar` through the helper and waits. It compares a new trace with the previous collection, embedding version, revision, top-k and floor. Both collections use the same embedding version. For manual undo of a promoted release, suspend the schedule, execute the following, then synchronize the writer to the restored collection.

```bash
kubectl -n rahbar patch cronjob ragops-reindex --type=merge -p '{"spec":{"suspend":true}}'
kubectl rollout undo deployment/rahbar-api -n rahbar
kubectl rollout status deployment/rahbar-api -n rahbar
python scripts/ragops_cluster.py trace
python scripts/ragops_cluster.py sync-cron
```

To check persistence, save the ID returned by the trace command as `TRACE_ID`. Restart only the assignment’s live API and compare the exact persisted record. Its timestamp and revision should still match.

```bash
kubectl -n rahbar rollout restart deploy/rahbar-api
kubectl -n rahbar rollout status deploy/rahbar-api
kubectl -n rahbar exec deploy/ragops-inspect -- python scripts/inspect_trace.py --trace-id "$TRACE_ID" --record
kubectl -n rahbar exec deploy/ragops-inspect -- python scripts/inspect_trace.py --trace-id "$TRACE_ID"
```

Run the appropriate sampler in another terminal **while** the named workload is executing. Check pod identity and timestamps, retain all observations and calculate per-container maxima by phase. The readings are sampled peaks. Compare resident memory with limits and CPU demand with requests. An absent short-lived Job sample means that phase needs repeating with metrics-server ready.

```bash
python scripts/measure_k8s_resources.py idle
python scripts/measure_k8s_resources.py ingestion
python scripts/measure_k8s_resources.py queries
python scripts/measure_k8s_resources.py evaluation
python scripts/measure_k8s_resources.py candidate
python scripts/measure_k8s_resources.py concurrent
python scripts/measure_k8s_resources.py summary
```

If metrics-server is unavailable, use the selected pod’s cgroup v2 counters with `kubectl -n rahbar exec POD -- cat /sys/fs/cgroup/memory.current /sys/fs/cgroup/cpu.stat`. Use the difference in CPU usage over a timed interval, recording pod UID and both reads. Model inference runs outside these Kubernetes pod budgets.

## Coverage, drift, archive restoration and evidence (Parts A, D, E)

From the model container’s private network, the inspection Deployment can run the same coverage checker as the host. Load the original golden snapshot into its writable temporary directory. The first historical comparison can legitimately return 1 below the 85% target. Inspect its output before continuing.

```bash
kubectl -n rahbar cp eval/results/coverage-before-golden.jsonl "$(kubectl -n rahbar get pod -l role=inspection -o jsonpath='{.items[0].metadata.name}'):/tmp/before.jsonl"
kubectl -n rahbar exec deploy/ragops-inspect -- python eval/check_coverage.py --live eval/live_queries.jsonl --golden /tmp/before.jsonl --similarity-threshold 0.78
kubectl -n rahbar exec deploy/ragops-inspect -- python eval/check_coverage.py --live eval/live_queries.jsonl --golden eval/golden.jsonl --similarity-threshold 0.78
python -m json.tool eval/results/drift_batch_b_verification_20261124-180937.json
python -m pytest -q indexer/tests/test_incremental.py
```

To verify the archive cycle independently of drift scoring, run `python scripts/ragops_drift.py --archive-only --source corpus/raw`. The helper creates a third lake and collection, ingests both batches, restores June, and checks both reports for the handbook's disposition. Supply the same original manifest-listed seed path used for stable and candidate.

Run the isolated drift experiment with the companion procedure in the root README. Never add the fictional November edition to the live collection. An archive-restore Job uses the same container command with `--rollback-doc academic-rules --to-version 2026-06` in place of `--incremental`. June must first have become archived in that same lake and collection.

For the fixed-name evaluation Job, copy the logged `RESULT_DIR` using its actual basename. The Job helper exports named-run results automatically. Select only assignment demonstration traces for Git.

```bash
kubectl -n rahbar logs job/rahbar-eval
POD=$(kubectl -n rahbar get pod -l role=inspection -o jsonpath='{.items[0].metadata.name}')
RUN=$(kubectl -n rahbar logs job/rahbar-eval | sed -n 's,^RESULT_DIR=/data/eval-results/,,p')
test -n "$RUN" && kubectl -n rahbar cp "$POD:/data/eval-results/$RUN" "eval/results/$RUN"
kubectl -n rahbar get all,pvc,configmap,cronjob,job
```

After export and the coordinated demonstration, optional cleanup is limited to `kind delete cluster --name rahbar-asg3` and `docker rm -f rahbar-asg3-model`. The named model volume can be reused. Cluster deletion removes both indexes and local-path evidence.
