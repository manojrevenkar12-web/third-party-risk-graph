import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useMemo, useState } from "react";
import type { Entity, Fact, Story } from "../../shared/data/types";
import { longDate, months } from "../../shared/format";
import { color, font, measure, motion as m, radius, size, space, weight } from "../../shared/theme/tokens";

const holds = (f: Fact, d: string) => f.v <= d && (f.i === null || f.i > d);

type Placed = { e: Entity; x: number; y: number; level: number };

/** Positions stay fixed over time: every entity that is ever upstream gets a level and a slot. */
function layout(story: Story, minWidth: number): { placed: Map<string, Placed>; width: number } {
  const byId = new Map(story.entities.map((e) => [e.uuid, e]));
  const level = new Map<string, number>([[story.supplier, 0]]);
  const queue = [story.supplier];
  while (queue.length) {
    const x = queue.shift()!;
    for (const f of story.facts) {
      if (f.fact === "OWNS" && f.b === x && !level.has(f.a)) {
        level.set(f.a, level.get(x)! + 1);
        queue.push(f.a);
      }
    }
  }
  // directors sit on their own row under the supplier, so their lines never cross other nodes
  for (const f of story.facts) if (f.fact === "DIRECTOR_OF" && f.b === story.supplier && !level.has(f.a)) level.set(f.a, -1);
  const rows = new Map<number, string[]>();
  for (const [id, l] of level) rows.set(l, [...(rows.get(l) ?? []), id]);
  const top = Math.max(...rows.keys());
  const widest = Math.max(...[...rows.values()].map((r) => r.length));
  const width = Math.max(minWidth, widest * (measure.node.w + space[5]));
  const out = new Map<string, Placed>();
  for (const [l, ids] of rows) {
    ids.sort((a, b) => (a === story.supplier ? -1 : b === story.supplier ? 1 : (byId.get(a)?.name ?? "").localeCompare(byId.get(b)?.name ?? "")));
    ids.forEach((id, k) => {
      const e = byId.get(id);
      if (!e) return;
      out.set(id, { e, level: l, x: ((k + 0.5) * width) / ids.length, y: (top - l) * measure.level + measure.node.h });
    });
  }
  return { placed: out, width };
}

export function Scrubber({ story }: { story: Story }) {
  const reduce = useReducedMotion();
  const steps = useMemo(() => months(story.start, story.end), [story]);
  const [k, setK] = useState(steps.length - 1);
  const d = steps[k];
  const { placed, width } = useMemo(() => layout(story, measure.chart * 2), [story]);
  const owns = story.facts.filter((f) => f.fact === "OWNS" && holds(f, d) && placed.has(f.a) && placed.has(f.b));
  // upstream as of d
  const up = new Set<string>([story.supplier]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const f of owns) if (up.has(f.b) && !up.has(f.a)) (up.add(f.a), (grew = true));
  }
  const directors = story.facts.filter((f) => f.fact === "DIRECTOR_OF" && f.b === story.supplier && holds(f, d));
  const listed = new Map(story.facts.filter((f) => f.fact === "LISTED_ON" && holds(f, d)).map((f) => [f.a, f]));
  const names = new Map(story.entities.map((e) => [e.uuid, e.name]));
  const hits = [...up, ...directors.map((f) => f.a)].filter((u) => listed.has(u));
  const active = new Set([...up, ...directors.map((f) => f.a)]);
  const visible = [...placed.values()].filter((p) => active.has(p.e.uuid));
  const height = Math.max(...[...placed.values()].map((p) => p.y)) + measure.node.h;

  return (
    <div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: space[4], alignItems: "center", margin: `${space[4]}px 0` }}>
        <label htmlFor="asof" style={{ fontWeight: weight.bold }}>
          As of {longDate(d)}
        </label>
        <input
          id="asof"
          type="range"
          min={0}
          max={steps.length - 1}
          value={k}
          onChange={(ev) => setK(Number(ev.target.value))}
          aria-valuetext={longDate(d)}
          style={{ flex: "1 1 280px", accentColor: color.registry }}
        />
      </div>
      <motion.p
        key={hits.length ? `hit-${hits.join()}` : "clear"}
        initial={reduce ? false : { opacity: 0, y: space[1] }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: m.fast, ease: m.ease }}
        role="status"
        style={{
          margin: 0,
          padding: `${space[3]}px ${space[4]}px`,
          borderRadius: radius.md,
          background: hits.length ? color.listedSoft : color.registrySoft,
          color: hits.length ? color.listed : color.registry,
          fontWeight: weight.bold,
        }}
      >
        {hits.length
          ? `Exposed: ${hits.map((h) => names.get(h)).join(", ")} ${hits.length > 1 ? "are" : "is"} on a sanctions list (${listed.get(hits[0])!.bname}, since ${longDate(listed.get(hits[0])!.v)}).`
          : "No owner, beneficial owner or director is on a sanctions list on this day."}
      </motion.p>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Ownership of ${story.name} as of ${longDate(d)}`} style={{ width: "100%", height: "auto", marginTop: space[4] }}>
        <AnimatePresence>
          {owns
            .filter((f) => up.has(f.b))
            .map((f) => {
              const a = placed.get(f.a)!;
              const b = placed.get(f.b)!;
              const trusted = f.source === "registry";
              return (
                <motion.g key={`${f.a}-${f.b}-${f.v}`} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: reduce ? 0 : m.fast }}>
                  <line x1={a.x} y1={a.y + measure.node.h / 2} x2={b.x} y2={b.y - measure.node.h / 2} stroke={trusted ? color.registry : color.web} strokeWidth={2} strokeDasharray={trusted ? undefined : "6 5"} />
                  <text x={(a.x + b.x) / 2 + space[3]} y={(a.y + b.y) / 2} fontSize={size.sm} fill={color.muted} fontFamily={font.body} stroke={color.paper} strokeWidth={space[1]} paintOrder="stroke">
                    {f.pct !== null ? `${Math.round(f.pct)}%` : ""}
                    {trusted ? "" : ` (${f.source})`}
                  </text>
                </motion.g>
              );
            })}
          {directors
            .filter((f) => placed.has(f.a))
            .map((f) => {
              const a = placed.get(f.a)!;
              const b = placed.get(f.b)!;
              return (
                <motion.g key={`dir-${f.a}-${f.v}`} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: reduce ? 0 : m.fast }}>
                  <line x1={b.x} y1={b.y + measure.node.h / 2} x2={a.x} y2={a.y - measure.node.h / 2} stroke={color.muted} strokeWidth={1} strokeDasharray="2 4" />
                  <text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2} textAnchor="middle" fontSize={size.xs} fill={color.muted} fontFamily={font.body} stroke={color.paper} strokeWidth={space[1]} paintOrder="stroke">
                    director
                  </text>
                </motion.g>
              );
            })}
          {visible.map((p) => {
            const hit = listed.has(p.e.uuid);
            return (
              <motion.g key={p.e.uuid} initial={{ opacity: 0, y: reduce ? 0 : space[2] }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: reduce ? 0 : m.fast, ease: m.ease }}>
                <rect x={p.x - measure.node.w / 2} y={p.y - measure.node.h / 2} width={measure.node.w} height={measure.node.h} rx={radius.md} fill={hit ? color.listedSoft : color.card} stroke={hit ? color.listed : p.e.uuid === story.supplier ? color.ink : color.line} strokeWidth={hit || p.e.uuid === story.supplier ? 2 : 1} />
                <text x={p.x} y={p.y - space[1]} textAnchor="middle" fontSize={size.sm} fontWeight={weight.bold} fill={color.ink} fontFamily={font.body}>
                  {p.e.name.length > 26 ? `${p.e.name.slice(0, 25)}…` : p.e.name}
                </text>
                <text x={p.x} y={p.y + size.sm} textAnchor="middle" fontSize={size.xs} fill={hit ? color.listed : color.muted} fontFamily={font.body}>
                  {hit ? `listed: ${listed.get(p.e.uuid)!.bname}` : `${p.e.kind}${p.e.country ? `, ${p.e.country}` : ""}`}
                </text>
              </motion.g>
            );
          })}
        </AnimatePresence>
      </svg>
      <p style={{ color: color.muted, fontSize: size.sm, margin: `${space[2]}px 0 0` }}>
        Solid lines are shareholdings from registry filings, dashed violet lines shareholdings read from a web page or an article, and dotted lines
        directorships.
      </p>
    </div>
  );
}
