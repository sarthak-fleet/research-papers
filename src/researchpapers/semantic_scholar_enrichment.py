"""Semantic Scholar citation enrichment for top papers.

Fetches citationCount + paperId via the /paper/batch endpoint and writes into
citation_overlay_v2. Ranking surfaces prefer this overlay when present.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from researchpapers.ch_db import connect as ch_connect
from researchpapers.config import load_settings
from researchpapers.ram import wait_for_ram
from researchpapers.overlays import ensure_citation_overlay_table

log = logging.getLogger("researchpapers.semantic_scholar_enrichment")

S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
BATCH_SIZE = 500
REQUEST_INTERVAL_SECONDS = 1.0


def _chunks(items: list[str], n: int) -> Iterable[list[str]]:
    for i in range(0, len(items), n):
        yield items[i : i + n]


def _s2_id_for_row(arxiv_id: str | None, doi: str | None) -> str | None:
    if arxiv_id:
        return f"ARXIV:{arxiv_id}"
    if doi:
        return f"DOI:{doi}"
    return None


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    retry=retry_if_exception_type(httpx.HTTPStatusError),
)
def _post_batch(client: httpx.Client, ids: list[str], api_key: str | None) -> list[dict | None]:
    headers = {"x-api-key": api_key} if api_key else {}
    resp = client.post(
        S2_BATCH_URL,
        params={"fields": "paperId,citationCount,externalIds,title"},
        json={"ids": ids},
        headers=headers,
    )
    resp.raise_for_status()
    return resp.json()


def enrich_top_papers(
    *,
    limit: int = 10000,
    settings: Settings | None = None,
    skip_existing: bool = True,
) -> dict[str, int | float]:
    """Enrich top-cited arxiv papers with Semantic Scholar citation counts."""
    settings = settings or load_settings()
    ensure_citation_overlay_table()
    wait_for_ram()

    skip_clause = (
        "AND p.paper_id NOT IN (SELECT paper_id FROM citation_overlay_v2 FINAL)"
        if skip_existing
        else ""
    )
    with ch_connect() as ch:
        rows = ch.query(
            f"""
            SELECT p.paper_id, p.arxiv_id, p.doi, p.citation_count
            FROM papers AS p FINAL
            WHERE p.source = 'arxiv'
              AND (length(p.arxiv_id) > 0 OR length(p.doi) > 0)
              {skip_clause}
            ORDER BY p.citation_count DESC
            LIMIT %(lim)s
            """,
            parameters={"lim": limit},
        ).result_rows

    log.info("enriching %d papers from Semantic Scholar", len(rows))
    if not rows:
        return {"enriched": 0, "skipped": 0, "failed": 0}

    interval = 0.1 if settings.semantic_scholar_api_key else REQUEST_INTERVAL_SECONDS
    counters: dict[str, int | float] = {"enriched": 0, "skipped": 0, "failed": 0, "improved": 0}
    t0 = time.monotonic()

    client = httpx.Client(timeout=30.0, headers={"User-Agent": settings.user_agent})
    last_request_at = 0.0
    try:
        batch: list[tuple[str, str | None, str | None, int]] = []
        s2_ids: list[str] = []
        for paper_id, arxiv_id, doi, old_cites in rows:
            s2_id = _s2_id_for_row(arxiv_id, doi)
            if not s2_id:
                counters["skipped"] += 1
                continue
            batch.append((paper_id, arxiv_id, doi, int(old_cites or 0)))
            s2_ids.append(s2_id)

        for chunk_idx in range(0, len(s2_ids), BATCH_SIZE):
            chunk_ids = s2_ids[chunk_idx : chunk_idx + BATCH_SIZE]
            chunk_rows = batch[chunk_idx : chunk_idx + BATCH_SIZE]
            elapsed = time.monotonic() - last_request_at
            if elapsed < interval:
                time.sleep(interval - elapsed)
            try:
                results = _post_batch(client, chunk_ids, settings.semantic_scholar_api_key)
            except Exception as e:  # noqa: BLE001
                log.warning("S2 batch failed: %s", e)
                counters["failed"] += len(chunk_rows)
                continue
            last_request_at = time.monotonic()

            inserts: list[list[object]] = []
            for (paper_id, _arxiv_id, _doi, old_cites), paper in zip(chunk_rows, results, strict=True):
                if not paper:
                    counters["skipped"] += 1
                    continue
                s2_paper_id = paper.get("paperId") or ""
                new_cites = int(paper.get("citationCount") or 0)
                if not s2_paper_id or new_cites <= 0:
                    counters["skipped"] += 1
                    continue
                inserts.append([paper_id, s2_paper_id, new_cites, "semantic_scholar"])
                counters["enriched"] += 1
                if new_cites > old_cites:
                    counters["improved"] += 1

            if inserts:
                with ch_connect() as ch:
                    ch.insert(
                        "citation_overlay_v2",
                        inserts,
                        column_names=["paper_id", "s2_paper_id", "citation_count", "source"],
                    )
            wait_for_ram()
            if counters["enriched"] % 500 < BATCH_SIZE:
                log.info(
                    "progress: enriched=%d improved=%d (%.1fs)",
                    counters["enriched"],
                    counters["improved"],
                    time.monotonic() - t0,
                )
    finally:
        client.close()

    counters["elapsed_seconds"] = round(time.monotonic() - t0, 2)
    return counters
