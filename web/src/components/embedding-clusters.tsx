import * as React from "react";

import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { fmt } from "@/lib/utils";

type Cluster = {
  id: number;
  size: number;
  top_tags: { tag: string; n: number }[];
  top_papers: { paper_id: string; title: string; citation_count: number; source: string }[];
};

function paperUrl(paper_id: string): string {
  if (paper_id.startsWith("arxiv:")) return `https://arxiv.org/abs/${paper_id.replace("arxiv:", "")}`;
  if (paper_id.startsWith("openreview:")) return `https://openreview.net/forum?id=${paper_id.replace("openreview:", "")}`;
  return "#";
}

function ClusterCard({ c }: { c: Cluster }) {
  const anchor = c.top_papers[0];
  const tagSummary = c.top_tags.slice(0, 4).map((t) => t.tag).join(", ");
  return (
    <Dialog>
      <DialogTrigger asChild>
        <button class="text-left rounded-lg border bg-card p-4 hover:bg-muted/40 transition-colors space-y-2 w-full h-full">
          <div class="flex items-baseline justify-between">
            <span class="text-xs font-mono text-muted-foreground">cluster #{c.id}</span>
            <span class="tabular-nums text-xs text-muted-foreground">{fmt.format(c.size)} papers</span>
          </div>
          <div class="text-sm text-foreground/85 line-clamp-1">{tagSummary}</div>
          {anchor && <div class="text-xs text-muted-foreground line-clamp-2 leading-snug">{anchor.title}</div>}
        </button>
      </DialogTrigger>
      <DialogContent class="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Cluster #{c.id} <span class="text-muted-foreground font-normal text-sm">({fmt.format(c.size)} papers)</span></DialogTitle>
          <DialogDescription>
            One of 64 semantic clusters from MiniBatchKMeans over all-MiniLM-L6-v2 embeddings (478k × 384-dim).
          </DialogDescription>
        </DialogHeader>
        <div class="space-y-3 pt-2">
          <div>
            <div class="text-xs uppercase tracking-wider text-muted-foreground font-semibold mb-1">Top tags</div>
            <div class="flex flex-wrap gap-1">
              {c.top_tags.map((t, i) => (
                <Badge key={i} variant="secondary" class="text-xs">
                  {t.tag} <span class="text-muted-foreground ml-1 tabular-nums">{t.n}</span>
                </Badge>
              ))}
            </div>
          </div>
          <div>
            <div class="text-xs uppercase tracking-wider text-muted-foreground font-semibold mb-1">Top-cited papers in this cluster</div>
            <div class="space-y-1">
              {c.top_papers.map((p) => (
                <a key={p.paper_id} href={paperUrl(p.paper_id)} target="_blank" rel="noopener"
                   class="block p-2 rounded-md hover:bg-muted text-sm">
                  <div class="flex items-center gap-2 mb-0.5">
                    <Badge variant="outline" class="font-mono text-[10px]">{p.source}</Badge>
                    {p.citation_count > 0 && (
                      <span class="tabular-nums text-xs text-muted-foreground">{fmt.format(p.citation_count)} cites</span>
                    )}
                  </div>
                  <div class="text-foreground/85">{p.title}</div>
                </a>
              ))}
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function EmbeddingClusters({ data }: { data: Cluster[] }) {
  return (
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
      {data.map((c) => <ClusterCard key={c.id} c={c} />)}
    </div>
  );
}
