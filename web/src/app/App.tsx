import { useState } from "react";
import { Designs } from "../features/designs/Designs";
import { Parts } from "../features/parts/Parts";
import { Scrubber } from "../features/scrubber/Scrubber";
import { Topics } from "../features/topics/Topics";
import type { Summary } from "../shared/data/types";
import { type Fetcher, useJson } from "../shared/data/useJson";
import { pct } from "../shared/format";
import { color, measure, size, space, weight } from "../shared/theme/tokens";
import { EmptyNotice, ErrorNotice } from "../shared/ui/Notice";
import { Section } from "../shared/ui/Section";
import { Segmented } from "../shared/ui/Segmented";
import { Skeleton } from "../shared/ui/Skeleton";

type Split = "heldout" | "dev";
const page = { maxWidth: measure.page, margin: "0 auto", padding: `${space[7]}px ${space[5]}px` } as const;
const fetchJson: Fetcher = (u) => fetch(u);

export function App({ fetcher = fetchJson }: { fetcher?: Fetcher }) {
  const load = useJson<Summary>("./data/summary.json", fetcher);
  if (load.state === "loading")
    return (
      <main style={page}>
        <Skeleton label="Loading results" />
      </main>
    );
  if (load.state === "error")
    return (
      <main style={page}>
        <ErrorNotice message={load.message} onRetry={load.retry} />
      </main>
    );
  return <Dashboard summary={load.data} />;
}

export function Dashboard({ summary }: { summary: Summary }) {
  const [split, setSplit] = useState<Split>(summary.heldout ? "heldout" : "dev");
  const run = summary[split] ?? summary.dev;
  const head = (summary.heldout ?? summary.dev)?.designs["graph-pipeline"];
  const naive = (summary.heldout ?? summary.dev)?.designs["naive-prototype"];
  const options = (["heldout", "dev"] as Split[]).filter((s) => summary[s]).map((s) => ({ value: s, label: s === "heldout" ? "Held-out" : "Development" }));
  return (
    <main style={page}>
      <header style={{ maxWidth: `${measure.text + 10}ch` }}>
        <p style={{ margin: 0, color: color.muted, fontSize: size.sm }}>third-party-risk-graph</p>
        <h1 style={{ fontSize: `clamp(${size.xl + 4}px, 5.5vw, ${size.hero}px)`, lineHeight: 1.05, fontWeight: weight.black, letterSpacing: "-0.02em", margin: `${space[3]}px 0` }}>
          Who stood behind {summary.story?.name ?? "a supplier"}, on any given day.
        </h1>
        <p style={{ color: color.muted, margin: 0 }}>
          A temporal knowledge graph of the client's suppliers, their owners and directors, sanctions and PEP lists and the press. Move the date: the graph
          answers as of that day, from filings, list entries, articles and web pages, each with its validity.
        </p>
        {head && naive && (
          <p style={{ margin: `${space[4]}px 0 0`, fontSize: size.lg }}>
            <b>{pct(head.right)}</b> of {head.questions} {summary.heldout ? "held-out" : "development"} questions answered right and <b>{pct(head.wrong)}</b> wrong; a naive
            prototype: {pct(naive.right)} right, {pct(naive.wrong)} wrong.
          </p>
        )}
      </header>
      <section style={{ padding: `${space[6]}px 0` }}>{summary.story ? <Scrubber story={summary.story} /> : <EmptyNotice what="ownership history" command="make report" />}</section>

      <Section
        title="Every design on the same questions"
        lede="Owners, beneficial owners, directors, sanctions and PEP exposure, adverse media and ownership changes, as of a date, in English and German. Right means the answer equals the truth; abstaining means the system said what it could not establish."
        aside={options.length > 1 ? <Segmented label="Questions" options={options} value={split} onChange={setSplit} /> : undefined}
      >
        {run ? <Designs run={run} /> : <EmptyNotice what="results" command="make eval && make report" />}
      </Section>
      <Section title="What each step gets right" lede="Measured against the true identity of every mention, every listing, every article and every page.">
        {run ? <Parts run={run} /> : <EmptyNotice what="results" command="make eval && make report" />}
      </Section>
      <Section title="A small model or a prompted one" lede="Adverse-media topics: the purpose-built classifier is as accurate here, costs nothing per article and answers in milliseconds.">
        <Topics topics={summary.topics.heldout ?? summary.topics.dev} />
      </Section>
      <footer style={{ borderTop: `1px solid ${color.line}`, paddingTop: space[5], color: color.muted, fontSize: size.sm, maxWidth: `${measure.text}ch` }}>
        Companies, people, filings, lists, articles and the model are simulated, with mistake rates set in config; what transfers is which step catches which
        failure. Reproduce with <code>make eval &amp;&amp; make report</code>.
      </footer>
    </main>
  );
}
