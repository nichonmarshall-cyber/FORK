/**
 * Where a figure came from, in one glance.
 *
 * Four kinds and only four, each a fixed colour, so a student learns the
 * system once: green is a document they confirmed, grey is their own
 * figure, cyan is Fork's arithmetic, violet is a What-If. The text always
 * says it too -- colour is never the only signal.
 *
 * "Confirmed" never becomes "verified": Fork checks its reading of a
 * document with the student, not with the university.
 */

import type { Provenance } from "@/lib/notebook";

const STYLES: Record<Provenance, { label: string; className: string }> = {
  confirmed_document: {
    label: "From your document",
    className: "border-emerald-400/30 bg-emerald-400/[0.08] text-emerald-300/90",
  },
  student_reported: {
    label: "You reported",
    className: "border-white/10 bg-white/[0.03] text-slate-400",
  },
  derived: {
    label: "Calculated",
    className: "border-cyan-400/30 bg-cyan-400/[0.08] text-cyan-300/90",
  },
  what_if: {
    label: "What-If",
    className: "border-violet-400/30 bg-violet-400/[0.08] text-violet-300/90",
  },
};

export const PROVENANCE_ORDER: Provenance[] = [
  "confirmed_document",
  "student_reported",
  "derived",
  "what_if",
];

export function provenanceShortLabel(p: Provenance): string {
  return STYLES[p].label;
}

export default function ProvenanceBadge({
  provenance,
  title,
}: {
  provenance: Provenance;
  /** The full source line, shown on hover and to screen readers. */
  title?: string;
}) {
  const style = STYLES[provenance];
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-full border px-1.5 py-0.5 text-[9.5px] uppercase tracking-[0.1em] ${style.className}`}
      title={title}
      data-provenance={provenance}
    >
      {style.label}
      {title && <span className="sr-only">: {title}</span>}
    </span>
  );
}
