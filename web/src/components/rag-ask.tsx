import * as React from "react";
import { Loader2, MessageSquareText } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

type Citation = {
  chunk_id: string;
  document_id?: string;
  filename?: string | null;
  excerpt?: string;
  score?: number;
};

type RagResult = {
  answer: string;
  citations: Citation[];
  trace_id?: string | null;
  route?: string | null;
  answer_mode?: string | null;
};

type StaticPaper = {
  paper_id?: string;
  arxiv_id?: string;
  title?: string;
  citation_count?: number;
  cites_per_year?: number;
  hotness?: number;
  avg_rating?: number;
  n_reviews?: number;
  venue?: string;
  decision?: string;
  submitted_date?: string;
  primary_category?: string;
  topic_tags?: string[];
  top_keywords?: string[];
};

type StaticCluster = {
  id: number;
  size: number;
  top_tags?: Array<{ tag: string; n: number }>;
  top_papers?: StaticPaper[];
};

type StaticTagRating = {
  tag: string;
  mean_rating: number;
  p90_rating?: number;
  n_papers: number;
  samples?: StaticPaper[];
};

type Evidence = {
  id: string;
  collection: string;
  title: string;
  excerpt: string;
  score: number;
};

const API_BASE: string =
  (import.meta.env.PUBLIC_API_URL as string | undefined) ??
  (typeof window !== "undefined" && (window as any).__API_BASE__) ??
  "";

function ragEndpoint(): string {
  if (API_BASE) return `${API_BASE}/rag/query`;
  return "/api/rag/query";
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Could not load ${path}`);
  return response.json() as Promise<T>;
}

function paperId(paper: StaticPaper): string {
  return paper.paper_id ?? (paper.arxiv_id ? `arxiv:${paper.arxiv_id}` : paper.title ?? "paper");
}

function paperMeta(paper: StaticPaper): string {
  const parts = [
    paper.venue,
    paper.decision,
    typeof paper.avg_rating === "number" ? `rating ${paper.avg_rating.toFixed(1)}` : null,
    typeof paper.citation_count === "number" ? `${paper.citation_count.toLocaleString()} citations` : null,
    typeof paper.cites_per_year === "number" ? `${paper.cites_per_year.toFixed(1)} cites/year` : null,
    paper.submitted_date,
  ];
  return parts.filter(Boolean).join(" | ");
}

function tokens(value: string): string[] {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, " ")
    .split(/\s+/)
    .filter((token) => token.length > 2);
}

function matchScore(questionTerms: string[], text: string, boost = 0): number {
  const haystack = text.toLowerCase();
  const termScore = questionTerms.reduce(
    (score, term) => score + (haystack.includes(term) ? 1 : 0),
    0,
  );
  return termScore + boost;
}

function paperEvidence(collection: string, paper: StaticPaper, boost = 0): Evidence {
  const title = paper.title ?? paperId(paper);
  const meta = paperMeta(paper);
  const tags = [...(paper.topic_tags ?? []), ...(paper.top_keywords ?? [])].slice(0, 5);
  const excerpt = [title, meta, tags.length ? `Signals: ${tags.join(", ")}` : null]
    .filter(Boolean)
    .join(". ");
  return {
    id: paperId(paper),
    collection,
    title,
    excerpt,
    score: boost,
  };
}

function summarizeEvidence(evidence: Evidence[]): string {
  const lines = evidence.slice(0, 5).map((item, index) => {
    const source = item.collection.replace(/_/g, " ");
    return `${index + 1}. ${item.title} (${source}): ${item.excerpt}`;
  });
  return [
    "Based on the deployed research-paper data, the strongest signals are:",
    ...lines,
    "",
    "This answer is served from the bundled demo index when the live Knowledgebase RAG service is unavailable. The same UI switches to the full server RAG path when the service key is configured.",
  ].join("\n");
}

async function staticDemoAnswer(question: string): Promise<RagResult> {
  const [hot, sleepers, reviewTop, topPapers, clusters, tagRatings] = await Promise.all([
    getJson<StaticPaper[]>("/data/hot.json"),
    getJson<StaticPaper[]>("/data/sleepers.json"),
    getJson<StaticPaper[]>("/data/review_top_papers.json"),
    getJson<StaticPaper[]>("/data/top_papers.json"),
    getJson<StaticCluster[]>("/data/embedding_clusters.json"),
    getJson<StaticTagRating[]>("/data/tag_rating.json"),
  ]);

  const questionTerms = tokens(question);
  const evidence: Evidence[] = [
    ...hot.slice(0, 40).map((paper) => paperEvidence("hot_papers", paper, paper.hotness ?? 0)),
    ...sleepers
      .slice(0, 40)
      .map((paper) => paperEvidence("sleepers", paper, (paper.avg_rating ?? 0) / 2)),
    ...reviewTop
      .slice(0, 40)
      .map((paper) => paperEvidence("openreview_top_rated", paper, (paper.avg_rating ?? 0) / 2)),
    ...topPapers
      .slice(0, 40)
      .map((paper) =>
        paperEvidence("citation_graph", paper, Math.min((paper.cites_per_year ?? 0) / 500, 3)),
      ),
    ...clusters.slice(0, 40).map((cluster) => {
      const tags = (cluster.top_tags ?? []).slice(0, 6).map((tag) => tag.tag).join(", ");
      const papers = (cluster.top_papers ?? [])
        .slice(0, 3)
        .map((paper) => paper.title)
        .filter(Boolean)
        .join("; ");
      return {
        id: `cluster:${cluster.id}`,
        collection: "semantic_clusters",
        title: `Cluster ${cluster.id}: ${tags}`,
        excerpt: `Cluster ${cluster.id} contains ${cluster.size.toLocaleString()} papers. Top tags: ${tags}. Representative papers: ${papers}.`,
        score: Math.log10(Math.max(cluster.size, 1)),
      };
    }),
    ...tagRatings.slice(0, 40).map((tag) => {
      const samples = (tag.samples ?? [])
        .slice(0, 3)
        .map((paper) => paper.title)
        .filter(Boolean)
        .join("; ");
      return {
        id: `tag:${tag.tag}`,
        collection: "openreview_tag_ratings",
        title: `${tag.tag} rating signal`,
        excerpt: `${tag.tag} has mean OpenReview rating ${tag.mean_rating.toFixed(2)} across ${tag.n_papers} papers${typeof tag.p90_rating === "number" ? ` and p90 ${tag.p90_rating.toFixed(2)}` : ""}. Examples: ${samples}.`,
        score: tag.mean_rating,
      };
    }),
  ];

  const lowerQuestion = question.toLowerCase();
  const ranked = evidence
    .map((item) => {
      const intentBoost =
        (lowerQuestion.includes("sleeper") && item.collection === "sleepers" ? 8 : 0) +
        (lowerQuestion.includes("rating") && item.collection === "openreview_tag_ratings" ? 8 : 0) +
        (lowerQuestion.includes("cluster") && item.collection === "semantic_clusters" ? 8 : 0) +
        (/(llm|language model|transformer|gpt|llama)/.test(lowerQuestion) &&
        /(llm|language model|transformer|gpt|llama)/i.test(`${item.title} ${item.excerpt}`)
          ? 20
          : 0) +
        (/(vision|image|video)/.test(lowerQuestion) &&
        /(vision|image|video|diffusion)/i.test(`${item.title} ${item.excerpt}`)
          ? 10
          : 0);
      return {
        ...item,
        score: matchScore(questionTerms, `${item.title} ${item.excerpt}`, item.score + intentBoost),
      };
    })
    .sort((a, b) => b.score - a.score || a.title.localeCompare(b.title));

  const selected = ranked.slice(0, 6);
  return {
    answer: summarizeEvidence(selected),
    citations: selected.map((item) => ({
      chunk_id: item.id,
      filename: item.collection,
      excerpt: item.excerpt,
      score: item.score,
    })),
    trace_id: null,
    route: "static-demo",
    answer_mode: "bundled-data",
  };
}

export function RagAsk() {
  const [question, setQuestion] = React.useState(
    "What are the strongest recent signals in language model research?",
  );
  const [result, setResult] = React.useState<RagResult | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function ask(nextQuestion = question) {
    const q = nextQuestion.trim();
    if (q.length < 3) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const response = await fetch(ragEndpoint(), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, top_k: 8 }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.error || body.detail || `HTTP ${response.status}`);
      }
      setResult(await response.json());
    } catch (err) {
      try {
        setResult(await staticDemoAnswer(q));
      } catch {
        setError(err instanceof Error ? err.message : "RAG request failed");
      }
    } finally {
      setLoading(false);
    }
  }

  const examples = [
    "Which underrated accepted papers look like sleepers?",
    "What clusters are strongest around transformers and vision?",
    "Which topics have high OpenReview ratings?",
  ];

  return (
    <div className="space-y-4">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void ask();
        }}
        className="space-y-3"
      >
        <textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          rows={3}
          placeholder="Ask a cited research question..."
          className="w-full rounded-lg border bg-card px-4 py-3 text-sm outline-none placeholder:text-muted-foreground/60 focus:ring-2 focus:ring-primary/50"
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" disabled={loading || question.trim().length < 3}>
            {loading ? (
              <>
                <Loader2 className="animate-spin" /> Asking...
              </>
            ) : (
              <>
                <MessageSquareText /> Ask RAG
              </>
            )}
          </Button>
          {examples.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => {
                setQuestion(example);
                void ask(example);
              }}
              className="rounded-full border px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground"
            >
              {example}
            </button>
          ))}
        </div>
      </form>

      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {result && (
        <div className="space-y-3">
          <div className="rounded-lg border bg-background/50 p-4">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              {result.route && <Badge variant="outline">{result.route}</Badge>}
              {result.answer_mode && <Badge variant="outline">{result.answer_mode}</Badge>}
              {result.trace_id && (
                <span className="font-mono text-xs text-muted-foreground">
                  trace {result.trace_id.slice(0, 10)}
                </span>
              )}
            </div>
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground/90">
              {result.answer}
            </p>
          </div>

          {result.citations?.length > 0 && (
            <div className="space-y-2">
              <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Citations
              </div>
              {result.citations.map((citation, index) => (
                <div
                  key={`${citation.chunk_id}-${index}`}
                  className="rounded-lg border bg-card p-3"
                >
                  <div className="mb-1 flex items-center justify-between gap-3 text-xs">
                    <span className="truncate font-mono text-foreground/80">
                      {citation.filename ?? citation.document_id ?? citation.chunk_id}
                    </span>
                    {typeof citation.score === "number" && (
                      <span className="font-mono text-muted-foreground">
                        {citation.score.toFixed(3)}
                      </span>
                    )}
                  </div>
                  {citation.excerpt && (
                    <p className="line-clamp-3 text-xs leading-relaxed text-muted-foreground">
                      {citation.excerpt}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
