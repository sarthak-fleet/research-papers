"""RAM-aware helpers for running heavy jobs on memory-constrained hosts (e.g. 16 GB M1).

Jobs call wait_for_ram() before loading models and use pick_n_process() /
clamp_batch_size() to stay inside a budget while other apps are running.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time

log = logging.getLogger("researchpapers.ram")

PAGE_SIZE = 4096

# Tuned for M1 Pro 16 GB with ~6 GB reserved for OS + browser + IDE.
DEFAULT_RESERVED_MB = 6000
DEFAULT_MIN_FREE_MB = 3500
DEFAULT_WAIT_TIMEOUT_SEC = 600

# Per-worker RSS observed at steady state (spaCy sm, parser disabled).
SPACY_WORKER_RSS_MB = 1500
EMBED_BATCH_RAM_MB = 4  # rough MB per paper in a encode batch (text + tensor)


def free_ram_mb() -> int:
    """Best-effort free RAM in MB. macOS: free + inactive + speculative pages."""
    if sys_platform_darwin():
        try:
            out = subprocess.check_output(["vm_stat"], text=True, timeout=2)
        except Exception:
            return 4096
        pages = {"free": 0, "inactive": 0, "speculative": 0}
        for line in out.splitlines():
            if "Pages free" in line:
                pages["free"] = int(line.rsplit(maxsplit=1)[-1].rstrip("."))
            elif "Pages inactive" in line:
                pages["inactive"] = int(line.rsplit(maxsplit=1)[-1].rstrip("."))
            elif "Pages speculative" in line:
                pages["speculative"] = int(line.rsplit(maxsplit=1)[-1].rstrip("."))
        return sum(pages.values()) * PAGE_SIZE // (1024 * 1024)

    # Linux: MemAvailable from /proc/meminfo
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass
    return 4096


def sys_platform_darwin() -> bool:
    import sys

    return sys.platform == "darwin"


def cpu_count() -> int:
    return os.cpu_count() or 4


def wait_for_ram(
    min_free_mb: int = DEFAULT_MIN_FREE_MB,
    *,
    timeout_sec: int = DEFAULT_WAIT_TIMEOUT_SEC,
    poll_sec: float = 5.0,
) -> int:
    """Block until at least min_free_mb is available. Returns free MB when ready."""
    deadline = time.monotonic() + timeout_sec
    while True:
        free_mb = free_ram_mb()
        if free_mb >= min_free_mb:
            return free_mb
        if time.monotonic() >= deadline:
            log.warning(
                "RAM wait timed out: free=%d MB < %d MB; proceeding anyway",
                free_mb,
                min_free_mb,
            )
            return free_mb
        log.info("waiting for RAM: free=%d MB need=%d MB", free_mb, min_free_mb)
        time.sleep(poll_sec)


def pick_n_process(
    *,
    worker_rss_mb: int = SPACY_WORKER_RSS_MB,
    cap: int | None = None,
    reserved_mb: int = DEFAULT_RESERVED_MB,
) -> int:
    """RAM-aware worker count for spaCy multiprocessing."""
    cap = cap or min(4, max(1, cpu_count() - 1))
    free_mb = free_ram_mb()
    budget = max(0, free_mb - reserved_mb)
    n = max(1, min(cap, budget // worker_rss_mb))
    log.info("RAM picker: free=%d MB budget=%d MB → n_process=%d (cap=%d)", free_mb, budget, n, cap)
    return int(n)


def clamp_batch_size(
    requested: int,
    *,
    per_item_mb: float = EMBED_BATCH_RAM_MB,
    reserved_mb: int = DEFAULT_RESERVED_MB,
    floor: int = 8,
) -> int:
    """Shrink a batch size to fit available RAM."""
    free_mb = free_ram_mb()
    budget = max(0, free_mb - reserved_mb)
    max_batch = int(budget / per_item_mb) if per_item_mb > 0 else requested
    out = max(floor, min(requested, max_batch))
    if out < requested:
        log.info("RAM clamp: batch %d → %d (free=%d MB)", requested, out, free_mb)
    return out


def m1_16gb_profile() -> dict[str, int]:
    """Conservative defaults for M1 Pro 16 GB with other apps running."""
    return {
        "embed_batch_size": 64,
        "spacy_batch_papers": 3000,
        "spacy_max_procs": 2,
        "cluster_batch_size": 2048,
        "cluster_chunk_rows": 20000,
        "metadata_limit": 10000,
        "enrich_limit": 10000,
        "abstract_detect_limit": 5000,
        "reserved_mb": DEFAULT_RESERVED_MB,
        "min_free_mb": DEFAULT_MIN_FREE_MB,
    }
