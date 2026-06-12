# PRD: Author graph and disambiguation

## Goal

Turn author names into a durable, navigable author graph with better identity
resolution, richer author pages, and topic-aware discovery.

## Why this matters

The repo already has author-by-tag and by-id endpoints, but author identity is
only partially resolved. That limits exploration, makes author pages uneven, and
prevents the product from becoming a true research discovery surface.

## User problem

Researchers want to answer questions like:

- Who is publishing in this topic across venues?
- Which authors recur across clusters?
- Is this name the same person across sources?

If author identity is weak, those questions collapse into noisy name lists.

## Proposed solution

Build an author graph layer that links papers, canonical author identities, and
topic signals. Use arXiv/OpenAlex identifiers where available, and cluster by
name plus coauthor and venue context when they are not.

## Scope

In scope:

- Expand author resolution beyond the current top-paper refresh set.
- Add canonical author records with aliases and source provenance.
- Surface author pages with citations, tags, clusters, and recent papers.
- Add graph views for coauthor neighborhoods and topic overlap.

Out of scope:

- Manual identity curation at large scale.
- Social/profile features.
- Any requirement to be perfect on all historical records before launch.

## Success criteria

- Author pages load for most high-signal authors without obvious duplicates.
- Topic exploration can start from an author and fan out into papers and tags.
- The by-tag surface becomes a stepping stone into the author graph rather than
  a dead-end table.

## Risks

- Name collisions will remain for common surnames.
- High-quality disambiguation likely needs heuristic iteration.
- The graph can get noisy if provenance and confidence are not shown.

