# Assignment 03 submission checklist and PR description

## Submission checklist

- [x] Integrated both partners’ work into `dev`. The merge at `377179c` retains Partner A’s `3a71ce9` and Partner B’s `f3ca41e` as its parents. Its tree is identical to the verified feature tree.
- [x] Audited commands for Parts A–F in `README.md` and the fresh-cluster sequence in `k8s/README.md`.
- [x] Preserved the golden dataset, embedding pairs, saved evaluation reports, trace samples and Kubernetes manifests under `eval/`, `traces/` and `k8s/`.
- [x] Collected both reports, seeded repeats, Job metadata, original logs and gate output from `rahbar-eval-resume-cf08356c2e`. Each of the four passes scored 48 questions and three noise probes against the same input hashes.
- [x] Recorded the normal candidate’s gate rejection and the post-gate stable readiness check. The Job completed scoring and failed with exit 1 because candidate p95 was 48.66 s against a 20 s limit. Recall, faithfulness and abstention passed.
- [x] Captured the complete normal Job log across three full terminal views, the final rejection and the original serving profile. The appendix also includes the prior ConfigMap threshold flip, degraded rejection and bad-release undo.
- [x] Generated the final report PDF with an uncropped appendix and checked the eight-page limit on the main report.
- [ ] Open and review the PR from `dev` to `main`.
- [ ] Submit the repository URL and the single final PDF. Both partners should attend the demo with the Kubernetes pipeline running.

## Submission files

- Final report with appendix at `docs/RAHBAR_ASG3_FINAL.pdf`.
- Repository URL [RAHBAR-2.0](https://github.com/m-hamza-atif/RAHBAR-2.0).
- The complete normal evaluation is in `eval/results/5df892be-9cef-4988-934a-0be12c072f24/`. The exported Job log is `docs/evidence/rahbar-eval-resume-cf08356c2e.txt`.

## Outstanding live release evidence

A fresh successful normal-candidate Kubernetes promotion and its post-promotion trace remain unverified. The candidate was rejected by the unchanged gate. The historical 42-question local PASS, archived-score threshold flip, and separate genuine rollback exercise retain their original scope. The submitted report records the normal candidate’s actual decision.

## PR description

**Title** · Complete RAHBAR 2.0 Assignment 03 RAGOps integration

### Scope

- Verify and incrementally ingest public policy documents with quarantine, archive restoration and isolated drift experiments.
- Evaluate embedding, retrieval and answer quality with seeded repeats, coverage checks, traces and a ConfigMap-driven release gate.
- Run independently indexed stable and candidate Services with persistent state, trace and result volumes, lease-protected ingestion and a verified rollback.
- Include the final PDF, real terminal captures, report source, saved scores, measured resources and reproducible runbooks.

### Verification

- Linux passed 135 tests. Windows passed 127 tests and skipped eight Bash installer cases. Windows API coverage was 91.45%. These runs predate the evidence-only finalization, and the merge preserved the tested implementation tree.
- Manifest schema and Kubernetes server validation passed. Independent ingestion produced 875 chunks per collection, unchanged ingestion embedded zero, and the June handbook was restored in the isolated archive test.
- The resumed normal Kubernetes evaluation completed both stable and both candidate passes. The gate rejected the normal candidate on p95 latency (48.66 s versus 20 s). The stable Deployment retained its original collection and index revision.
- The separate fresh 48-question degraded comparison failed recall and faithfulness. The ConfigMap flip used the archived 42-question reports and one evaluator image. A controlled bad rollout was undone, with the restored profile verified by a fresh trace.
- The report explicitly records the outstanding successful normal candidate rollout and trace.

[Open or review the dev-to-main PR](https://github.com/m-hamza-atif/RAHBAR-2.0/compare/main...dev?expand=1)
