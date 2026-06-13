"""ArXiv abstract refresh for contaminated OpenAlex records.

Detects suspect arxiv papers (title corrected in metadata overlay, or low
title/abstract word overlap), re-fetches abstracts from the arXiv API, and
writes corrections into abstract_overlay_v2.
"""

from __future__ import annotations

import logging
import re
import time

import feedparser
import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from researchpapers.ch_db import connect as ch_connect
from researchpapers.overlays import ensure_abstract_overlay_table

log = logging.getLogger("researchpapers.arxiv_abstract_refresh")

ARXIV_API = "https://export.arxiv.org/api/query"
MAILTO = "anonymous@example.com"
_WORD_RE = re.compile(r"[a-z]{4,}")


def _title_abstract_overlap(title: str, abstract: str) -> float:
    title_words = set(_WORD_RE.findall((title or "").lower()))
    abstract_words = set(_WORD_RE.findall((abstract or "").lower()))
    if not title_words:
        return 1.0
    return len(title_words & abstract_words) / len(title_words)


def _suspicion_reason(
    raw_title: str,
    effective_title: str,
    abstract: str,
) -> str | None:
    if effective_title and raw_title and effective_title.strip() != raw_title.strip():
        return "title_corrected_in_metadata"
    overlap = _title_abstract_overlap(effective_title or raw_title, abstract or "")
    if overlap < 0.08:
        return "low_title_abstract_overlap"
    return None


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(httpx.HTTPError),
)
def _arxiv_batch(client: httpx.Client, arxiv_ids: list[str]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    if not arxiv_ids:
        return out
    resp = client.get(
        ARXIV_API,
        params={"id_list": ",".join(arxiv_ids), "max_results": len(arxiv_ids)},
    )
    resp.raise_for_status()
    feed = feedparser.parse(resp.text)
    for entry in feed.entries:
        entry_id = entry.get("id", "")
        m = re.search(r"arxiv\.org/abs/([0-9a-zA-Z.\-/]+?)(?:v\d+)?$", entry_id)
        if not m:
            continue
        aid = m.group(1)
        title = " ".join((entry.get("title") or "").split())
        abstract = " ".join((entry.get("summary") or "").split())
        if abstract:
            out[aid] = {"title": title, "abstract": abstract}
    return out


def detect_suspect_papers(*, limit: int = 5000, skip_existing: bool = True) -> list[tuple]:
    skip_clause = (
        "AND p.paper_id NOT IN (SELECT paper_id FROM abstract_overlay_v2 FINAL)"
        if skip_existing
        else ""
    )
    with ch_connect() as ch:
        rows = ch.query(
            f"""
            SELECT
              p.paper_id,
              p.arxiv_id,
              p.title,
              p.abstract,
              coalesce(nullIf(m.title, ''), p.title) AS effective_title
            FROM papers AS p FINAL
            LEFT JOIN paper_metadata_v2 AS m FINAL ON m.paper_id = p.paper_id
            WHERE p.source = 'arxiv'
              AND length(p.arxiv_id) > 0
              AND length(p.abstract) > 50
              {skip_clause}
            ORDER BY p.citation_count DESC
            LIMIT %(lim)s
            """,
            parameters={"lim": limit},
        ).result_rows

    suspects: list[tuple] = []
    for row in rows:
        paper_id, arxiv_id, raw_title, abstract, effective_title = row
        reason = _suspicion_reason(raw_title, effective_title, abstract or "")
        if reason:
            suspects.append((paper_id, arxiv_id, raw_title, abstract, effective_title, reason))
    return suspects


def refresh_suspect_abstracts(
    *,
    detect_limit: int = 5000,
    skip_existing: bool = True,
    reembed: bool = False,
) -> dict[str, int | float]:
    """Detect and refresh suspect arxiv abstracts from the arXiv API."""
    ensure_abstract_overlay_table()
    suspects = detect_suspect_papers(limit=detect_limit, skip_existing=skip_existing)
    log.info("detected %d suspect papers", len(suspects))
    if not suspects:
        return {"detected": 0, "refreshed": 0, "unchanged": 0, "failed": 0}

    client = httpx.Client(
        timeout=30.0,
        headers={"User-Agent": f"researchpapers/0.2 ({MAILTO})"},
        params={"mailto": MAILTO},
    )
    counters: dict[str, int | float] = {
        "detected": len(suspects),
        "refreshed": 0,
        "unchanged": 0,
        "failed": 0,
    }
    t0 = time.monotonic()

    arxiv_by_paper = {s[0]: s[1] for s in suspects}
    paper_by_arxiv = {s[1]: s[0] for s in suspects}
    old_abstract_by_paper = {s[0]: s[3] or "" for s in suspects}
    reason_by_paper = {s[0]: s[5] for s in suspects}

    arxiv_fetched: dict[str, dict[str, str]] = {}
    all_aids = list(paper_by_arxiv.keys())
    try:
        for i in range(0, len(all_aids), 80):
            chunk = all_aids[i : i + 80]
            try:
                arxiv_fetched.update(_arxiv_batch(client, chunk))
            except Exception as e:  # noqa: BLE001
                log.warning("arxiv batch fetch failed: %s", e)
                counters["failed"] += len(chunk)
            time.sleep(3.5)
    finally:
        client.close()

    inserts: list[list[object]] = []
    refreshed_ids: list[str] = []
    for paper_id, arxiv_id in arxiv_by_paper.items():
        fetched = arxiv_fetched.get(arxiv_id)
        if not fetched:
            counters["failed"] += 1
            continue
        new_abstract = fetched["abstract"]
        old_abstract = old_abstract_by_paper[paper_id]
        if new_abstract.strip() == old_abstract.strip():
            counters["unchanged"] += 1
            continue
        inserts.append([
            paper_id,
            arxiv_id,
            new_abstract,
            fetched.get("title") or "",
            reason_by_paper[paper_id],
        ])
        refreshed_ids.append(paper_id)
        counters["refreshed"] += 1

    if inserts:
        with ch_connect() as ch:
            ch.insert(
                "abstract_overlay_v2",
                inserts,
                column_names=["paper_id", "arxiv_id", "abstract", "title", "detection_reason"],
            )

    if reembed and refreshed_ids:
        counters["reembedded"] = _reembed_papers(refreshed_ids)

    counters["elapsed_seconds"] = round(time.monotonic() - t0, 2)
    return counters


def _reembed_papers(paper_ids: list[str]) -> int:
    from sentence_transformers import SentenceTransformer

    from researchpapers.overlays import EFFECTIVE_ABSTRACT_SQL, EFFECTIVE_TITLE_SQL, OVERLAY_JOINS_SQL

    with ch_connect() as ch:
        rows = ch.query(
            f"""
            SELECT p.paper_id,
                   {EFFECTIVE_TITLE_SQL} AS title,
                   {EFFECTIVE_ABSTRACT_SQL} AS abstract
            FROM papers AS p FINAL
            {OVERLAY_JOINS_SQL}
            WHERE p.paper_id IN %(ids)s
            """,
            parameters={"ids": paper_ids},
        ).result_rows
    if not rows:
        return 0

    model = SentenceTransformer("all-MiniLM-L6-v2")
    texts = [f"{r[1] or ''}. {(r[2] or '')[:1000]}" for r in rows]
    embeddings = model.encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False)
    payload = [[r[0], embeddings[i].tolist(), "all-MiniLM-L6-v2"] for i, r in enumerate(rows)]
    with ch_connect() as ch:
        ch.insert(
            "paper_embeddings",
            payload,
            column_names=["paper_id", "embedding", "model"],
        )
    return len(payload)
