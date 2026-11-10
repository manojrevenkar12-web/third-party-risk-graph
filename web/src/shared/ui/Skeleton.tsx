import { color, radius, space } from "../theme/tokens";

/** Grey bars in the shape of the content that is on its way. */
export function Skeleton({ label, rows = 5 }: { label: string; rows?: number }) {
  return (
    <div role="status" aria-label={label} aria-busy="true" style={{ display: "grid", gap: space[4] }}>
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          style={{
            height: i === 0 ? space[8] : space[5],
            width: `${100 - i * 11}%`,
            background: color.panel,
            borderRadius: radius.sm,
          }}
        />
      ))}
    </div>
  );
}
