"""PageRank over the full citation graph via scipy.sparse.

Streams edges from ClickHouse in chunks to avoid holding the full edge list in
Python before matrix construction. Writes scores to paper_scores_v2 overlay.
"""

from __future__ import annotations

import logging
import time

import numpy as np
import scipy.sparse as sp

from researchpapers.ch_db import connect as ch_connect
from researchpapers.ram import wait_for_ram

log = logging.getLogger("researchpapers.pagerank_full")

EDGE_CHUNK = 250_000


def compute_and_write(damping: float = 0.85, max_iter: int = 50, tol: float = 1e-6) -> dict:
    wait_for_ram()
    t0 = time.monotonic()

    with ch_connect() as ch:
        log.info("loading papers (with openalex_id)...")
        papers = ch.query(
            "SELECT paper_id, openalex_id FROM papers FINAL WHERE length(openalex_id) > 0"
        ).result_rows
    n = len(papers)
    log.info("loaded %d papers", n)

    oa_to_idx = {p[1]: i for i, p in enumerate(papers)}
    paper_id_to_idx = {p[0]: i for i, p in enumerate(papers)}
    paper_id_by_idx = [p[0] for p in papers]

    rows: list[int] = []
    cols: list[int] = []
    matched = 0
    offset = 0
    with ch_connect() as ch:
        while True:
            chunk = ch.query(
                """
                SELECT citing_paper_id, cited_openalex_id
                FROM references_paper
                ORDER BY citing_paper_id, cited_openalex_id
                LIMIT %(lim)s OFFSET %(off)s
                """,
                parameters={"lim": EDGE_CHUNK, "off": offset},
            ).result_rows
            if not chunk:
                break
            for citing, cited_oa in chunk:
                src = paper_id_to_idx.get(citing)
                dst = oa_to_idx.get(cited_oa)
                if src is not None and dst is not None and src != dst:
                    rows.append(src)
                    cols.append(dst)
                    matched += 1
            offset += len(chunk)
            if len(chunk) < EDGE_CHUNK:
                break
            if offset % (EDGE_CHUNK * 4) == 0:
                log.info("streamed %d edges (%d matched)", offset, matched)

    log.info("loaded %d edges, matched %d in-corpus", offset, matched)
    if matched == 0:
        return {"computed": 0, "error": "no edges matched"}

    data = np.ones(matched, dtype=np.float32)
    A = sp.coo_matrix((data, (rows, cols)), shape=(n, n)).tocsr()
    del rows, cols, data

    out_deg = np.array(A.sum(axis=1)).ravel()
    dangling = out_deg == 0
    out_deg[dangling] = 1.0
    D_inv = sp.diags(1.0 / out_deg)
    M = (A.T @ D_inv).astype(np.float32)
    del A, D_inv

    log.info("running power iteration (max %d iters, tol %.0e)...", max_iter, tol)
    pr = np.ones(n, dtype=np.float32) / n
    teleport = np.ones(n, dtype=np.float32) / n
    for i in range(max_iter):
        dangling_mass = pr[dangling].sum()
        pr_new = damping * (M @ pr + dangling_mass / n) + (1 - damping) * teleport
        diff = np.abs(pr_new - pr).sum()
        pr = pr_new
        if i % 10 == 0:
            log.info("  iter %d, L1 diff = %.6f", i, float(diff))
        if diff < tol:
            log.info("converged at iter %d", i)
            break

    pr = pr / pr.sum()
    log.info("PR range: min=%.2e max=%.2e mean=%.2e", pr.min(), pr.max(), pr.mean())

    log.info("writing %d pagerank scores to paper_scores_v2...", n)
    with ch_connect() as ch:
        ch.command("""
            CREATE TABLE IF NOT EXISTS paper_scores_v2 (
              paper_id String,
              pagerank Float64,
              computed_at DateTime DEFAULT now()
            )
            ENGINE = ReplacingMergeTree(computed_at)
            ORDER BY paper_id
        """)
    payload = [[paper_id_by_idx[i], float(pr[i])] for i in range(n)]
    BATCH = 10000
    with ch_connect() as ch:
        for start in range(0, n, BATCH):
            ch.insert(
                "paper_scores_v2",
                payload[start : start + BATCH],
                column_names=["paper_id", "pagerank"],
            )

    return {
        "computed": n,
        "edges": matched,
        "iters": i + 1,
        "elapsed_seconds": round(time.monotonic() - t0, 2),
    }
