import { motion, useReducedMotion } from "framer-motion";
import type { Run } from "../../shared/data/types";
import { pct } from "../../shared/format";
import { color, measure, motion as m, radius, size, space, weight } from "../../shared/theme/tokens";
import { EmptyNotice } from "../../shared/ui/Notice";
import { useNarrow } from "../../shared/ui/useNarrow";

const PARTS = [
  { key: "right", label: "right", fill: color.right },
  { key: "abstained", label: "said it could not tell", fill: color.abstain },
  { key: "wrong", label: "wrong", fill: color.wrong },
] as const;

/** One bar per design: right, abstained and wrong answers to the same questions. */
export function Designs({ run }: { run: Run }) {
  const reduce = useReducedMotion();
  const narrow = useNarrow();
  const rows = Object.entries(run.designs);
  if (!rows.length) return <EmptyNotice what="results" command="make eval && make report" />;
  return (
    <div>
      <p style={{ display: "flex", gap: space[4], flexWrap: "wrap", fontSize: size.sm, color: color.muted, margin: `0 0 ${space[4]}px` }}>
        {PARTS.map((p) => (
          <span key={p.key} style={{ display: "inline-flex", alignItems: "center", gap: space[2] }}>
            <span style={{ width: space[3], height: space[3], borderRadius: radius.sm, background: p.fill }} />
            {p.label}
          </span>
        ))}
      </p>
      <div style={{ display: "grid", gap: space[3] }}>
        {rows.map(([name, d]) => (
          <div
            key={name}
            role="img"
            aria-label={`${d.label}: ${pct(d.right)} right, ${pct(d.wrong)} wrong, ${pct(d.abstained)} abstained`}
            style={{
              display: "grid",
              gridTemplateColumns: narrow ? "1fr auto" : "minmax(160px, 280px) 1fr minmax(110px, 150px)",
              gap: narrow ? `${space[1]}px ${space[3]}px` : space[4],
              alignItems: "center",
            }}
          >
            <span style={{ fontSize: size.sm, fontWeight: name === "graph-pipeline" ? weight.bold : weight.regular }}>{d.label}</span>
            <div style={{ display: "flex", height: measure.bar, borderRadius: radius.pill, overflow: "hidden", background: color.panel, gridColumn: narrow ? "1 / -1" : undefined, gridRow: narrow ? 2 : undefined }}>
              {PARTS.map((p) => (
                <motion.div key={p.key} initial={false} animate={{ width: `${100 * d[p.key]}%` }} transition={{ duration: reduce ? 0 : m.fast, ease: m.ease }} style={{ background: p.fill }} />
              ))}
            </div>
            <span style={{ fontSize: size.sm }}>
              <b>{pct(d.right)}</b> <span style={{ color: d.wrong > 0.02 ? color.wrong : color.muted }}>{pct(d.wrong)} wrong</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
