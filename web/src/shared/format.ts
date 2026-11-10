export const pct = (x: number, digits = 1) => `${(100 * x).toFixed(digits)}%`;
export const eur = (x: number) => `€${x.toFixed(2)}`;

/** Months between two ISO dates, as ISO dates on the first of each month. */
export function months(start: string, end: string): string[] {
  const out: string[] = [];
  const d = new Date(`${start.slice(0, 7)}-01T00:00:00Z`);
  const stop = new Date(`${end}T00:00:00Z`);
  while (d <= stop) {
    out.push(d.toISOString().slice(0, 10));
    d.setUTCMonth(d.getUTCMonth() + 1);
  }
  return out;
}

export const longDate = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });

export const INTENT: Record<string, string> = {
  owners: "Owners",
  ubo: "Beneficial owners",
  directors: "Directors",
  sanctions_exposure: "Sanctions exposure",
  pep_exposure: "PEP exposure",
  adverse_media: "Adverse media",
  last_ownership_change: "Last ownership change",
  exposed_suppliers: "Exposed suppliers",
};
