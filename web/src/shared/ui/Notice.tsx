import { color, font, radius, size, space, weight } from "../theme/tokens";

export const buttonStyle = {
  font: `${weight.bold} ${size.sm}px ${font.body}`,
  color: color.card,
  background: color.ink,
  border: "none",
  borderRadius: radius.pill,
  padding: `${space[2]}px ${space[5]}px`,
  cursor: "pointer",
} as const;

export function ErrorNotice({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" style={{ borderLeft: `${space[1]}px solid ${color.wrong}`, padding: `${space[3]}px ${space[4]}px` }}>
      <p style={{ margin: 0 }}>The results could not be loaded: {message}.</p>
      <p style={{ margin: `${space[2]}px 0 ${space[3]}px`, color: color.muted }}>
        <code>web/public/data/summary.json</code> is written by <code>make report</code>. Check that it exists, then try
        again.
      </p>
      <button type="button" onClick={onRetry} style={buttonStyle}>
        Try again
      </button>
    </div>
  );
}

export function EmptyNotice({ what, command }: { what: string; command: string }) {
  return (
    <p style={{ color: color.muted, margin: 0 }}>
      No {what} yet. Run <code>{command}</code> to produce them.
    </p>
  );
}
