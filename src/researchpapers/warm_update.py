"""One-command overlay refresh for memory-constrained hosts.

Runs enrichment jobs sequentially with RAM waits between steps so a 16 GB M1
can refresh citations, abstracts, author graph, and static exports without
peaking multiple model loads at once.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from researchpapers.ch_db import ping as ch_ping
from researchpapers.config import PROJECT_ROOT, load_settings
from researchpapers.ram import m1_16gb_profile, wait_for_ram

log = logging.getLogger("researchpapers.warm_update")


def run_warm_update(
    *,
    build_web: bool = False,
    skip_enrich: bool = False,
    skip_abstracts: bool = False,
    skip_author_graph: bool = False,
    profile: dict[str, int] | None = None,
) -> dict[str, object]:
    """Sequential overlay refresh tuned for 16 GB RAM."""
    if not ch_ping():
        raise RuntimeError("ClickHouse is not reachable on localhost:8123 — start with: docker compose up -d clickhouse")

    settings = load_settings()
    p = profile or m1_16gb_profile()
    results: dict[str, object] = {"profile": p}

    def _step(name: str, fn) -> None:
        wait_for_ram(p["min_free_mb"])
        log.info("=== %s ===", name)
        results[name] = fn()

    if not skip_enrich:
        from researchpapers import semantic_scholar_enrichment

        def enrich():
            return semantic_scholar_enrichment.enrich_top_papers(
                limit=p["enrich_limit"],
                settings=settings,
            )

        _step("enrich_citations", enrich)

    if not skip_abstracts:
        from researchpapers import arxiv_abstract_refresh

        def refresh():
            return arxiv_abstract_refresh.refresh_suspect_abstracts(
                detect_limit=p["abstract_detect_limit"],
                reembed=True,
            )

        _step("refresh_abstracts", refresh)

    if not skip_author_graph:
        from researchpapers import author_graph

        def graph():
            return author_graph.build_author_graph(expand_metadata_limit=p["metadata_limit"])

        _step("build_author_graph", graph)

    wait_for_ram(p["min_free_mb"])

    from researchpapers import ch_exports, exporter

    out_dir = PROJECT_ROOT / "web" / "public" / "data"
    ch_paths = ch_exports.export_review_data(out_dir)
    json_paths = exporter.export_all(settings, out_dir)
    results["exports"] = [str(x) for x in ch_paths + json_paths]
    log.info("exported %d JSON files", len(results["exports"]))

    if build_web:
        wait_for_ram(p["min_free_mb"])
        web_dir = PROJECT_ROOT / "web"
        log.info("building Astro site...")
        r = subprocess.run(["npm", "run", "build"], cwd=str(web_dir), capture_output=True, text=True)
        if r.returncode != 0:
            log.error("npm build failed:\n%s", r.stderr)
            raise RuntimeError("web build failed")
        results["web_dist"] = str(web_dir / "dist")

    return results
