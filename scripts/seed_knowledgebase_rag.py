#!/usr/bin/env python3
"""Seed the Knowledgebase RAG Worker from researchPapers static exports.

This intentionally seeds a representative website slice, not the full 488k
paper corpus. It uses the existing exported JSON under web/public/data so it
does not touch ClickHouse or run any corpus ingest jobs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "web" / "public" / "data"
DEFAULT_BASE_URL = "https://knowledgebase.sarthakagrawal927.workers.dev"
DEFAULT_DOMAIN = "research-papers"


def load_json(name: str) -> Any:
    return json.loads((DATA_DIR / name).read_text())


def paper_url(paper_id: str | None = None, arxiv_id: str | None = None) -> str | None:
    if arxiv_id:
        return f"https://arxiv.org/abs/{arxiv_id}"
    if paper_id and paper_id.startswith("arxiv:"):
        return f"https://arxiv.org/abs/{paper_id.removeprefix('arxiv:')}"
    if paper_id and paper_id.startswith("openreview:"):
        return f"https://openreview.net/forum?id={paper_id.removeprefix('openreview:')}"
    return None


def compact_paper(row: dict[str, Any], *, collection: str) -> dict[str, Any]:
    paper_id = row.get("paper_id") or (
        f"arxiv:{row['arxiv_id']}" if row.get("arxiv_id") else None
    )
    title = str(row.get("title") or row.get("anchor_title") or "").strip()
    return {
        "record_kind": "paper_signal",
        "collection": collection,
        "paper_id": paper_id,
        "arxiv_id": row.get("arxiv_id"),
        "source": row.get("source") or ("arxiv" if row.get("arxiv_id") else None),
        "title": title,
        "url": paper_url(paper_id, row.get("arxiv_id")),
        "submitted_date": row.get("submitted_date"),
        "year": row.get("year"),
        "citation_count": row.get("citation_count"),
        "cites_per_year": row.get("cites_per_year"),
        "pagerank": row.get("pagerank") or row.get("pagerank_score"),
        "katz_score": row.get("katz_score"),
        "avg_rating": row.get("avg_rating"),
        "n_reviews": row.get("n_reviews"),
        "venue": row.get("venue"),
        "decision": row.get("decision"),
        "primary_category": row.get("primary_category"),
        "topic_tags": row.get("topic_tags") or [],
        "top_keywords": row.get("top_keywords") or [],
        "summary": " | ".join(
            part
            for part in [
                f"{collection} paper",
                title,
                f"{row.get('citation_count')} citations" if row.get("citation_count") is not None else "",
                f"rating {row.get('avg_rating')}" if row.get("avg_rating") is not None else "",
                f"venue {row.get('venue')}" if row.get("venue") else "",
            ]
            if part
        ),
    }


def cluster_record(row: dict[str, Any], *, collection: str) -> dict[str, Any]:
    top_tags = row.get("top_tags") or []
    tags = [
        str(item.get("tag") if isinstance(item, dict) else item)
        for item in top_tags[:12]
    ]
    top_papers = row.get("top_papers") or []
    return {
        "record_kind": "cluster",
        "collection": collection,
        "cluster_id": row.get("id"),
        "size": row.get("size"),
        "title": f"{collection} cluster {row.get('id')}",
        "labels": row.get("labels") or tags,
        "top_papers": [
            {
                "paper_id": p.get("paper_id") or (
                    f"arxiv:{p['arxiv_id']}" if p.get("arxiv_id") else None
                ),
                "title": p.get("title"),
                "citation_count": p.get("citation_count"),
            }
            for p in top_papers[:8]
        ],
        "summary": (
            f"{collection} cluster {row.get('id')} contains {row.get('size')} papers. "
            f"Top labels: {', '.join((row.get('labels') or tags)[:8])}. "
            f"Representative papers: "
            f"{'; '.join(str(p.get('title')) for p in top_papers[:5] if p.get('title'))}."
        ),
    }


def tag_record(row: dict[str, Any]) -> dict[str, Any]:
    samples = row.get("samples") or []
    return {
        "record_kind": "tag_rating",
        "collection": "tag_rating",
        "tag": row.get("tag"),
        "title": f"Tag rating: {row.get('tag')}",
        "mean_rating": row.get("mean_rating"),
        "p90_rating": row.get("p90_rating"),
        "n_papers": row.get("n_papers"),
        "sample_papers": [
            {
                "paper_id": sample.get("paper_id"),
                "title": sample.get("title"),
                "avg_rating": sample.get("avg_rating"),
                "venue": sample.get("venue"),
            }
            for sample in samples[:6]
        ],
        "summary": (
            f"Tag {row.get('tag')} has mean OpenReview rating {row.get('mean_rating')} "
            f"over {row.get('n_papers')} papers. Examples: "
            f"{'; '.join(str(s.get('title')) for s in samples[:4] if s.get('title'))}."
        ),
    }


def build_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    records.extend(compact_paper(row, collection="top_papers") for row in load_json("top_papers.json")[:200])
    records.extend(compact_paper(row, collection="hot") for row in load_json("hot.json")[:100])
    records.extend(compact_paper(row, collection="sleepers") for row in load_json("sleepers.json")[:100])
    records.extend(
        compact_paper(row, collection="top_reviewed")
        for row in load_json("review_top_papers.json")[:200]
    )
    records.extend(
        cluster_record(row, collection="embedding")
        for row in load_json("embedding_clusters.json")[:64]
    )
    records.extend(
        cluster_record(row, collection="abstract")
        for row in load_json("abstract_clusters.json")[:25]
    )
    records.extend(tag_record(row) for row in load_json("tag_rating.json")[:100])
    return records


def chunks(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def post_with_retries(
    client: httpx.Client,
    url: str,
    *,
    headers: dict[str, str],
    json_body: dict[str, Any],
    attempts: int,
) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            resp = client.post(url, headers=headers, json=json_body)
            if resp.status_code in {429, 500, 502, 503, 504} and attempt < attempts:
                sleep_s = min(2 ** attempt, 20)
                print(
                    f"retrying HTTP {resp.status_code} in {sleep_s}s "
                    f"(attempt {attempt}/{attempts})",
                    flush=True,
                )
                time.sleep(sleep_s)
                continue
            return resp
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            last_error = exc
            if attempt >= attempts:
                raise
            sleep_s = min(2 ** attempt, 20)
            print(
                f"retrying {type(exc).__name__} in {sleep_s}s "
                f"(attempt {attempt}/{attempts})",
                flush=True,
            )
            time.sleep(sleep_s)
    if last_error:
        raise last_error
    raise RuntimeError("unreachable retry state")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("RAG_SERVICE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--domain", default=os.environ.get("RAG_DOMAIN", DEFAULT_DOMAIN))
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    records = build_records()
    print(f"prepared {len(records)} records for domain={args.domain}")
    if args.out:
        args.out.write_text(json.dumps(records, indent=2))
        print(f"wrote {args.out}")
    if args.dry_run:
        return 0

    key = os.environ.get("RAG_SERVICE_KEY")
    if not key:
        print("RAG_SERVICE_KEY is required for live seed", file=sys.stderr)
        return 2

    base_url = args.base_url.rstrip("/")
    with httpx.Client(timeout=args.timeout) as client:
        domain_resp = post_with_retries(
            client,
            f"{base_url}/v1/kb/domains",
            headers={"Authorization": f"Bearer {key}"},
            json_body={
                "name": args.domain,
                "description": "researchPapers website seed: papers, clusters, ratings, hot/sleeper signals.",
            },
            attempts=args.retries,
        )
        if domain_resp.status_code not in {200, 201, 409}:
            domain_resp.raise_for_status()

        total_chunks = 0
        for index, batch in enumerate(chunks(records, args.batch_size), start=1):
            resp = post_with_retries(
                client,
                f"{base_url}/v1/kb/ingest/record",
                headers={"Authorization": f"Bearer {key}"},
                json_body={
                    "domain": args.domain,
                    "type": "PaperSignal",
                    "data": batch,
                    "idempotency_key": f"research-papers-static-v1-{index}",
                },
                attempts=args.retries,
            )
            resp.raise_for_status()
            body = resp.json()
            chunks_indexed = int(body.get("chunks_indexed") or 0)
            total_chunks += chunks_indexed
            print(
                f"batch {index}: records={len(batch)} "
                f"chunks_indexed={chunks_indexed} file_id={body.get('file_id')}"
                f"{' idempotent' if body.get('idempotent_replay') else ''}"
                ,
                flush=True,
            )
            time.sleep(0.25)
    print(f"seed complete: records={len(records)} chunks_indexed={total_chunks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
