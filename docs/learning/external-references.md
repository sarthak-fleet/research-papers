# External References

One-line "what / why it matters here / link" for each technology in the stack.
Concepts are not re-explained here — follow the link.

---

## Embeddings & Semantic Search

**sentence-transformers / all-MiniLM-L6-v2**
Bi-encoder that maps text to dense 384-dim vectors for semantic similarity.
This project uses it for embedding 478k paper abstracts and for query encoding in semantic search.
[https://www.sbert.net/](https://www.sbert.net/)

**Cosine distance in ClickHouse**
ClickHouse's built-in `cosineDistance(a, b)` on `Array(Float32)` columns — used here instead of
a separate vector DB (Faiss, Weaviate, Qdrant) because the corpus fits in a full-scan budget.
[https://clickhouse.com/docs/sql-reference/functions/distance-functions](https://clickhouse.com/docs/sql-reference/functions/distance-functions)

---

## Local LLM Inference

**MLX**
Apple's array framework for machine learning on Apple Silicon. Enables running quantised LLMs
entirely in unified memory without CUDA. Used here for Qwen2.5-3B-Instruct-4bit tagging.
[https://ml-explore.github.io/mlx/](https://ml-explore.github.io/mlx/)

**mlx-lm**
Python library wrapping MLX for chat-model inference. Provides `load()` and `generate()` — the
two calls used in `mlx_tag_v3.py`.
[https://github.com/ml-explore/mlx-lm](https://github.com/ml-explore/mlx-lm)

**Qwen2.5-3B-Instruct-4bit**
The specific model used for premium tagging. 4-bit quantisation of Alibaba's Qwen2.5-3B
instruction-tuned model; fits in ~2 GB unified memory.
[https://huggingface.co/mlx-community/Qwen2.5-3B-Instruct-4bit](https://huggingface.co/mlx-community/Qwen2.5-3B-Instruct-4bit)

---

## NLP Stack

**spaCy**
Industrial NLP library. Used here with parser and NER disabled — only the `tok2vec + tagger`
components — for POS-based noun-phrase extraction across 478k abstracts.
[https://spacy.io/](https://spacy.io/)

**scispaCy**
spaCy models fine-tuned on biomedical text (PubMed, MIMIC). Installed (`scispacy>=0.6.2`) for
bioRxiv/medRxiv NER; the primary corpus tagger uses `en_core_web_sm` for speed.
[https://allenai.github.io/scispacy/](https://allenai.github.io/scispacy/)

**KeyBERT**
Keyword extraction using document/phrase cosine similarity with MMR diversity. Present in
`keybert_tag.py` as an evaluated approach; not in the current CH production pipeline.
[https://maartengr.github.io/KeyBERT/](https://maartengr.github.io/KeyBERT/)

---

## Graph Analytics

**Original PageRank paper (Brin & Page, 1998)**
Defines the random-walk model with damping factor (0.85 here), dangling-node handling, and power
iteration. The implementation in `pagerank_full.py` follows this directly.
[http://ilpubs.stanford.edu:8090/422/](http://ilpubs.stanford.edu:8090/422/)

**NetworkX**
Python graph library. Used in `graph.py` (legacy Postgres path) for `nx.pagerank`, Katz
centrality, Louvain community detection, and `simple_cycles`. Not used in the current
full-corpus `pagerank_full.py` (which uses scipy.sparse directly).
[https://networkx.org/documentation/stable/](https://networkx.org/documentation/stable/)

**scipy.sparse**
Sparse matrix library used in `pagerank_full.py` for the transition matrix `M = A.T @ D_inv`.
CSR format enables fast matrix-vector multiply for power iteration at 1M+ edges.
[https://docs.scipy.org/doc/scipy/reference/sparse.html](https://docs.scipy.org/doc/scipy/reference/sparse.html)

---

## Storage & Analytics

**ClickHouse MergeTree family**
Column-oriented storage engine. `MergeTree` for append-only edge tables; `ReplacingMergeTree`
for overlay tables that need idempotent upsert (deduplicated at read time with `FINAL`).
[https://clickhouse.com/docs/engines/table-engines/mergetree-family/replacingmergetree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/replacingmergetree)

**ClickHouse LowCardinality**
Dictionary encoding for string columns with few distinct values. Applied to `source`, `tagger`,
`venue`, and `cited_openalex_id` — the last one particularly impactful for the 1M-row references
table (noted in schema comments as "HUGE for storage").
[https://clickhouse.com/docs/sql-reference/data-types/lowcardinality](https://clickhouse.com/docs/sql-reference/data-types/lowcardinality)

---

## Clustering

**MiniBatchKMeans (scikit-learn)**
Online variant of KMeans using `partial_fit` — used in `cluster_embeddings.py` to cluster 478k
384-dim vectors into 64 semantic clusters without loading all vectors at once (~700 MB saved).
[https://scikit-learn.org/stable/modules/generated/sklearn.cluster.MiniBatchKMeans.html](https://scikit-learn.org/stable/modules/generated/sklearn.cluster.MiniBatchKMeans.html)

---

## Data Sources

**OpenAlex**
Open academic graph: papers, authors, institutions, concepts, citation counts. Primary metadata
source for the arxiv corpus (400k papers). Known limitation: `submitted_date` reflects the
latest revision, not original submission — corrected by the `effective_year` UDF.
[https://openalex.org/](https://openalex.org/)

**Semantic Scholar (S2)**
Used via `semantic_scholar_enrichment.py` to fetch more accurate `citationCount` for top papers,
stored in `citation_overlay_v2`.
[https://www.semanticscholar.org/product/api](https://www.semanticscholar.org/product/api)
