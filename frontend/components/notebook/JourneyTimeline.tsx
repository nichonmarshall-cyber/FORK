/**
 * The academic journey: what has happened to the student's record, newest
 * first, grouped by month. Each line is written by the backend at the
 * moment the change was made; this only lays them out.
 */

import Link from "next/link";
import { dateTime, monthLabel } from "@/lib/format";
import type { TimelineEvent } from "@/lib/notebook";

const KIND: Record<string, { label: string; dot: string }> = {
  notebook_started: { label: "Notebook", dot: "bg-slate-500" },
  audit_added: { label: "Document", dot: "bg-emerald-400" },
  what_if_added: { label: "What-If", dot: "bg-violet-400" },
  document_recorded: { label: "Document", dot: "bg-slate-400" },
  document_file_attached: { label: "Document", dot: "bg-slate-400" },
  document_removed: { label: "Document", dot: "bg-rose-400" },
  facts_updated: { label: "Your details", dot: "bg-slate-300" },
  comparison_saved: { label: "Comparison", dot: "bg-cyan-400" },
  comparison_updated: { label: "Comparison", dot: "bg-cyan-400" },
  comparison_removed: { label: "Comparison", dot: "bg-slate-500" },
  plan_chosen: { label: "Decision", dot: "bg-amber-300" },
  plan_cleared: { label: "Decision", dot: "bg-slate-500" },
};

function linkFor(event: TimelineEvent): { href: string; label: string } | null {
  if (event.scenario_id) return { href: `/compare?scenario=${event.scenario_id}`, label: "Open" };
  if (event.document_id) return { href: "/#record", label: "View" };
  return null;
}

export default function JourneyTimeline({ events }: { events: TimelineEvent[] }) {
  const groups: { month: string; items: TimelineEvent[] }[] = [];
  for (const e of events) {
    const month = monthLabel(e.occurred_at);
    const last = groups[groups.length - 1];
    if (last && last.month === month) last.items.push(e);
    else groups.push({ month, items: [e] });
  }

  return (
    <section
      id="journey"
      aria-labelledby="journey-heading"
      className="rounded-2xl border border-white/[0.07] bg-[#0a0e17] p-5"
    >
      <h2 id="journey-heading" className="text-[15px] font-semibold text-slate-100">
        Your academic journey
      </h2>
      <p className="mt-1 text-[12.5px] text-slate-500">
        What you&rsquo;ve added, explored, and decided, newest first.
      </p>

      {events.length === 0 ? (
        <p className="mt-4 text-[12.5px] text-slate-500">Nothing here yet.</p>
      ) : (
        <div className="mt-4 space-y-5">
          {groups.map((g) => (
            <div key={g.month}>
              <h3 className="text-[10.5px] uppercase tracking-[0.15em] text-slate-600">{g.month}</h3>
              <ol className="mt-2 space-y-0 border-l border-white/[0.08] pl-4">
                {g.items.map((e) => {
                  const kind = KIND[e.event_type] ?? { label: "Update", dot: "bg-slate-500" };
                  const link = linkFor(e);
                  return (
                    <li key={e.id} className="relative pb-3.5 last:pb-0">
                      <span
                        aria-hidden
                        className={`absolute -left-[21px] top-1.5 h-2 w-2 rounded-full ring-4 ring-[#0a0e17] ${kind.dot}`}
                      />
                      <p className="text-[13px] leading-snug text-slate-200">{e.summary}</p>
                      <p className="mt-0.5 flex flex-wrap gap-x-2 text-[11px] text-slate-500">
                        <span>{kind.label}</span>
                        <time dateTime={e.occurred_at ?? undefined}>{dateTime(e.occurred_at)}</time>
                        {link && (
                          <Link href={link.href} className="text-cyan-300/90 hover:underline">
                            {link.label}
                          </Link>
                        )}
                      </p>
                    </li>
                  );
                })}
              </ol>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
