"""Cluster the embedding space with MiniBatchKMeans.

Fits incrementally from ClickHouse chunks so we never load all 478k vectors at
once (~700 MB saved on 16 GB hosts).
"""

from __future__ import annotations

import logging
import time

import numpy as np

from researchpapers.ch_db import connect as ch_connect
from researchpapers.ram import m1_16gb_profile, wait_for_ram

log = logging.getLogger("researchpapers.cluster")

CHUNK_ROWS = 20_000


def _embedding_chunks(*, chunk_rows: int, sample_size: int | None = None):
    offset = 0
    total = 0
    while True:
        limit = chunk_rows
        if sample_size is not None:
            remaining = sample_size - total
            if remaining <= 0:
                break
            limit = min(limit, remaining)
        with ch_connect() as ch:
            rows = ch.query(
                """
                SELECT paper_id, embedding
                FROM paper_embeddings FINAL
                ORDER BY paper_id
                LIMIT %(lim)s OFFSET %(off)s
                """,
                parameters={"lim": limit, "off": offset},
            ).result_rows
        if not rows:
            break
        paper_ids = [r[0] for r in rows]
        X = np.array([r[1] for r in rows], dtype=np.float32)
        yield paper_ids, X
        total += len(rows)
        offset += len(rows)
        if len(rows) < limit:
            break


def cluster_papers(
    n_clusters: int = 64,
    batch_size: int = 2048,
    sample_size: int | None = None,
    chunk_rows: int | None = None,
) -> dict:
    from sklearn.cluster import MiniBatchKMeans

    wait_for_ram()
    chunk_rows = chunk_rows or m1_16gb_profile()["cluster_chunk_rows"]
    t0 = time.monotonic()

    km = MiniBatchKMeans(
        n_clusters=n_clusters,
        batch_size=batch_size,
        n_init=3,
        max_iter=100,
        random_state=42,
        verbose=0,
    )

    n_fit = 0
    for paper_ids, X in _embedding_chunks(chunk_rows=chunk_rows, sample_size=sample_size):
        km.partial_fit(X)
        n_fit += len(paper_ids)
        log.info("partial_fit: %d vectors (total %d)", len(paper_ids), n_fit)

    if n_fit == 0:
        return {"clustered": 0}

    log.info("assigning cluster labels in chunks...")
    n_written = 0
    for paper_ids, X in _embedding_chunks(chunk_rows=chunk_rows, sample_size=sample_size):
        labels = km.predict(X)
        payload = [[pid, int(c), "minibatch_kmeans_v1"] for pid, c in zip(paper_ids, labels, strict=True)]
        with ch_connect() as ch:
            ch.insert("paper_clusters", payload, column_names=["paper_id", "cluster_id", "algorithm"])
        n_written += len(payload)
        wait_for_ram()

    return {
        "clustered": n_written,
        "n_clusters": n_clusters,
        "elapsed_seconds": round(time.monotonic() - t0, 2),
    }
