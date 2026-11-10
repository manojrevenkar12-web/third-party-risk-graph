import { color, font, size } from "./tokens";

/** Exposes the tokens as CSS variables so the stylesheet and inline styles share one source. */
export function applyTheme(root: HTMLElement = document.documentElement): void {
  for (const [k, v] of Object.entries(color)) root.style.setProperty(`--${k}`, v);
  root.style.setProperty("--font-body", font.body);
  for (const [k, v] of Object.entries(size)) root.style.setProperty(`--size-${k}`, `${v}px`);
}
