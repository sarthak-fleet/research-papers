# Engineering Lessons

Concrete lessons drawn from the code and git history of this project. ADR rationale lives in
[decisions.md](decisions.md).

---

## ClickHouse ingest pitfalls

### ORDER BY choice determines query speed, not just storage layout

`papers` is ordered by `(source, source_id)`. This means point-lookups by `paper_id` require a
full scan unless the query can also filter by `source`. Anti-join queries like
`paper_id NOT IN (SELECT paper_id FROM paper_tags ...)` scan the full `paper_tags` table on
every batch. For the current corpus size (488k papers, <1M tag rows) this is fast enough; at
10× scale it would need a secondary index or a bloom filter projection.

### `PARTITION BY toYear(submitted_date)` blocks cheap in-place mutations

The `papers` table is year-partitioned. ClickHouse `ALTER TABLE ... UPDATE` rewrites every
affected part within a partition; on a partitioned table this means any mutation touches a
large fraction of data. This is why `paper_scores_v2`, `paper_metadata_v2`, `citation_overlay_v2`,
and `abstract_overlay_v2` are all separate `ReplacingMergeTree` tables — appending a new row
and reading with `FINAL` is O(1), while `ALTER UPDATE` on the base table is O(partition size).

### `ReplacingMergeTree` requires `FINAL` on every read

All overlay tables use `ReplacingMergeTree`. Without `FINAL`, duplicate rows (old and new
versions of the same `paper_id`) may both be returned until ClickHouse runs a background merge.
Every query in `api.py`, `ch_exports.py`, and `pagerank_full.py` uses `FINAL` or an explicit
`... FINAL` qualifier. Forgetting it causes inflated counts and duplicate rows — the
`fix query drift` commit (2026-06-12) fixed exactly this.

### `LowCardinality(String)` on high-cardinality foreign keys is not free

`cited_openalex_id` in `references_paper` is marked `LowCardinality(String)` with the comment
"HUGE for storage" in `01_schema.sql`. This works well because OpenAlex IDs repeat across many
citing papers. However, applying `LowCardinality` to a truly unique key (like `paper_id`) would
waste dictionary memory without compression benefit.

### UDFs must be re-applied after container restores

`effective_year` and `effective_date` are defined in `02_functions.sql` as `CREATE OR REPLACE
FUNCTION`. They live in the ClickHouse system state, not in the data volume. `deploy.sh` must
re-apply them after a warm restore from a data dump — otherwise year-based filters and charts
silently return wrong results (the initial bug that led to commit `fix: persist effective_year/
date UDFs as init SQL`).

---

## Embedding pipeline

### Batch size must be clamped dynamically, not set once

The default encode batch size is 64 (down from 256). But even 64 can OOM on a 16 GB machine
with other processes running. `ram.clamp_batch_size` reads `vm_stat` before each batch and
reduces the batch if free RAM (free + inactive + speculative pages) drops below a 6 GB reserve.
Setting a static batch size in a config file is not sufficient for a host with variable memory
pressure.

### Anti-join `NOT IN (SELECT ...)` is resumable by design

`embed.py` fetches only papers whose `paper_id` is not already in `paper_embeddings FINAL`.
This means killed runs resume from where they left off without needing a checkpoint file. The
same pattern is used in `noun_tag_v2.py`, `mlx_tag_v3.py`, and `cluster_embeddings.py`. The
tradeoff: the anti-join subquery is re-evaluated on every chunk, which is a full scan of
`paper_embeddings`. At 478k rows this is fast; at 10M+ it would need an incremental cursor or
a materialised "already-done" set.

### Text truncation before encoding matters

`embed.py` truncates abstract to 1000 characters before passing to `model.encode`. MiniLM-L6-v2
has a 256-token context window; longer abstracts are silently truncated by the tokenizer anyway.
Explicit truncation in Python prevents wasteful tokenisation of text that will be dropped.

---

## MLX inference

### Cold-start is one-time per run, not per paper

`mlx_lm.load()` in `mlx_tag_v3.py` is called once before the paper loop. The model (~2 GB of
quantised weights) is loaded into unified memory and stays resident. If you interrupt and restart
with `--shards`, each shard pays the cold-start cost. Keep `--total-shards` high (3+) to run
one shard at a time and avoid competing with other RAM-hungry processes.

### Group prompting (4 papers per call) yields ~4× throughput

Packing 4 paper titles+abstracts into one chat turn with a JSON array response format achieves
roughly 4× the tagged-papers-per-second vs. single-paper calls with similar tag quality.
The tradeoff: if the LLM produces malformed JSON for one slot, all 4 papers in the group are
retried at the next run (the `None` sentinel in `_parse_group_response` handles partial failures
per slot, so only the failed slot is skipped, not the whole group).

### MLX HTTP server ignores strict JSON schema

When using the MLX server via HTTP (`llm_tag.py`), `response_format: json_schema` with
`strict: true` is silently ignored. The fallback is `json_object` mode. Direct `mlx_lm.generate`
(no HTTP layer) does not have this problem — the prompt engineering carries the format contract.

### RAM throttle is necessary during concurrent workloads

`mlx_tag_v3.py` checks `vm_stat` every 5 seconds and sleeps when free RAM drops below 3 GB.
Without this, simultaneous model inference + ClickHouse background merges + IDE + browser can
push the system into swap on a 16 GB host.

---

## PageRank on a sparse citation graph

### Dangling nodes require explicit teleport mass redistribution

Papers with no outgoing in-corpus edges (dangling nodes) absorb rank without redistributing it.
`pagerank_full.py` detects them with `out_deg == 0`, sets their effective out-degree to 1, and
redistributes their mass uniformly: `damping * (M @ pr + dangling_mass / n)`. Without this,
dangling nodes accumulate rank that never flows back and convergence is slower.

### OpenAlex ID join excludes bioRxiv/medRxiv from the PageRank graph

The edge join in `pagerank_full.py` matches `citing_paper_id → cited_openalex_id` and requires
both ends to have `openalex_id` set. bioRxiv and medRxiv papers often lack OpenAlex IDs, so they
are absent from the graph even though their arxiv counterparts may be present. PageRank scores
for bioRxiv papers will be 0 or absent from `paper_scores_v2`.

### Convergence on this graph: ~20–30 iterations

The corpus has ~1.05M edges over ~488k nodes (average degree ~2.1, very sparse). Power iteration
with `tol=1e-6` converges in 20–30 iterations in practice. The `max_iter=50` cap is a safety
limit that is not normally reached.

---

## spaCy tagging

### Disabling the parser is the single biggest throughput lever

The module docstring in `noun_tag_v2.py` states: "The dependency parser eats ~60-70% of spaCy's
CPU time." Running `tok2vec + tagger` only (via `disable=["parser", "ner", "lemmatizer"]`) gives
3–5× throughput on the same hardware. The POS-only noun-phrase pattern covers the same
academically-relevant phrases as parsed NPs for this corpus.

### Worker count must be RAM-aware, not CPU-aware

`pick_n_process` in `ram.py` estimates workers as `min(cap, budget_MB / worker_rss_MB)` where
`worker_rss_MB = 1500` (observed steady-state RSS for `en_core_web_sm` with parser disabled).
On a 16 GB machine with 6 GB reserved, this typically gives 2 workers — matching the `DEFAULT_MAX_PROCS`
in the M1 profile. Using `os.cpu_count()` workers would OOM.

---

## FastAPI lean mode

### Subprocess-based query encoding saves ~400 MB resident RAM

The API defaults to `LEAN_API=1`, which spawns a one-shot `encode_query.py` subprocess for
every semantic-search request instead of keeping a `SentenceTransformer` instance in the API
process. The subprocess loads the model, encodes the query, writes the JSON vector to stdout,
and exits. Tradeoff: ~0.5–1s additional latency per semantic-search call; acceptable for
interactive use.

---

## Data quality: OpenAlex metadata bugs

### OpenAlex `submitted_date` returns revision date for arxiv preprints

"Attention Is All You Need" (arxiv:1706.03762) shows `submitted_date` of 2025 in OpenAlex
because it was revised in 2025. The `effective_year` UDF corrects this by parsing the YYMM
prefix of the arxiv ID (`17` → 2017). This is a systemic issue across the corpus, not an
isolated case — it affects any arxiv paper that has been revised after its original submission.

### Cross-contaminated abstracts in OpenAlex

Some arxiv IDs have incorrect titles or abstracts in OpenAlex's index (different paper's content).
`abstract_overlay_v2` stores the authoritative arxiv-API abstracts for detected contaminated records.
Run `papers refresh-abstracts --reembed` after a large refresh to update semantic-search vectors
for corrected papers.
