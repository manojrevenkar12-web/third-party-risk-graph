import type { TopicRow, Topics as T } from "../../shared/data/types";
import { pct } from "../../shared/format";
import { color, size, space, weight } from "../../shared/theme/tokens";

const ROWS = ["small model", "model (small)", "model (large)", "cascade"];
const LABEL: Record<string, string> = {
  "small model": "Purpose-built classifier (TF-IDF, logistic regression)",
  "model (small)": "Prompted model, small tier",
  "model (large)": "Prompted model, large tier",
  cascade: "Classifier, model when it is unsure",
};

/** Adverse-media topics: a small trained model against a prompted one, on accuracy, cost and latency. */
export function Topics({ topics }: { topics: T }) {
  return (
    <div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: size.sm }}>
        <thead>
          <tr style={{ textAlign: "left", color: color.muted }}>
            {["Approach", "Accuracy", "EUR per 1,000 articles", "Latency"].map((h) => (
              <th key={h} style={{ fontWeight: weight.medium, paddingBottom: space[2] }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ROWS.map((r) => {
            const v = topics[r] as TopicRow | undefined;
            if (!v) return null;
            return (
              <tr key={r} style={{ borderTop: `1px solid ${color.line}` }}>
                <td style={{ padding: `${space[3]}px ${space[4]}px ${space[3]}px 0`, fontWeight: r === "small model" ? weight.bold : weight.regular }}>{LABEL[r]}</td>
                <td>{pct(v.accuracy)}</td>
                <td>{v.eur_per_1000.toFixed(3)}</td>
                <td>{v.ms < 100 ? `${v.ms.toFixed(1)} ms` : `${(v.ms / 1000).toFixed(1)} s`}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p style={{ color: color.muted, fontSize: size.sm }}>
        {topics.articles} articles ({topics.split === "dev" ? "five-fold cross-validation on development articles" : "published after the cutoff; the classifier never saw them"}).
      </p>
    </div>
  );
}
