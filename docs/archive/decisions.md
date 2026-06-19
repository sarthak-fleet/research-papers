# Architecture Decision Records

Decisions made during the researchPapers platform build. Dates derived from git history.

---

## ADR-001 — ClickHouse as the runtime database

**Date:** 2026-05-30

**Context:** The corpus is 488k papers, 1.05M citation edges, 478k 384-dim embedding vectors,
and several append-only overlay tables. The workload is analytical: GROUP BY source, ORDER BY
pagerank/citation_count over full-corpus scans, nearest-neighbour cosine over `paper_embeddings`,
and time-series aggregations on `citation_history`. Postgres was the original ingest store and
remains available for the few legacy CLI paths.

**Decision:** ClickHouse is the sole runtime database for the API, frontend, and all pipeline reads.
Postgres is demoted to an optional ingest staging store.

**Rationale:**
- MergeTree columnar storage compresses repeated values (source, tagger, cluster_id) far better
  than Postgres row storage for a mostly-read workload at this scale.
- `LowCardinality(String)` on `cited_openalex_id` (see schema comment: "HUGE for storage") and
  `source` shrinks the 1M-row references table significantly.
- `ReplacingMergeTree` provides idempotent upsert semantics for overlay tables without needing
  `ON CONFLICT` logic.
- ClickHouse's built-in `cosineDistance` function over `Array(Float32)` is used for semantic
  search over all 478k embeddings without a separate vector DB.

**Alternatives considered:**
- Postgres with pgvector for embeddings, BRIN/GIN indexes for analytics.
- SQLite for simplicity (single binary).

**Trade-offs:**
- ClickHouse `ALTER TABLE ... UPDATE` is asynchronous and partition-bound; that's why PageRank
  scores live in a separate `paper_scores_v2` overlay (ReplacingMergeTree on `paper_id`) rather
  than in-place on the `papers` table (partitioned by year, makes mutations expensive).
- `FINAL` modifier required on all reads from ReplacingMergeTree tables to get deduplicated rows;
  the team uses it consistently in all queries.
- Postgres migrations (001–012) are preserved for cold restore / legacy CLI path.

---

## ADR-002 — all-MiniLM-L6-v2 for paper embeddings (384-dim)

**Date:** 2026-05-30

**Context:** Need to embed ~478k title+abstract pairs for semantic search and clustering.
Running on an M1 Pro 16 GB machine. Embedding must fit in a ClickHouse `Array(Float32)`
column and support cosine distance queries without a separate vector index.

**Decision:** `sentence-transformers/all-MiniLM-L6-v2`, 384-dim L2-normalised vectors.

**Rationale:**
- 384 dims is small enough to store inline in ClickHouse (`Array(Float32)` per row ≈ 1.5 KB),
  avoiding an external vector DB.
- Model is small enough to run on CPU with manageable RAM; batch size clamped to 64 on
  16 GB hosts (down from a default of 256) via `ram.clamp_batch_size`.
- Already used for KeyBERT tagging (same model, reused), so no extra download cost.
- Normalised vectors make `cosineDistance` equivalent to dot-product — ClickHouse can compute
  this without a specialised ANN index.

**Alternatives considered:**
- `all-mpnet-base-v2` (768-dim): better quality but 2× storage and slower on CPU.
- OpenAI `text-embedding-ada-002`: high quality, but recurring API cost and data-privacy risk
  for a self-hosted corpus.

**Trade-offs:**
- No ANN index (HNSW, IVF) in ClickHouse — cosine search is a full scan over 478k vectors.
  Acceptable at this scale; would need an index or a separate store at 10M+ papers.
- 384-dim captures topic-level similarity well but may miss fine-grained methodological nuance.

---

## ADR-003 — MLX (Qwen2.5-3B-4bit) for premium tagging

**Date:** 2026-05-30

**Context:** Tags from spaCy's POS-only noun-chunk extractor are syntactically valid but
semantically coarse ("language models", "deep learning"). A subset of high-citation papers
warrants richer tags (specific method names, dataset names, TLDRs). The machine is an M1 Pro —
Apple Silicon with a unified memory architecture.

**Decision:** `mlx-community/Qwen2.5-3B-Instruct-4bit` via the `mlx-lm` Python package,
running entirely on-device using the MLX framework. Applied to a "premium" subset defined by
citation-count thresholds (≥100 citations, or recent papers with ≥20–50 citations).

**Rationale:**
- MLX runs quantised models directly on Apple Silicon's Neural Engine / GPU with unified memory.
  No PCIe bandwidth bottleneck, no CUDA required.
- 4-bit quantisation of a 3B-param model fits in ~2 GB of GPU-accessible unified memory,
  leaving headroom for the OS and the ClickHouse process.
- "Grouped prompt" batching (4 papers per LLM call): same model load, same forward-pass cost,
  ~4× effective throughput vs single-paper prompts.
- Writes directly to ClickHouse `paper_tags` (tagger `mlx_qwen3b_v3`); killed runs lose at most
  one batch (50 groups ≈ 200 papers) via flush-every-50-groups pattern.

**Alternatives considered:**
- OpenAI API: cost, latency, privacy, no offline use.
- Ollama + server-mode MLX (`llm_tag.py`): HTTP round-trip overhead, MLX server ignores
  strict JSON schema (documented in `llm_tag.py` comment: "MLX server does not honor
  strict json_schema; use json_object mode").
- Qwen2.5-1.5B-4bit: 30% faster but 3× skip rate (documented in `mlx_tag_v3.py`
  comment: "Empirically the 1.5B handles short academic abstracts fine, just with slightly
  more uniform/less detailed tags").

**Trade-offs:**
- Cold-start: `load()` call takes several seconds the first time; model is kept resident for
  the duration of a sharded run.
- RAM throttle: MLX holds the model in unified memory; `_ram_throttle()` pauses the loop when
  free RAM drops below 3 GB so other processes (e.g. IDE, browser) stay responsive.
- Sharding: the CLI supports `--shards N` to partition by `cityHash64(paper_id) % N`, allowing
  parallel runs on the same or different machines without coordination.

---

## ADR-004 — spaCy v2 with parser disabled (POS-only noun-chunk tagger)

**Date:** 2026-05-30

**Context:** Need to tag all 478k papers with noun-phrase tags at low cost. Full spaCy NLP
pipeline (tokenizer + tok2vec + tagger + parser + NER + lemmatizer) is slow and the dependency
parse is not needed for noun-phrase extraction.

**Decision:** Load `en_core_web_sm` with `disable=["parser", "ner", "lemmatizer"]`.
Extract noun-phrase candidates via a hand-written POS pattern `(ADJ|NOUN|PROPN)+` ending with
NOUN or PROPN. Single PROPNs kept only for acronyms (all-caps 2–8 chars) or CamelCase/digit
names (ImageNet, GPT4, Llama2).

**Rationale:**
- The parser accounts for 60–70% of spaCy CPU time (documented in `noun_tag_v2.py` module
  docstring). Disabling it gives 3–5× throughput on the same hardware.
- The POS pattern covers "deep convolutional neural networks", "Adam optimizer", "stochastic
  gradient descent" without needing parsed dependency arcs.
- `scispacy` (`scispacy>=0.6.2` in `pyproject.toml`) is installed for biomedical entity
  recognition on bioRxiv/medRxiv papers, but the primary tagger for the full corpus is
  `en_core_web_sm` (lightweight, fast).

**Alternatives considered:**
- Full spaCy pipeline with dep-parse: too slow for 478k papers on a single host.
- KeyBERT: better semantic quality but requires loading the MiniLM model in addition to spaCy,
  and wrote to Postgres only (not ported to the CH pipeline). See `keybert_tag.py` — still reads
  from and writes to Postgres, not ClickHouse; effectively deprecated.
- OpenAI API extraction: cost-prohibitive at 478k scale.

**Trade-offs:**
- POS-only chunking produces some false positives ("the proposed", "our model") that are
  filtered via a blacklist in `noun_tag.py`. Precision is lower than parsed noun phrases but
  acceptable for tag-cloud/drill-down use cases.
- scispaCy model size on disk is significant (~500 MB for the large model); the project uses
  the `en_core_web_sm` model for the main corpus to save disk.

---

## ADR-005 — KeyBERT (not used in production pipeline)

**Date:** TBD: capture rationale — KeyBERT appears in `pyproject.toml` and `keybert_tag.py`
but the CLI for KeyBERT writes to Postgres only. It was likely evaluated early as an alternative
to spaCy noun-chunk tags.

**Decision:** Not used in the current ClickHouse pipeline. `keybert_tag.py` remains as a
reference implementation targeting Postgres.

**Trade-offs:**
- KeyBERT uses the same MiniLM-L6-v2 model as the embedder, so there is no extra download.
  The MMR diversity parameter avoids near-duplicate tags. However, it requires loading the
  sentence-transformer model in addition to the Postgres connection, and was not ported to
  the CH paper_tags write path.

---

## ADR-006 — scipy.sparse power iteration for full-corpus PageRank

**Date:** 2026-05-31

**Context:** The citation graph has ~1.05M edges over ~488k nodes. The original implementation
in `graph.py` used `networkx.pagerank()` over a Postgres-backed in-memory DiGraph loaded all at
once. At 1M+ edges this was slow and memory-intensive.

**Decision:** Custom power-iteration in `pagerank_full.py` using `scipy.sparse.csr_matrix`.
Edges are streamed from ClickHouse in 250k-row chunks to avoid materialising the full edge list
before matrix construction.

**Rationale:**
- `scipy.sparse` matrix-vector multiply is 10–50× faster than NetworkX's pure-Python iteration
  for large graphs.
- Streaming edge reads stay within the 16 GB memory budget; the full COO triplet list for 1M
  edges fits in ~24 MB as `float32` arrays before conversion to CSR.
- Dangling-node mass redistribution is handled explicitly (teleport term for zero-outdegree nodes)
  to avoid score leakage.
- Results written to `paper_scores_v2` (ReplacingMergeTree) in 10k-row batches, not in-place
  on `papers`, because `ALTER UPDATE` on the year-partitioned table is expensive.

**Alternatives considered:**
- NetworkX `nx.pagerank()` (kept in `graph.py` for the legacy Postgres subgraph): fine for
  smaller in-corpus subgraphs, impractical at full-corpus scale.
- DB-side graph computation (ClickHouse `arrayJoin` + iterative SQL): ClickHouse has no native
  graph engine; iterative SQL PageRank is cumbersome at this edge count.
- GraphX / Apache Spark: overkill for a single-machine workload.

**Trade-offs:**
- Power iteration with `max_iter=50, tol=1e-6` converges in practice within 20–30 iterations
  on a sparse academic citation graph.
- The implementation resolves edges via `openalex_id` join — papers without `openalex_id` are
  excluded from the graph (no edges in or out). This is the majority-case for bioRxiv/medRxiv.

---

## ADR-007 — FastAPI over alternatives

**Date:** 2026-05-30

**Context:** Need a lightweight HTTP API over ClickHouse. Endpoints are read-only; no mutations.
The semantic-search endpoint needs to invoke a Python ML model (SentenceTransformer) synchronously.

**Decision:** FastAPI with `uvicorn`.

**Rationale:**
- FastAPI's automatic OpenAPI docs reduce endpoint documentation burden.
- Async-friendly: ClickHouse queries via `clickhouse-connect` can be offloaded without blocking
  the event loop.
- `--lean` mode: the API defaults to spawning a one-shot subprocess for query encoding
  (`encode_query.py`) rather than keeping the SentenceTransformer loaded. This saves ~400 MB RSS
  on the API process at the cost of ~0.5s latency per semantic-search request.

**Alternatives considered:**
- Flask: synchronous, heavier setup for type-annotated request/response models.
- Django: too heavy for a read-only analytics API.

**Trade-offs:**
- CORS is wide-open (`allow_origins=["*"]`) — acceptable for a private self-hosted deployment,
  not for a public API without authentication.

---

## ADR-008 — Astro 5 + React islands + static JSON exports

**Date:** 2026-05-30

**Context:** The dashboard renders several data-heavy tables (papers, tags, authors, communities).
Most content is static after a pipeline run; only search, semantic search, and similar-papers
need live API calls.

**Decision:** Astro 5 with `output: "static"`. Data-heavy tables are React islands hydrated
from pre-built `web/public/data/*.json` files (generated by `papers export-ch`). Search and
semantic-search components call the FastAPI live. CSS pipeline uses Lightning CSS via the Vite
`@tailwindcss/vite` plugin; stylesheets are always inlined (`inlineStylesheets: "always"`).

**Rationale:**
- Static JSON export decouples the frontend build from the live API: the dashboard works even
  if the FastAPI server is down, as long as the exports are fresh.
- React islands (partial hydration) keep JS bundle size small — only interactive components
  hydrate in the browser.
- Lightning CSS replaced the previous CSS pipeline for faster builds
  (commit `2fa23b0`: "web: switch CSS pipeline to Lightning CSS + inline stylesheets").

**Alternatives considered:**
- Pure React SPA: entire bundle re-renders on every route change; no static export path.
- Next.js: heavier framework, SSR adds complexity for a self-hosted deployment where the
  ClickHouse data is local.

**Trade-offs:**
- Static JSON exports must be regenerated (`papers export-ch` + `npm run build`) after each
  ingestion or re-tag run.
- Vercel/CF CDN deployment is deferred; current shape is same-host deploy.
