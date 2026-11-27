# Batch B drift comparison

Ran the same 42-question golden snapshot, three typo variants and embedding pairs before and after the Batch B ingest. The collection, API settings, models, seed and cache bypass stayed the same. The input hashes matched and the index revision changed.

| Measure | Batch A | After Batch B |
| --- | ---: | ---: |
| Recall@3 and recall@5 | 1.0000 | 0.2973 |
| MRR | 0.9685 | 0.2793 |
| nDCG@5 | 0.9743 | 0.2838 |
| Reference faithfulness | 0.7027 | 0.2162 |
| Citation validity | 1.0000 | 1.0000 |
| Expected abstention correctness | 1.0000 | 1.0000 |
| p50 latency | 3.58 s | 5.24 s |
| p95 latency | 7.42 s | 22.70 s |

The writer accepted six new files, quarantined five and embedded six chunks without leaving orphans. It archived the June academic handbook when the synthetic November edition became current. That shorter edition covers attendance and leaves out many rules from the June handbook. Default retrieval excludes archived versions, so many questions lost their gold page. The frozen labels deliberately test whether old behavior survives the data update.

- **Current attendance, q03.** The first hit changed from the June handbook to `06-academic-rules.md`. The answer shifted from 100% to the fixture's 80% threshold and also introduced an unsupported lab-hours detail. A citation matching a retrieved reference does not establish that every answer claim follows from it.
- **Historical comparison, q19.** The June handbook still ranked first for the query containing a year. The explicit November probe still ranked June first and abstained. The retriever filters by year, so month-level requests can still surface multiple editions in the same year.
- **Transcript probe.** Batch A abstained. After the update, the API answered from the records-office fixture. Trace `c24461d21d754aea84e9375de9ddbe23` recorded `injection_text_removed` on the fixture and reconstructed the cleaned text sent to the generator.

The release gate rejected the Batch B snapshot on recall, reference faithfulness and p95 latency. This was one local timing run with substantial outliers. Batch B was used as an isolated experiment, and its fictional policy was never promoted.

Evidence is saved under `eval/results/` in the annotated baseline, post-Batch-B report, verification report and two probe files.
