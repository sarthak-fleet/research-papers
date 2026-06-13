# Project Status

Last updated: 2026-06-13

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
- **Semantic Scholar enrichment** (`papers enrich-citations`) writes
  `citation_overlay_v2`; ranking surfaces prefer S2 counts with provenance.
- **ArXiv abstract refresh** (`papers refresh-abstracts`) detects contaminated
  records and writes `abstract_overlay_v2`; search/detail use corrected text.
- **Author graph** (`papers build-author-graph`) builds `authors_v2` and
  `paper_authorships_v2`; API exposes `/authors/v2/{id}`, coauthors, and
  `/authors/resolve`.

## Planned Next

1. Decide the deployment target before public use: same-host deployment is the
   preferred path unless a CDN/static frontend launch is needed.
2. Keep static JSON exports fresh after new ingestion or retagging with
   `uv run papers export-ch` and a frontend rebuild.
3. Run overlay jobs on production corpus after deploy:
   `enrich-citations`, `refresh-abstracts --reembed`, `build-author-graph`.

## Deferred / Parked

- Cloudflare/Vercel CDN deployment is deferred while same-host deployment is
  preferred.
- Legacy Postgres pipeline work is parked unless needed for cold restore or old
  commands.
- OrbStack/macOS VM instability is an environment issue; do not treat it as a
  product regression without reproducing on a stable Docker daemon.
- Full-corpus Semantic Scholar backfill and manual author curation remain out of
  scope.
