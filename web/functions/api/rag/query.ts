interface Env {
  RAG_SERVICE_KEY?: string;
  RAG_SERVICE_URL?: string;
  RAG_DOMAIN?: string;
}

type PagesContext = {
  request: Request;
  env: Env;
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

const DEFAULT_RAG_URL = "https://knowledgebase.sarthakagrawal927.workers.dev";
const DEFAULT_DOMAIN = "research-papers";

async function fetchAssetJson<T>(request: Request, path: string): Promise<T> {
  const url = new URL(path, request.url);
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Could not load ${path}`);
  return response.json() as Promise<T>;
}

function paperId(paper: StaticPaper): string {
  return paper.paper_id ?? (paper.arxiv_id ? `arxiv:${paper.arxiv_id}` : paper.title ?? "paper");
}

function paperMeta(paper: StaticPaper): string {
  return [
    paper.venue,
    paper.decision,
    typeof paper.avg_rating === "number" ? `rating ${paper.avg_rating.toFixed(1)}` : null,
    typeof paper.citation_count === "number" ? `${paper.citation_count.toLocaleString()} citations` : null,
    typeof paper.cites_per_year === "number" ? `${paper.cites_per_year.toFixed(1)} cites/year` : null,
    paper.submitted_date,
  ]
    .filter(Boolean)
    .join(" | ");
}

function paperEvidence(collection: string, paper: StaticPaper, boost = 0): Evidence {
  const title = paper.title ?? paperId(paper);
  const tags = [...(paper.topic_tags ?? []), ...(paper.top_keywords ?? [])].slice(0, 5);
  const excerpt = [title, paperMeta(paper), tags.length ? `Signals: ${tags.join(", ")}` : null]
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

function tokens(value: string): string[] {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, " ")
    .split(/\s+/)
    .filter((token) => token.length > 2);
}

function matchScore(questionTerms: string[], text: string, boost = 0): number {
  const haystack = text.toLowerCase();
  return (
    boost +
    questionTerms.reduce((score, term) => score + (haystack.includes(term) ? 1 : 0), 0)
  );
}

function summarizeEvidence(evidence: Evidence[]): string {
  return [
    "Based on the deployed research-paper data, the strongest signals are:",
    ...evidence.slice(0, 5).map((item, index) => {
      const source = item.collection.replace(/_/g, " ");
      return `${index + 1}. ${item.title} (${source}): ${item.excerpt}`;
    }),
    "",
    "This answer is served from the bundled demo index when the live Knowledgebase RAG service is unavailable. The same endpoint switches to the full server RAG path when the service key is configured.",
  ].join("\n");
}

async function staticDemoAnswer(request: Request, question: string): Promise<Response> {
  const [hot, sleepers, reviewTop, topPapers, clusters, tagRatings] = await Promise.all([
    fetchAssetJson<StaticPaper[]>(request, "/data/hot.json"),
    fetchAssetJson<StaticPaper[]>(request, "/data/sleepers.json"),
    fetchAssetJson<StaticPaper[]>(request, "/data/review_top_papers.json"),
    fetchAssetJson<StaticPaper[]>(request, "/data/top_papers.json"),
    fetchAssetJson<StaticCluster[]>(request, "/data/embedding_clusters.json"),
    fetchAssetJson<StaticTagRating[]>(request, "/data/tag_rating.json"),
  ]);

  const questionTerms = tokens(question);
  const lowerQuestion = question.toLowerCase();
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

  const selected = evidence
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
    .sort((a, b) => b.score - a.score || a.title.localeCompare(b.title))
    .slice(0, 6);

  return Response.json(
    {
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
    },
    {
      headers: {
        "Cache-Control": "no-store",
      },
    },
  );
}

export async function onRequestPost(context: PagesContext): Promise<Response> {
  let payload: Record<string, unknown>;
  try {
    payload = await context.request.json();
  } catch {
    return Response.json({ error: "JSON body is required" }, { status: 400 });
  }

  const question = String(payload.question ?? payload.query ?? "").trim();
  if (question.length < 3) {
    return Response.json(
      { error: "question must be at least 3 characters" },
      { status: 400 },
    );
  }

  const key = context.env.RAG_SERVICE_KEY;
  if (!key) {
    return staticDemoAnswer(context.request, question);
  }

  const baseUrl = (context.env.RAG_SERVICE_URL || DEFAULT_RAG_URL).replace(/\/+$/, "");
  const domain = String(payload.domain ?? context.env.RAG_DOMAIN ?? DEFAULT_DOMAIN).trim();
  const topK = Math.min(Math.max(Number(payload.top_k ?? 8), 1), 20);

  const upstream = await fetch(`${baseUrl}/v1/kb/query`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      domain,
      question,
      mode: String(payload.mode ?? "hybrid"),
      answer_mode: String(payload.answer_mode ?? "extractive"),
      top_k: topK,
      rerank: true,
      mmr: true,
      query_rewrite: true,
      query_decompose: true,
    }),
  });

  const text = await upstream.text();
  let body: unknown;
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    body = { error: text || "upstream returned non-JSON response" };
  }

  if (!upstream.ok) {
    return staticDemoAnswer(context.request, question);
  }

  return Response.json(body, {
    headers: {
      "Cache-Control": "no-store",
    },
  });
}
