# Project Status

Last updated: 2026-06-08

## Current Scope

researchPapers is a ClickHouse-backed academic-paper intelligence platform. It
indexes papers from arxiv, OpenReview, bioRxiv, and medRxiv, exposes FastAPI
search and insight endpoints, and serves an Astro + React dashboard for semantic
search, citation graph analysis, tags, reviews, hot papers, sleepers, similar
papers, and HighSignal-style research digests.

## Done

- Roughly 488k papers are ingested across arxiv, OpenReview, bioRxiv, and
  medRxiv.
- ClickHouse is the current runtime database for API, frontend, and pipeline
  reads; Postgres remains only for legacy CLI paths.
- Full-corpus PageRank, paper-to-paper edges, MiniLM embeddings, semantic
  clusters, spaCy tags, MLX tagging, and correction overlays are documented.
- FastAPI endpoints exist for health, stats, search, paper detail, semantic
  search, sleepers, hot papers, similar papers, tags, authors, and reviews.
- Astro frontend and static JSON exports are wired to the FastAPI/ClickHouse
  data path.
- Warm restore, cold rebuild, deployment shapes, dump/export scripts, and CLI
  commands are documented.

## Planned Next

1. Semantic Scholar enrichment for top papers. PRD: `docs/prds/semantic-scholar-enrichment.md`
2. ArXiv abstract refresh for contaminated records. PRD: `docs/prds/arxiv-abstract-refresh.md`
3. Author graph and disambiguation expansion. PRD: `docs/prds/author-graph-disambiguation.md`
4. Decide the deployment target before public use: same-host deployment is the
   preferred path unless a CDN/static frontend launch is needed.
5. Keep static JSON exports fresh after new ingestion or retagging with
   `uv run papers export-ch` and a frontend rebuild.

## Deferred / Parked

- Cloudflare/Vercel CDN deployment is deferred while same-host deployment is
  preferred.
- Legacy Postgres pipeline work is parked unless needed for cold restore or old
  commands.
- OrbStack/macOS VM instability is an environment issue; do not treat it as a
  product regression without reproducing on a stable Docker daemon.
