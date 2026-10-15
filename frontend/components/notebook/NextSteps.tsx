/**
 * "Before you meet your advisor": what would make the record more complete
 * or the conversation more useful. Each item is triggered by a specific gap
 * the backend found in the record, and says which.
 */

import Link from "next/link";
import type { NextStep } from "@/lib/notebook";
import { PROVENANCE_ORDER } from "./ProvenanceBadge";
import ProvenanceBadge from "./ProvenanceBadge";

export default function NextSteps({ steps, id = "next" }: { steps: NextStep[]; id?: string }) {
  const required = steps.filter((s) => !s.optional);
  const optional = steps.filter((s) => s.optional);

  return (
    <section
      aria-labelledby={`${id}-heading`}
      className="rounded-2xl border border-cyan-400/15 bg-[#0a0e17] p-5"
    >
      <h2 id={`${id}-heading`} className="text-[15px] font-semibold text-slate-100">
        Before you meet your advisor
      </h2>
      <p className="mt-1 text-[12.5px] leading-relaxed text-slate-500">
        Fork is the step before your advisor, not a replacement. These get you there with
        better questions.
      </p>

      {steps.length === 0 ? (
        <p className="mt-4 text-[12.5px] text-slate-400">
          Your record is in good shape. Bring your saved comparisons and ask your advisor to
          check the figures marked as your own.
        </p>
      ) : (
        <ol className="mt-4 space-y-3">
          {[...required, ...optional].map((step) => (
            <li key={step.id} className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-3.5">
              <p className="text-[13px] font-medium text-slate-100">
                {step.title}
                {step.optional && (
                  <span className="ml-2 text-[10.5px] font-normal uppercase tracking-[0.1em] text-slate-600">
                    optional
                  </span>
                )}
              </p>
              <p className="mt-1 text-[12px] leading-relaxed text-slate-400">{step.detail}</p>
              <Link
                href={step.action.href}
                className="mt-2 inline-block text-[12px] font-medium text-cyan-300 hover:underline"
              >
                {step.action.label} →
              </Link>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

export function ProvenanceLegend() {
  const text: Record<string, string> = {
    confirmed_document: "Read from a document by Fork, and you confirmed the reading. Not checked with UNT.",
    student_reported: "A figure you entered yourself.",
    derived: "Worked out by Fork from other figures and published data, the same way every time.",
    what_if: "From a What-If audit — true only for that program, not your current one.",
  };
  return (
    <section aria-labelledby="legend-heading" className="rounded-2xl border border-white/[0.07] bg-[#0a0e17] p-5">
      <h2 id="legend-heading" className="text-[13px] font-semibold text-slate-200">
        How to read your record
      </h2>
      <ul className="mt-3 space-y-2.5">
        {PROVENANCE_ORDER.map((p) => (
          <li key={p} className="flex items-start gap-2.5">
            <ProvenanceBadge provenance={p} />
            <span className="text-[11.5px] leading-snug text-slate-500">{text[p]}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
