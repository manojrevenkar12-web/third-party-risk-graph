import { useCallback, useEffect, useState } from "react";

export type Load<T> =
  | { state: "loading" }
  | { state: "error"; message: string; retry: () => void }
  | { state: "ready"; data: T; retry: () => void };

export type Fetcher = (url: string) => Promise<Response>;

/** Fetches one JSON file and reports loading, error (with retry) or the data. */
export function useJson<T>(url: string, fetcher: Fetcher): Load<T> {
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<Load<T>>({ state: "loading" });
  const retry = useCallback(() => setAttempt((a) => a + 1), []);
  useEffect(() => {
    let live = true;
    setResult({ state: "loading" });
    fetcher(url)
      .then(async (r) => {
        if (!r.ok) throw new Error(`${url} answered ${r.status}`);
        const data = (await r.json()) as T;
        if (live) setResult({ state: "ready", data, retry });
      })
      .catch((e: unknown) => {
        if (live) setResult({ state: "error", message: e instanceof Error ? e.message : String(e), retry });
      });
    return () => {
      live = false;
    };
  }, [url, fetcher, attempt, retry]);
  return result;
}
