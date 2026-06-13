-- Overlay tables for metadata/citation/abstract corrections and author graph.
-- Created at runtime by pipeline jobs; kept here for warm-restore documentation.

CREATE TABLE IF NOT EXISTS citation_overlay_v2 (
  paper_id String,
  s2_paper_id String,
  citation_count UInt32,
  source LowCardinality(String) DEFAULT 'semantic_scholar',
  enriched_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(enriched_at)
ORDER BY paper_id;

CREATE TABLE IF NOT EXISTS abstract_overlay_v2 (
  paper_id String,
  arxiv_id String,
  abstract String,
  title String,
  detection_reason LowCardinality(String),
  refreshed_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(refreshed_at)
ORDER BY paper_id;

CREATE TABLE IF NOT EXISTS authors_v2 (
  author_id String,
  display_name String,
  aliases Array(String),
  source LowCardinality(String),
  openalex_id Nullable(String),
  n_papers UInt32 DEFAULT 0,
  sum_citations UInt64 DEFAULT 0,
  top_tags Array(String),
  top_clusters Array(UInt16),
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY author_id;

CREATE TABLE IF NOT EXISTS paper_authorships_v2 (
  paper_id String,
  author_id String,
  author_name String,
  position UInt8,
  source LowCardinality(String),
  updated_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (paper_id, author_id);

-- Existing overlay tables (also created by pipeline jobs).
CREATE TABLE IF NOT EXISTS paper_metadata_v2 (
  paper_id String,
  title String,
  citation_count UInt32,
  authors Array(Tuple(name String, openalex_id String)),
  refreshed_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(refreshed_at)
ORDER BY paper_id;

CREATE TABLE IF NOT EXISTS paper_scores_v2 (
  paper_id String,
  pagerank Float64,
  computed_at DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(computed_at)
ORDER BY paper_id;
