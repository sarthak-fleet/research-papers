import * as React from "react";

import { fmt } from "@/lib/utils";

type Node = { id: string; count: number };
type Edge = { source: string; target: string; co_occurrence: number };

export function TagCooccurrence({ data }: { data: { nodes: Node[]; edges: Edge[] } }) {
  const nodes = data.nodes.slice(0, 20);
  const nodeIds = nodes.map((n) => n.id);
  const idIndex = new Map(nodeIds.map((id, i) => [id, i]));

  const matrix: number[][] = nodes.map(() => nodes.map(() => 0));
  for (const e of data.edges) {
    const i = idIndex.get(e.source);
    const j = idIndex.get(e.target);
    if (i !== undefined && j !== undefined) {
      matrix[i][j] = e.co_occurrence;
      matrix[j][i] = e.co_occurrence;
    }
  }

  const maxEdge = Math.max(...data.edges.map((e) => e.co_occurrence));
  const colorFor = (v: number) => {
    if (v === 0) return "transparent";
    const intensity = Math.min(1, Math.log10(1 + v) / Math.log10(1 + maxEdge));
    const alpha = 0.1 + intensity * 0.85;
    return `rgba(99, 179, 237, ${alpha.toFixed(3)})`;
  };

  return (
    <div className="overflow-x-auto">
      <table className="text-[10px] font-mono border-collapse">
        <thead>
          <tr>
            <th className="sticky left-0 bg-background z-10 p-1"></th>
            {nodes.map((n) => (
              <th
                key={n.id}
                className="font-normal text-muted-foreground align-bottom p-0"
                style={{ height: "130px", minWidth: "24px", maxWidth: "24px" }}
              >
                <div
                  style={{
                    transform: "rotate(-60deg) translateY(20px)",
                    transformOrigin: "bottom left",
                    whiteSpace: "nowrap",
                    paddingLeft: "4px",
                  }}
                >
                  {n.id}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {nodes.map((row_n, i) => (
            <tr key={row_n.id}>
              <th
                className="sticky left-0 bg-background z-10 text-right pr-2 font-normal text-muted-foreground"
                style={{ minWidth: "180px", maxWidth: "180px" }}
              >
                <span className="truncate inline-block w-full text-right">{row_n.id}</span>
                <span className="text-[9px] text-muted-foreground ml-1">{fmt.format(row_n.count)}</span>
              </th>
              {nodes.map((col_n, j) => {
                const v = matrix[i][j];
                const isDiag = i === j;
                return (
                  <td
                    key={col_n.id}
                    title={isDiag ? `${row_n.id}: ${row_n.count} papers` : `${row_n.id} ↔ ${col_n.id}: ${v} co-occurrences`}
                    className="text-center align-middle"
                    style={{
                      width: "24px",
                      height: "24px",
                      background: isDiag ? "rgba(99,179,237,0.15)" : colorFor(v),
                      border: "1px solid rgba(0,0,0,0.05)",
                    }}
                  >
                    {v > 0 && !isDiag && v >= maxEdge * 0.05 ? (
                      <span className="text-[8px] font-semibold text-slate-950">{v >= 1000 ? `${Math.round(v / 100) / 10}k` : v}</span>
                    ) : null}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
