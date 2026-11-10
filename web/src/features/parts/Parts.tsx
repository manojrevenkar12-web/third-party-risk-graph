import type { Run } from "../../shared/data/types";
import { pct } from "../../shared/format";
import { color, size, space, weight } from "../../shared/theme/tokens";
import { EmptyNotice } from "../../shared/ui/Notice";

const METRICS: { key: string; label: string; what: string; fmt: (v: number) => string }[] = [
  { key: "er_precision", label: "Resolution precision", what: "pairs of mentions merged into one entity that are the same person or company", fmt: pct },
  { key: "er_recall", label: "Resolution recall", what: "pairs that are the same and were merged", fmt: pct },
  { key: "false_sanctions_links", label: "Listings on the wrong party", what: "sanctions entries attached to a namesake", fmt: (v) => String(v) },
  { key: "article_precision", label: "Article precision", what: "adverse-media facts attached to the right entity with the right topic", fmt: pct },
  { key: "web_precision", label: "Web enrichment precision", what: "owners read from web pages that really owned the company", fmt: pct },
];

/** The graph pipeline against the naive prototype, step by step. */
export function Parts({ run }: { run: Run }) {
  const a = run.designs["graph-pipeline"];
  const b = run.designs["naive-prototype"];
  if (!a || !b) return <EmptyNotice what="results" command="make eval && make report" />;
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: size.sm }}>
      <thead>
        <tr style={{ textAlign: "left", color: color.muted }}>
          <th style={{ fontWeight: weight.medium, paddingBottom: space[2] }}>Step</th>
          <th style={{ fontWeight: weight.medium }}>Graph pipeline</th>
          <th style={{ fontWeight: weight.medium }}>Naive prototype</th>
        </tr>
      </thead>
      <tbody>
        {METRICS.map((mt) => (
          <tr key={mt.key} style={{ borderTop: `1px solid ${color.line}` }}>
            <td style={{ padding: `${space[3]}px ${space[4]}px ${space[3]}px 0` }}>
              <b>{mt.label}</b>
              <br />
              <span style={{ color: color.muted }}>{mt.what}</span>
            </td>
            <td style={{ fontWeight: weight.bold, fontSize: size.lg }}>{mt.fmt((a as unknown as Record<string, number>)[mt.key])}</td>
            <td style={{ color: color.muted, fontSize: size.lg }}>{mt.fmt((b as unknown as Record<string, number>)[mt.key])}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
