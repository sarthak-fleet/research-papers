# Retro: Postgres → ClickHouse Migration

**Date:** 2026-05-30 (initial ClickHouse-first commit)
**Scope:** Runtime database switch; Postgres demoted to legacy ingest staging store.

---

## What happened

The project started on Postgres (migrations 001–012 document the full schema evolution: papers,
paper_tags, references_paper, cited_works, citation_cycles, graph scores, communities, semantic
clusters, tags). At some point before the first git commit on this repo, the decision was made to
move the runtime to ClickHouse. The initial commit message reads: "Architecture: ClickHouse-first
runtime. Postgres remains only as a legacy ingest staging store for the arxiv pipeline."

`scripts/migrate_pg_to_ch.py` is a one-shot migrator that moved papers, paper_tags, references,
cited_works, and citation_cycles from Postgres to ClickHouse. It exists as a historical artifact;
it is not part of the normal pipeline.

## What went well

- The Postgres migrations (001–012) preserved a clean schema history, making the CH schema design
  straightforward: every PG column has a direct CH equivalent (JSONB arrays → `Array(String)`,
  BIGSERIAL PKs dropped in favour of `paper_id String`).
- `ReplacingMergeTree` for overlay tables provided idempotent upsert without the `ON CONFLICT`
  boilerplate of Postgres.
- ClickHouse's `LowCardinality(String)` on `cited_openalex_id` gave significant storage savings
  on the 1M-row references table, which was identified immediately in the schema comments.

## What was hard

- `ALTER TABLE ... UPDATE` is slow on year-partitioned tables. The original plan (update
  `pagerank_score` in-place on the `papers` table) had to be abandoned in favour of separate
  overlay tables (`paper_scores_v2`, `paper_metadata_v2`, etc.).
- Every read from a `ReplacingMergeTree` requires `FINAL`; forgetting it caused the
  "fix query drift" bug (2026-06-12) where counts were inflated by duplicate rows.
- ClickHouse UDFs (`effective_year`, `effective_date`) live in system state, not the data volume.
  After the first warm restore from a dump, the UDFs were missing and year-based filters
  returned wrong results. Fixed by persisting them in `clickhouse/init/02_functions.sql` and
  re-applying in `deploy.sh`.

## Lessons

- See [lessons.md](../lessons.md) for ClickHouse-specific pitfalls (ReplacingMergeTree, partition
  mutations, LowCardinality, UDF persistence).
