# PRD: ArXiv abstract refresh for contaminated OpenAlex records

## Goal

Repair the subset of arXiv records whose OpenAlex abstracts or related fields are
cross-contaminated with another paper's data.

## Why this matters

The repo already patches titles through `paper_metadata_v2`, but incorrect
abstracts still degrade semantic search, tag generation, and user trust. This is
especially visible on papers where search or clustering seems "close but wrong."

## User problem

Researchers searching by meaning expect summaries and tags to reflect the paper
they clicked. If the abstract is wrong, the whole downstream experience becomes
unreliable.

## Proposed solution

Add an arXiv refresh job that re-pulls abstracts and stable metadata for
suspect arXiv IDs, then writes the corrected fields into a new overlay table.

## Scope

In scope:

- Detect suspicious arXiv rows using mismatched titles, abstract anomalies, or
  known bad ID patterns.
- Re-fetch abstract text and stable metadata from arXiv.
- Store corrected values in a ClickHouse overlay table.
- Use corrected abstracts in search, tag generation, and paper detail views.

Out of scope:

- Rebuilding the entire ingestion pipeline.
- Rewriting every historical source record.
- Any model retraining unrelated to the corrected text.

## Success criteria

- Search results improve for known contaminated papers.
- The semantic search and tag surfaces no longer expose obviously wrong
  abstracts on refreshed records.
- Corrections can be rerun and diffed against the previous overlay snapshot.

## Risks

- arXiv API rate limits or transient errors.
- Incorrect detection could overwrite good data if the suspicion filter is too
  broad.
- Some records may not have a clean upstream abstract to recover.

