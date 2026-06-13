"""Overlay table DDL and effective-field SQL for metadata/citation/abstract corrections.

Ranking and detail surfaces JOIN these tables instead of mutating the partition-keyed
`papers` table. Provenance is exposed via citation_source / abstract_source helpers.
"""

from __future__ import annotations

from researchpapers.ch_db import connect as ch_connect

EFFECTIVE_CITATION_SQL = (
    "coalesce(nullIf(s2.citation_count, 0), nullIf(m.citation_count, 0), p.citation_count)"
)
EFFECTIVE_TITLE_SQL = "coalesce(nullIf(m.title, ''), p.title)"
EFFECTIVE_ABSTRACT_SQL = "coalesce(nullIf(ab.abstract, ''), p.abstract)"
CITATION_SOURCE_SQL = (
    "multiIf(s2.citation_count > 0, 'semantic_scholar', "
    "m.citation_count > 0, 'openalex_refresh', 'openalex')"
)
ABSTRACT_SOURCE_SQL = "if(length(ab.abstract) > 0, 'arxiv_refresh', 'openalex')"

OVERLAY_JOINS_SQL = """
LEFT JOIN paper_metadata_v2 AS m FINAL ON m.paper_id = p.paper_id
LEFT JOIN citation_overlay_v2 AS s2 FINAL ON s2.paper_id = p.paper_id
LEFT JOIN abstract_overlay_v2 AS ab FINAL ON ab.paper_id = p.paper_id
"""


def ensure_citation_overlay_table() -> None:
    with ch_connect() as ch:
        ch.command("""
            CREATE TABLE IF NOT EXISTS citation_overlay_v2 (
              paper_id String,
              s2_paper_id String,
              citation_count UInt32,
              source LowCardinality(String) DEFAULT 'semantic_scholar',
              enriched_at DateTime DEFAULT now()
            )
            ENGINE = ReplacingMergeTree(enriched_at)
            ORDER BY paper_id
        """)


def ensure_abstract_overlay_table() -> None:
    with ch_connect() as ch:
        ch.command("""
            CREATE TABLE IF NOT EXISTS abstract_overlay_v2 (
              paper_id String,
              arxiv_id String,
              abstract String,
              title String,
              detection_reason LowCardinality(String),
              refreshed_at DateTime DEFAULT now()
            )
            ENGINE = ReplacingMergeTree(refreshed_at)
            ORDER BY paper_id
        """)


def ensure_author_graph_tables() -> None:
    with ch_connect() as ch:
        ch.command("""
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
            ORDER BY author_id
        """)
        ch.command("""
            CREATE TABLE IF NOT EXISTS paper_authorships_v2 (
              paper_id String,
              author_id String,
              author_name String,
              position UInt8,
              source LowCardinality(String),
              updated_at DateTime DEFAULT now()
            )
            ENGINE = ReplacingMergeTree(updated_at)
            ORDER BY (paper_id, author_id)
        """)


def ensure_all_overlay_tables() -> None:
    ensure_citation_overlay_table()
    ensure_abstract_overlay_table()
    ensure_author_graph_tables()
