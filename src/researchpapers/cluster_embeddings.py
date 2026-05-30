"""Cluster the embedding space with MiniBatchKMeans.

HDBSCAN is O(n²) and too slow on 478k vectors. MiniBatchKMeans scales linearly
and gives stable cluster IDs we can index and surface in the dashboard.

Output → CH paper_clusters (paper_id, cluster_id). Then ch_exports surfaces
top tags + sample papers per cluster.
"""

from __future__ import annotations

import logging
import time

import numpy as np

from researchpapers.ch_db import connect as ch_connect

log = logging.getLogger("researchpapers.cluster")


def cluster_papers(n_clusters: int = 64, batch_size: int = 4096, sample_size: int | None = None) -> dict:
    from sklearn.cluster import MiniBatchKMeans

    t0 = time.monotonic()
    with ch_connect() as ch:
        log.info("loading embeddings...")
        rows = ch.query(
            "SELECT paper_id, embedding FROM paper_embeddings FINAL"
            + (f" LIMIT {int(sample_size)}" if sample_size else "")
        ).result_rows
    n = len(rows)
    log.info("loaded %d embeddings", n)
    if not rows:
        return {"clustered": 0}

    paper_ids = [r[0] for r in rows]
    X = np.array([r[1] for r in rows], dtype=np.float32)
    log.info("matrix shape: %s", X.shape)

    log.info("fitting MiniBatchKMeans (k=%d, batch=%d)...", n_clusters, batch_size)
    t_fit = time.monotonic()
    km = MiniBatchKMeans(
        n_clusters=n_clusters,
        batch_size=batch_size,
        n_init=3,
        max_iter=100,
        random_state=42,
        verbose=0,
    )
    labels = km.fit_predict(X)
    log.info("fit done in %.1fs, inertia=%.1f", time.monotonic() - t_fit, km.inertia_)

    cluster_sizes = np.bincount(labels, minlength=n_clusters)
    log.info("cluster size distribution: min=%d, max=%d, mean=%.0f",
             cluster_sizes.min(), cluster_sizes.max(), cluster_sizes.mean())

    payload = [[pid, int(c), "minibatch_kmeans_v1"] for pid, c in zip(paper_ids, labels.tolist(), strict=True)]
    log.info("writing %d rows to paper_clusters...", len(payload))
    with ch_connect() as ch:
        ch.insert("paper_clusters", payload, column_names=["paper_id", "cluster_id", "algorithm"])
    return {
        "clustered": n,
        "n_clusters": n_clusters,
        "elapsed_seconds": round(time.monotonic() - t0, 2),
    }
