"""Author graph builder: canonical identities, authorship links, coauthor neighborhoods.

Builds authors_v2 and paper_authorships_v2 from paper_metadata_v2 OpenAlex IDs,
then adds inferred buckets for ambiguous name-only authorships on high-signal papers.
"""

from __future__ import annotations

import logging

from researchpapers.ch_db import connect as ch_connect
from researchpapers.overlays import ensure_author_graph_tables

log = logging.getLogger("researchpapers.author_graph")


def build_author_graph(*, expand_metadata_limit: int = 10000) -> dict[str, int]:
    """Rebuild author graph tables from metadata overlay + paper authorships."""
    from researchpapers.ram import wait_for_ram

    wait_for_ram()
    ensure_author_graph_tables()

    # Expand metadata refresh if the overlay is smaller than requested.
    with ch_connect() as ch:
        n_meta = ch.query("SELECT count() FROM paper_metadata_v2 FINAL").result_rows[0][0]
    if n_meta < expand_metadata_limit:
        from researchpapers import refresh_metadata

        log.info("refreshing metadata for top %d papers (had %d)", expand_metadata_limit, n_meta)
        refresh_metadata.refresh_top_papers(limit=expand_metadata_limit)

    counters = {"authorships": 0, "authors": 0, "inferred": 0}

    with ch_connect() as ch:
        # Clear stale rows by truncating — tables are small overlay-sized.
        ch.command("TRUNCATE TABLE paper_authorships_v2")
        ch.command("TRUNCATE TABLE authors_v2")

        # 1. OpenAlex-disambiguated authorships from paper_metadata_v2.
        ch.command("""
            INSERT INTO paper_authorships_v2 (paper_id, author_id, author_name, position, source)
            SELECT
              m.paper_id,
              a.2 AS author_id,
              a.1 AS author_name,
              toUInt8(idx) AS position,
              'openalex' AS source
            FROM paper_metadata_v2 AS m FINAL
            ARRAY JOIN m.authors AS a, arrayEnumerate(m.authors) AS idx
            WHERE length(a.2) > 0 AND length(a.1) > 0
        """)
        counters["authorships"] = ch.query("SELECT count() FROM paper_authorships_v2").result_rows[0][0]

        # 2. Aggregate canonical author records.
        ch.command("""
            INSERT INTO authors_v2 (
              author_id, display_name, aliases, source, openalex_id,
              n_papers, sum_citations, top_tags, top_clusters
            )
            SELECT
              pa.author_id,
              argMax(pa.author_name, p.citation_count) AS display_name,
              groupUniqArray(pa.author_name) AS aliases,
              'openalex' AS source,
              pa.author_id AS openalex_id,
              count() AS n_papers,
              sum(coalesce(nullIf(m.citation_count, 0), p.citation_count)) AS sum_citations,
              [] AS top_tags,
              arraySlice(groupUniqArray(p.semantic_cluster), 1, 6) AS top_clusters
            FROM paper_authorships_v2 AS pa
            JOIN papers AS p FINAL ON p.paper_id = pa.paper_id
            LEFT JOIN paper_metadata_v2 AS m FINAL ON m.paper_id = pa.paper_id
            WHERE pa.source = 'openalex'
            GROUP BY pa.author_id
        """)
        counters["authors"] = ch.query("SELECT count() FROM authors_v2").result_rows[0][0]

        # 3. Inferred buckets for top-cited papers still on raw author name strings.
        ch.command("""
            INSERT INTO paper_authorships_v2 (paper_id, author_id, author_name, position, source)
            SELECT
              p.paper_id,
              concat('inferred:', toString(cityHash64(author, coalesce(p.community_id, 0), coalesce(p.semantic_cluster, 0)))) AS author_id,
              author,
              toUInt8(idx) AS position,
              'inferred' AS source
            FROM papers AS p FINAL
            ARRAY JOIN p.authors AS author, arrayEnumerate(p.authors) AS idx
            WHERE p.source = 'arxiv'
              AND length(author) > 0
              AND p.paper_id NOT IN (SELECT paper_id FROM paper_authorships_v2)
              AND p.citation_count >= 10
            LIMIT 50000
        """)
        inferred_authorships = ch.query(
            "SELECT count() FROM paper_authorships_v2 WHERE source = 'inferred'"
        ).result_rows[0][0]
        counters["inferred"] = int(inferred_authorships)
        counters["authorships"] = ch.query("SELECT count() FROM paper_authorships_v2").result_rows[0][0]

        ch.command("""
            INSERT INTO authors_v2 (
              author_id, display_name, aliases, source, openalex_id,
              n_papers, sum_citations, top_tags, top_clusters
            )
            SELECT
              pa.author_id,
              argMax(pa.author_name, p.citation_count) AS display_name,
              groupUniqArray(pa.author_name) AS aliases,
              'inferred' AS source,
              NULL AS openalex_id,
              count() AS n_papers,
              sum(p.citation_count) AS sum_citations,
              [] AS top_tags,
              arraySlice(groupUniqArray(p.semantic_cluster), 1, 6) AS top_clusters
            FROM paper_authorships_v2 AS pa
            JOIN papers AS p FINAL ON p.paper_id = pa.paper_id
            WHERE pa.source = 'inferred'
            GROUP BY pa.author_id
        """)
        counters["authors"] = ch.query("SELECT count() FROM authors_v2").result_rows[0][0]

    return counters


def lookup_author(author_id: str) -> dict | None:
    with ch_connect() as ch:
        profile = ch.query(
            """
            SELECT author_id, display_name, aliases, source, openalex_id,
                   n_papers, sum_citations, top_tags, top_clusters
            FROM authors_v2 FINAL
            WHERE author_id = %(aid)s
            """,
            parameters={"aid": author_id},
        ).result_rows
        if not profile:
            return None
        row = profile[0]
        papers = ch.query(
            """
            SELECT
              p.paper_id,
              coalesce(nullIf(m.title, ''), p.title) AS title,
              coalesce(nullIf(s2.citation_count, 0), nullIf(m.citation_count, 0), p.citation_count) AS citation_count,
              p.submitted_date,
              pa.position
            FROM paper_authorships_v2 AS pa FINAL
            JOIN papers AS p FINAL ON p.paper_id = pa.paper_id
            LEFT JOIN paper_metadata_v2 AS m FINAL ON m.paper_id = p.paper_id
            LEFT JOIN citation_overlay_v2 AS s2 FINAL ON s2.paper_id = p.paper_id
            WHERE pa.author_id = %(aid)s
            ORDER BY citation_count DESC
            LIMIT 50
            """,
            parameters={"aid": author_id},
        ).result_rows
    return {
        "author_id": row[0],
        "display_name": row[1],
        "aliases": list(row[2] or []),
        "source": row[3],
        "openalex_id": row[4],
        "n_papers": int(row[5] or 0),
        "sum_citations": int(row[6] or 0),
        "top_tags": list(row[7] or []),
        "top_clusters": [int(c) for c in (row[8] or []) if c is not None],
        "papers": [
            {
                "paper_id": p[0],
                "title": p[1],
                "citation_count": int(p[2] or 0),
                "submitted_date": str(p[3]) if p[3] else None,
                "position": int(p[4] or 0),
            }
            for p in papers
        ],
    }


def coauthors_for(author_id: str, *, limit: int = 25) -> list[dict]:
    with ch_connect() as ch:
        rows = ch.query(
            """
            WITH mine AS (
              SELECT paper_id FROM paper_authorships_v2 FINAL WHERE author_id = %(aid)s
            ),
            co AS (
              SELECT
                pa2.author_id,
                argMax(pa2.author_name, p.citation_count) AS display_name,
                argMax(pa2.source, p.citation_count) AS source,
                count() AS n_shared_papers,
                sum(p.citation_count) AS sum_citations
              FROM paper_authorships_v2 AS pa2 FINAL
              JOIN mine ON mine.paper_id = pa2.paper_id
              JOIN papers AS p FINAL ON p.paper_id = pa2.paper_id
              WHERE pa2.author_id != %(aid)s
              GROUP BY pa2.author_id
              ORDER BY n_shared_papers DESC, sum_citations DESC
              LIMIT %(lim)s
            )
            SELECT author_id, display_name, source, n_shared_papers, sum_citations
            FROM co
            """,
            parameters={"aid": author_id, "lim": limit},
        ).result_rows
    return [
        {
            "author_id": r[0],
            "display_name": r[1],
            "source": r[2],
            "n_shared_papers": int(r[3]),
            "sum_citations": int(r[4] or 0),
        }
        for r in rows
    ]


def resolve_author_name(name: str, *, limit: int = 10) -> list[dict]:
    with ch_connect() as ch:
        rows = ch.query(
            """
            SELECT author_id, display_name, source, n_papers, sum_citations, top_clusters
            FROM authors_v2 FINAL
            WHERE has(aliases, %(name)s) OR display_name = %(name)s
            ORDER BY sum_citations DESC
            LIMIT %(lim)s
            """,
            parameters={"name": name, "lim": limit},
        ).result_rows
    return [
        {
            "author_id": r[0],
            "display_name": r[1],
            "source": r[2],
            "n_papers": int(r[3] or 0),
            "sum_citations": int(r[4] or 0),
            "top_clusters": [int(c) for c in (r[5] or []) if c is not None],
        }
        for r in rows
    ]
