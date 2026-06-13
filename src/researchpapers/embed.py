"""Populate papers.abstract_embedding with sentence-transformers all-MiniLM-L6-v2.

384-dim L2-normalized vectors. Streams papers from ClickHouse in chunks so we
never materialize the full queue in RAM. Anti-join against existing embeddings.
"""

from __future__ import annotations

import logging
import time

from researchpapers.ch_db import connect as ch_connect
from researchpapers.ram import clamp_batch_size, wait_for_ram

log = logging.getLogger("researchpapers.embed")

MODEL_NAME = "all-MiniLM-L6-v2"
EMBED_DIM = 384
CHUNK_SIZE = 5000
DEFAULT_BATCH_SIZE = 64


def _fetch_chunk(
    *,
    source: str | None,
    chunk_size: int,
) -> list[tuple[str, str, str | None]]:
    src_clause = "AND p.source = %(src)s" if source else ""
    with ch_connect() as ch:
        return ch.query(
            f"""
            SELECT p.paper_id, p.title, p.abstract
            FROM papers AS p FINAL
            WHERE length(p.abstract) > 80
              AND p.paper_id NOT IN (SELECT paper_id FROM paper_embeddings FINAL)
              {src_clause}
            ORDER BY p.paper_id
            LIMIT %(lim)s
            """,
            parameters={"src": source, "lim": chunk_size} if source else {"lim": chunk_size},
        ).result_rows


def embed_papers(
    *,
    source: str | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    limit: int | None = None,
    chunk_size: int = CHUNK_SIZE,
) -> dict[str, int | float]:
    """Embed title+abstract → INSERT into paper_embeddings (separate table, no UPDATE)."""
    from sentence_transformers import SentenceTransformer

    wait_for_ram()
    log.info("loading %s", MODEL_NAME)
    model = SentenceTransformer(MODEL_NAME)

    counters: dict[str, int | float] = {"embedded": 0}
    t0 = time.monotonic()
    remaining = int(limit) if limit else None

    while True:
        if remaining is not None and remaining <= 0:
            break
        take = min(chunk_size, remaining) if remaining is not None else chunk_size
        rows = _fetch_chunk(source=source, chunk_size=take)
        if not rows:
            break

        effective_batch = clamp_batch_size(batch_size)
        texts = [f"{r[1] or ''}. {(r[2] or '')[:1000]}" for r in rows]
        embeddings = model.encode(
            texts,
            batch_size=effective_batch,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        payload = [
            [r[0], embeddings[i].tolist(), MODEL_NAME]
            for i, r in enumerate(rows)
        ]
        with ch_connect() as ch:
            ch.insert(
                "paper_embeddings",
                payload,
                column_names=["paper_id", "embedding", "model"],
            )
        counters["embedded"] += len(rows)
        if remaining is not None:
            remaining -= len(rows)

        elapsed = time.monotonic() - t0
        rate = counters["embedded"] / elapsed if elapsed else 0
        log.info("embedded %d (%.1f p/s)", counters["embedded"], rate)

        if len(rows) < take:
            break
        wait_for_ram()

    elapsed = time.monotonic() - t0
    counters["elapsed_seconds"] = round(elapsed, 2)
    counters["papers_per_sec"] = round(counters["embedded"] / elapsed, 1) if elapsed else 0
    return counters
