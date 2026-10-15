/** Display formatting shared by the notebook screens. Pure functions. */

export function money(n: number): string {
  return `${n < 0 ? "−" : ""}$${Math.abs(n).toLocaleString("en-US", {
    maximumFractionDigits: 0,
  })}`;
}

/** A signed change in semesters, worded so zero reads as "no change". */
export function semestersDelta(n: number): string {
  if (n === 0) return "No change";
  const abs = Math.abs(n);
  return `${n > 0 ? "+" : "−"}${abs} semester${abs === 1 ? "" : "s"}`;
}

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Group label for the journey: "October 2026". */
export function monthLabel(iso: string | null | undefined): string {
  if (!iso) return "Undated";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "Undated";
  return d.toLocaleDateString("en-US", { month: "long", year: "numeric" });
}

export function hours(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}
