import * as React from "react";

import { Badge } from "@/components/ui/badge";

type Result = {
  paper_id: string;
  source: string;
  title: string;
  abstract_preview: string;
  submitted_date: string | null;
  citation_count: number;
  arxiv_id: string | null;
  similarity: number;
};

// Resolve API base in this priority:
//   1. PUBLIC_API_URL build-time env (Cloudflare Pages / Vercel)
//   2. window.__API_BASE__ runtime override (set via /api-config.js if present)
//   3. Empty string: static deployed demo mode over bundled JSON exports
const API_BASE: string =
  (import.meta.env.PUBLIC_API_URL as string | undefined) ??
  (typeof window !== "undefined" && (window as any).__API_BASE__) ??
  "";

type StaticPaper = {
  paper_id?: string;
  arxiv_id?: string;
  source?: string;
  title?: string;
  submitted_date?: string | null;
  citation_count?: number | null;
  topic_tags?: string[];
  top_keywords?: string[];
  venue?: string;
  decision?: string;
  avg_rating?: number | null;
};

function paperUrl(paper_id: string, arxiv_id: string | null): string {
  if (arxiv_id) return `https://arxiv.org/abs/${arxiv_id}`;
  if (paper_id.startsWith("arxiv:")) return `https://arxiv.org/abs/${paper_id.replace("arxiv:", "")}`;
  if (paper_id.startsWith("openreview:")) return `https://openreview.net/forum?id=${paper_id.replace("openreview:", "")}`;
  return "#";
}

function textScore(query: string, row: StaticPaper): number {
  const tokens = query.toLowerCase().split(/\s+/).filter((token) => token.length > 2);
  const haystack = [
    row.title,
    row.source,
    row.venue,
    row.decision,
    ...(row.topic_tags ?? []),
    ...(row.top_keywords ?? []),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  let score = 0;
  for (const token of tokens) {
    if (haystack.includes(token)) score += token.length;
  }
  if (row.title?.toLowerCase().includes(query.toLowerCase())) score += 20;
  score += Math.log1p(Number(row.citation_count ?? 0)) / 4;
  if (row.avg_rating) score += Number(row.avg_rating) / 3;
  return score;
}

async function staticSearch(query: string): Promise<Result[]> {
  const [topPapers, hot, sleepers, reviewed] = await Promise.all([
    fetch("/data/top_papers.json").then((r) => r.json()),
    fetch("/data/hot.json").then((r) => r.json()),
    fetch("/data/sleepers.json").then((r) => r.json()),
    fetch("/data/review_top_papers.json").then((r) => r.json()),
  ]) as [StaticPaper[], StaticPaper[], StaticPaper[], StaticPaper[]];
  const byId = new Map<string, StaticPaper>();
  for (const row of [...topPapers, ...hot, ...sleepers, ...reviewed]) {
    const paperId = row.paper_id ?? (row.arxiv_id ? `arxiv:${row.arxiv_id}` : row.title);
    if (paperId && !byId.has(paperId)) byId.set(paperId, row);
  }
  return [...byId.values()]
    .map((row) => ({ row, score: textScore(query, row) }))
    .filter(({ score }) => score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 15)
    .map(({ row, score }) => {
      const paperId = row.paper_id ?? (row.arxiv_id ? `arxiv:${row.arxiv_id}` : row.title ?? "paper");
      const arxivId = row.arxiv_id ?? (paperId?.startsWith("arxiv:") ? paperId.replace("arxiv:", "") : null);
      const details = [
        row.venue,
        row.decision,
        row.topic_tags?.slice(0, 4).join(", "),
        row.top_keywords?.slice(0, 4).join(", "),
      ].filter(Boolean).join(" · ");
      return {
        paper_id: paperId,
        source: row.source ?? (paperId?.startsWith("openreview:") ? "openreview" : "static"),
        title: row.title ?? paperId,
        abstract_preview: details || "Bundled researchPapers signal from the deployed static export.",
        submitted_date: row.submitted_date ?? null,
        citation_count: Number(row.citation_count ?? 0),
        arxiv_id: arxivId,
        similarity: Math.min(0.999, score / 40),
      };
    });
}

export function SemanticSearch() {
  const [q, setQ] = React.useState("");
  const [results, setResults] = React.useState<Result[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [didSearch, setDidSearch] = React.useState(false);

  const run = React.useCallback(async (query: string) => {
    if (query.length < 3) return;
    setLoading(true);
    setError(null);
    setDidSearch(true);
    try {
      if (API_BASE) {
        const r = await fetch(`${API_BASE}/semantic-search?q=${encodeURIComponent(query)}&limit=15`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = await r.json();
        setResults(data.results || []);
      } else {
        setResults(await staticSearch(query));
      }
    } catch (e: unknown) {
      setError(e?.message || "request failed");
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, []);

  return (
    <div class="space-y-4">
      <form
        onSubmit={(e) => { e.preventDefault(); run(q); }}
        class="flex gap-2"
      >
        <input
          type="text"
          value={q}
          onInput={(e) => setQ((e.target as HTMLInputElement).value)}
          placeholder="Search the corpus by meaning — e.g. 'emergent capabilities in language models'"
          class="flex-1 rounded-lg border bg-card px-4 py-3 text-sm outline-none focus:ring-2 focus:ring-primary/50 placeholder:text-muted-foreground/60"
        />
        <button
          type="submit"
          disabled={loading || q.length < 3}
          class="px-5 py-3 rounded-lg bg-primary text-primary-foreground text-sm font-medium disabled:opacity-50 hover:opacity-90 transition-opacity"
        >
          {loading ? "Searching..." : "Search"}
        </button>
      </form>

      {error && <div class="text-sm text-destructive">Error: {error}</div>}

      {didSearch && !loading && results.length === 0 && !error && (
        <div class="text-sm text-muted-foreground">No matches in the deployed demo slice. Try a broader topic.</div>
      )}

      {results.length > 0 && (
        <div class="space-y-2">
          {results.map((r) => (
            <a
              key={r.paper_id}
              href={paperUrl(r.paper_id, r.arxiv_id)}
              target="_blank"
              rel="noopener"
              class="block rounded-lg border bg-card p-3 hover:bg-muted/40 transition-colors"
            >
              <div class="flex items-center gap-2 text-xs mb-1">
                <span class="tabular-nums text-primary font-semibold">{r.similarity.toFixed(3)}</span>
                <Badge variant="outline" class="font-mono text-[10px]">{r.source}</Badge>
                {r.citation_count > 0 && (
                  <span class="tabular-nums text-muted-foreground">{r.citation_count.toLocaleString()} cites</span>
                )}
                {r.submitted_date && (
                  <span class="text-muted-foreground tabular-nums">{r.submitted_date.slice(0, 4)}</span>
                )}
              </div>
              <div class="text-sm text-foreground/90 mb-1">{r.title}</div>
              <div class="text-xs text-muted-foreground line-clamp-2">{r.abstract_preview}</div>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
