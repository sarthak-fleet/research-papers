# Retro: RAM-Aware Pipeline for 16 GB M1

**Date:** 2026-06-13
**Scope:** Commit "Add RAM-aware pipeline for 16 GB hosts and lean API mode."

---

## What happened

Running the full pipeline (embed 478k papers → cluster → spaCy tag → MLX tag → PageRank) on an
M1 Pro 16 GB machine with a browser, IDE, and Docker open caused OOMs and stalled jobs. The
batch sizes and worker counts from the initial implementation were calibrated for a machine with
more headroom.

The fix introduced `ram.py` as a shared helper module used by every heavy pipeline job:
- `wait_for_ram()`: blocks until `free + inactive + speculative` pages total ≥ 3.5 GB.
- `clamp_batch_size()`: reduces encode batch size dynamically based on current free RAM.
- `pick_n_process()`: calculates spaCy worker count as `min(cap, budget_MB / 1500)`.
- `m1_16gb_profile()`: named defaults tuned for the target machine.

The FastAPI server also gained `--lean` mode: semantic-search query encoding is offloaded to a
one-shot subprocess (`encode_query.py`), saving ~400 MB RSS in the API process.

## What went well

- A single `ram.py` module centralises all memory-pressure logic. Each pipeline job imports
  `wait_for_ram` / `clamp_batch_size` / `pick_n_process` rather than rolling its own sleep loops.
- macOS `vm_stat` parsing correctly accounts for inactive and speculative pages (which the OS
  reclaims on demand), giving a more accurate "available" figure than just "free pages".
- The MLX tagger gained a separate `_ram_throttle()` (also using `vm_stat`) that runs every 5
  seconds during inference, pausing the GPU when free RAM drops below 3 GB.

## What was hard

- Batch size defaults (embed: 256, spaCy: 25000 papers, cluster: load-all-478k) all had to be
  audited and reduced. There was no single place to change them.
- The MLX tagger keeps the model resident throughout the run; there is no way to unload it
  between groups without paying the cold-start cost again. The only lever is shard size.
- The lean API mode adds ~0.5–1s per semantic-search call (subprocess spawn + model cold-start).
  This is acceptable interactively but would be unacceptable at >1 request/sec load.

## Lessons

- See [lessons.md](../lessons.md): "Batch size must be clamped dynamically", "Cold-start is
  one-time per run", "RAM throttle is necessary during concurrent workloads".
