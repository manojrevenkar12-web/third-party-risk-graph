import { useEffect, useState } from "react";
import { breakpoint } from "../theme/tokens";

/** True on screens narrower than the narrow breakpoint (follows resizes). */
export function useNarrow(): boolean {
  const query = `(max-width: ${breakpoint.narrow}px)`;
  const get = () => typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia(query).matches;
  const [narrow, setNarrow] = useState(get);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const m = window.matchMedia(query);
    const on = () => setNarrow(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, [query]);
  return narrow;
}
