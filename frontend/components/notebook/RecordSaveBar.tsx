"use client";

/**
 * "Add to my notebook" for audits confirmed on the compare page.
 *
 * The review flow (upload, correct, confirm) is unchanged and still lives
 * in an in-memory session. Saving is a separate, explicit step: nothing a
 * student uploads becomes part of their durable record until they say so,
 * and only after they've confirmed Fork's reading.
 */

import Link from "next/link";
import { useState } from "react";
import { ApiError } from "@/lib/types";
import type { AuditSession } from "@/lib/audit";
import { saveAuditToRecord } from "@/lib/notebook";

type Which = "current" | "what_if";

export default function RecordSaveBar({
  session,
  onSaved,
}: {
  session: AuditSession;
  onSaved?: () => void;
}) {
  const [status, setStatus] = useState<Partial<Record<Which, string>>>({});
  const [busy, setBusy] = useState<Which | null>(null);

  const currentConfirmed = session.uploaded_source.confirmation_status === "confirmed";
  const whatIfConfirmed = session.documents?.what_if.confirmed ?? false;
  if (!currentConfirmed && !whatIfConfirmed) return null;

  async function save(which: Which) {
    setBusy(which);
    try {
      const r = await saveAuditToRecord(session.session_id, which);
      setStatus((s) => ({
        ...s,
        [which]: r.created ? "Added to your notebook." : "Already in your notebook.",
      }));
      onSaved?.();
    } catch (err) {
      setStatus((s) => ({
        ...s,
        [which]: err instanceof ApiError ? err.message : "Couldn't add it to your notebook.",
      }));
    } finally {
      setBusy(null);
    }
  }

  const row = (which: Which, label: string) => (
    <div className="flex flex-wrap items-center gap-2">
      <button
        type="button"
        onClick={() => save(which)}
        disabled={busy !== null}
        className="rounded-lg border border-emerald-400/30 bg-emerald-400/[0.06] px-3 py-1.5 text-[12px] font-medium text-emerald-200 hover:bg-emerald-400/10 disabled:opacity-60"
      >
        {busy === which ? "Adding…" : label}
      </button>
      {status[which] && (
        <span role="status" className="text-[12px] text-slate-400">
          {status[which]}{" "}
          {status[which]?.includes("notebook") && (
            <Link href="/#record" className="text-cyan-300 hover:underline">
              View
            </Link>
          )}
        </span>
      )}
    </div>
  );

  return (
    <div className="space-y-2 rounded-xl border border-white/[0.07] bg-white/[0.02] p-3">
      <p className="text-[11.5px] leading-relaxed text-slate-500">
        Keep what you confirmed in your notebook. Fork saves the figures it read and you
        confirmed — not the PDF or your course-by-course grades.
      </p>
      {currentConfirmed && row("current", "Add this degree audit to my notebook")}
      {whatIfConfirmed && row("what_if", "Add the What-If audit to my notebook")}
    </div>
  );
}
