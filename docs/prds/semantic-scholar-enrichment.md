# PRD: Semantic Scholar enrichment for top papers

## Goal

Reduce citation undercount and improve ranking quality for the most important
papers by enriching the corpus with Semantic Scholar citation data.

## Why this matters

The current corpus already surfaces citation-heavy papers, but OpenAlex
undercounts some influential preprints and older works. That creates visible
rank-order errors in hot lists, sleepers, and search result prioritization.

## User problem

Researchers using the dashboard need the most important papers to appear where
they expect them. If citation counts are too low, the platform loses trust on
high-signal surfaces and misses strong long-tail papers.

## Proposed solution

Add a `Semantic Scholar /paper/batch` enrichment job for the top-cited and most
viewed papers, then store the enriched citation counts and metadata in a small
overlay table.

## Scope

In scope:

- Enrich the top 1k to 10k papers by citation count and recency.
- Persist Semantic Scholar citation counts and identifiers in ClickHouse.
- Prefer enriched citation counts in ranking surfaces when present.
- Show provenance so users can see when a value came from Semantic Scholar.

Out of scope:

- Full-corpus Semantic Scholar backfill.
- Write paths or user-editable metadata.
- Any ranking model beyond citation-count correction.

## Success criteria

- Known citation-heavy papers move closer to expected rank order.
- Hot and top-cited lists show fewer obvious undercount artifacts.
- Enrichment can be rerun idempotently without manual cleanup.

## Risks

- Semantic Scholar coverage may vary by source and paper age.
- Batch limits or API latency may make large backfills expensive.
- Enriched numbers should never silently replace source data without provenance.

