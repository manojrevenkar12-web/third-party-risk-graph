import type { ReactNode } from "react";
import { color, measure, size, space, weight } from "../theme/tokens";

export function Section({ title, lede, children, aside }: { title: string; lede?: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <section style={{ padding: `${space[7]}px 0`, borderTop: `1px solid ${color.line}` }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: space[4], justifyContent: "space-between", alignItems: "end" }}>
        <div style={{ maxWidth: `${measure.text}ch` }}>
          <h2 style={{ fontSize: size.xl, fontWeight: weight.bold, margin: 0, letterSpacing: "-0.01em" }}>{title}</h2>
          {lede && <p style={{ color: color.muted, margin: `${space[2]}px 0 0` }}>{lede}</p>}
        </div>
        {aside}
      </div>
      <div style={{ marginTop: space[6] }}>{children}</div>
    </section>
  );
}
