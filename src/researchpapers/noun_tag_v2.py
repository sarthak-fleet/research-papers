"""spaCy v2 tagger: parser disabled, POS-only chunking, bulk DB writes.

The dependency parser eats ~60-70% of spaCy's CPU time. We don't actually need
parsed structure — only the POS tags. So we run a `tok2vec + tagger` pipeline
and extract noun-phrase candidates ourselves via a simple POS pattern match:

    (ADJ|NOUN|PROPN)+ ending with NOUN or PROPN

This matches "deep convolutional neural networks", "Adam optimizer",
"stochastic gradient descent", but not "the proposed" or "our model".

Expected: 3-5× faster than v1 on the same hardware.
"""

from __future__ import annotations

import logging
import time
from collections import Counter

import spacy

from researchpapers.config import Settings
from researchpapers.noun_tag import (
    BLACKLIST_PHRASE,
    BLACKLIST_SINGLE,
    _strip_leading,
)
from researchpapers.ram import m1_16gb_profile, pick_n_process, wait_for_ram

log = logging.getLogger("researchpapers.noun_tag_v2")

SPACY_MODEL = "en_core_web_sm"
DEFAULT_BATCH_PAPERS = m1_16gb_profile()["spacy_batch_papers"]
DEFAULT_MAX_PROCS = m1_16gb_profile()["spacy_max_procs"]


def _candidates_pos_only(doc) -> Counter:
    """Extract noun-phrase candidates via POS pattern, no dependency parsing."""
    from spacy.lang.en.stop_words import STOP_WORDS

    cnt: Counter[str] = Counter()
    n = len(doc)
    i = 0
    while i < n:
        if doc[i].pos_ in ("ADJ", "NOUN", "PROPN"):
            j = i
            while j < n and doc[j].pos_ in ("ADJ", "NOUN", "PROPN"):
                j += 1
            # Trim trailing ADJs — phrase must end with a noun
            end = j - 1
            while end >= i and doc[end].pos_ not in ("NOUN", "PROPN"):
                end -= 1
            if end > i:
                phrase = " ".join(doc[k].text for k in range(i, end + 1)).strip()
                cleaned = _strip_leading(phrase)
                n_words = len(cleaned.split())
                if 2 <= n_words <= 4:
                    if cleaned not in BLACKLIST_SINGLE and cleaned not in BLACKLIST_PHRASE:
                        tokens = cleaned.split()
                        if not all(t in BLACKLIST_SINGLE or t in STOP_WORDS for t in tokens):
                            if tokens[0] not in STOP_WORDS:
                                cnt[cleaned] += 1
            i = j
        else:
            i += 1

    # Proper nouns + capitalized acronyms.
    # Single PROPNs are noisy: in titles, spaCy frequently mis-tags ordinary nouns and
    # adjectives ("Deep", "Learning", "Network") as PROPN just because they're capitalized.
    # We keep singletons only if they have a clear "this is a real model/tool name" shape:
    #   - all uppercase + alphabetic + 2-8 chars (CNN, BERT, LLM, GPT)
    #   - OR mixed-case with internal capital after the first char (ImageNet, ResNet,
    #     PyTorch, OpenAI) or digits (GPT4, T5, Llama2)
    for tok in doc:
        t = tok.text
        n = len(t)
        if tok.pos_ == "PROPN" and 3 <= n <= 30:
            has_internal_upper_or_digit = any(c.isupper() or c.isdigit() for c in t[1:])
            if has_internal_upper_or_digit and t.lower() not in BLACKLIST_SINGLE:
                cnt[t] += 1
        elif t.isupper() and 2 <= n <= 8 and t.isalpha():
            cnt[t] += 1
    return cnt


def _fetch_untagged_chunk(*, source: str, batch_papers: int) -> list[tuple[str, str, str | None]]:
    from researchpapers.ch_db import connect as ch_connect

    with ch_connect() as ch:
        return ch.query(
            """
            SELECT p.paper_id, p.title, p.abstract
            FROM papers AS p FINAL
            WHERE p.source = %(source)s
              AND length(p.abstract) > 80
              AND p.paper_id NOT IN (
                SELECT paper_id FROM paper_tags FINAL WHERE tagger = 'spacy_v2'
              )
            ORDER BY p.paper_id
            LIMIT %(lim)s
            """,
            parameters={"source": source, "lim": batch_papers},
        ).result_rows


def tag_multi_source(
    *,
    source: str,
    batch_papers: int = DEFAULT_BATCH_PAPERS,
    limit: int | None = None,
    n_process: int | None = None,
    max_procs: int | None = None,
) -> dict[str, int | float]:
    """Run spaCy v2 on any source in ClickHouse. Streams untagged papers in chunks."""
    from researchpapers.ch_db import write_paper_tags

    wait_for_ram()
    log.info("loading spaCy %s with parser DISABLED", SPACY_MODEL)
    nlp = spacy.load(SPACY_MODEL, disable=["parser", "ner", "lemmatizer"])

    t0 = time.monotonic()
    total_tagged = 0
    total_skipped = 0
    batch_idx = 0
    cap = max_procs if max_procs is not None else DEFAULT_MAX_PROCS

    while True:
        if limit is not None and total_tagged >= limit:
            break
        take = batch_papers if limit is None else min(batch_papers, limit - total_tagged)
        chunk_rows = _fetch_untagged_chunk(source=source, batch_papers=take)
        if not chunk_rows:
            break

        batch_idx += 1
        n = n_process or pick_n_process(cap=cap)
        log.info(
            "batch #%d: %d papers, n_process=%d (running total tagged=%d)",
            batch_idx, len(chunk_rows), n, total_tagged,
        )
        chunk = [
            {"paper_id": r[0], "title": r[1], "abstract": r[2]}
            for r in chunk_rows
        ]
        texts = [f"{r['title']}\n\n{r['abstract']}" for r in chunk]
        results: list[list[str]] = []
        for doc in nlp.pipe(texts, batch_size=512, n_process=n):
            cnt = _candidates_pos_only(doc)
            results.append([t for t, _ in cnt.most_common(12)])

        ch_rows = [
            (r["paper_id"], "spacy_v2", tags, None)
            for r, tags in zip(chunk, results, strict=True)
        ]
        write_paper_tags(ch_rows, model_version="en_core_web_sm")
        total_tagged += len(chunk)
        total_skipped += sum(1 for r in results if not r)
        wait_for_ram()

    elapsed = time.monotonic() - t0
    return {
        "tagged": total_tagged,
        "skipped": total_skipped,
        "elapsed_seconds": round(elapsed, 2),
        "papers_per_sec": round(total_tagged / elapsed, 1) if elapsed else 0,
    }


def tag_papers(
    settings: Settings,
    *,
    limit: int | None = None,
    only_top_cited: bool = True,
    batch_papers: int | None = None,
    n_process: int | None = None,
    max_procs: int | None = None,
) -> dict[str, int | float]:
    """Tag the arxiv slice with spaCy v2. Thin wrapper around tag_multi_source.

    only_top_cited is ignored (kept for CLI back-compat) — CH ORDER BY against
    a half-billion-row table is wasted work for what's effectively a bulk tag pass.
    """
    return tag_multi_source(
        source="arxiv",
        limit=limit,
        batch_papers=batch_papers or DEFAULT_BATCH_PAPERS,
        n_process=n_process,
        max_procs=max_procs,
    )
