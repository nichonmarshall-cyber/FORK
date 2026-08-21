"use client";

import { useRef, useState } from "react";
import {
  AuditSession,
  DocumentsState,
  acknowledgeDiscrepancies,
  confirmDocument,
  looksLikePdf,
  uploadWhatIf,
} from "@/lib/audit";
import { ApiError } from "@/lib/types";

/**
 * The What-If slot.
 *
 * A What-If audit answers a question a current audit can't: how many of a
 * student's hours apply to a *different* degree. That figure is the one Fork
 * otherwise has to ask them to estimate, so a confirmed What-If replaces the
 * manual input for exactly the program it was run against.
 *
 * Exactly the program it was run against. A Computer Science What-If supplies
 * Computer Science and nothing else — the backend resolves the document's
 * program to one major key and refuses when it can't, and this component
 * never infers a program from context.
 *
 * Two questions get asked here and they are not interchangeable:
 *
 *   confirm      -- did Fork read this PDF correctly?
 *   acknowledge  -- these confirmed documents disagree; proceed anyway?
 *
 * The second can't even be asked until both documents are confirmed, which is
 * why confirming the current audit never implies it.
 */
export default function WhatIfPanel({
  session,
  documents,
  onSession,
  optionLabel,
  selectedProgramKey,
}: {
  session: AuditSession;
  documents: DocumentsState;
  onSession: (s: AuditSession) => void;
  /** The option currently on screen. A document supplies credits only to
   * its own program; when that isn't the selected one the document is
   * dormant, and saying so beats implying it applied. */
  selectedProgramKey: string;
  /** How the matched program is named in the form, so the two agree. */
  optionLabel: (programKey: string) => string;
}) {
  const [busy, setBusy] = useState<null | "uploading" | "confirming" | "acknowledging">(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const { what_if: whatIf, resolved } = documents;
  const classification = whatIf.classification;
  const match = classification?.match ?? null;

  async function run(
    kind: "uploading" | "confirming" | "acknowledging",
    fn: () => Promise<AuditSession>,
    fallback: string,
  ) {
    setBusy(kind);
    setError(null);
    try {
      onSession(await fn());
    } catch (e) {
      // A failed step leaves the previous documents and the calculated
      // decision exactly as they were.
      setError(e instanceof ApiError ? e.message : fallback);
    } finally {
      setBusy(null);
    }
  }

  function handleFile(file: File) {
    if (!looksLikePdf(file)) {
      setError("Fork reads degree audits saved as PDF. That file isn't one.");
      return;
    }
    run("uploading", () => uploadWhatIf(session.session_id, file), "Couldn't read that file.");
  }

  const documentName = classification
    ? [
        "UNT What-If Audit",
        classification.program_name,
        classification.catalog_year,
      ]
        .filter(Boolean)
        .join(" — ")
    : "What-If audit";

  return (
    <div className="space-y-2.5 border-t border-white/[0.07] pt-4">
      <p className="text-[10.5px] uppercase tracking-[0.15em] text-slate-500">
        What-If audit
      </p>

      {!whatIf.present && busy !== "uploading" && (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            const file = e.dataTransfer.files?.[0];
            if (file) handleFile(file);
          }}
          className={`rounded-xl border border-dashed px-3 py-3.5 text-center transition ${
            dragging
              ? "border-cyan-400/60 bg-cyan-500/[0.06]"
              : "border-white/[0.12] bg-white/[0.02]"
          }`}
        >
          <p className="text-[12.5px] leading-relaxed text-slate-400">
            Drop a What-If audit here, or{" "}
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              className="cursor-pointer font-semibold text-cyan-400 underline-offset-2 hover:underline"
            >
              choose a file
            </button>
            .
          </p>
          <p className="mt-1.5 text-[11px] leading-relaxed text-slate-600">
            Optional. Run one in myUNT for the major you&apos;re considering and
            Fork can use its figures instead of asking you to estimate.
          </p>
        </div>
      )}

      {busy === "uploading" && (
        <p role="status" className="text-[12.5px] text-slate-300">
          Reading your What-If audit…
        </p>
      )}

      {whatIf.present && (
        <div className="space-y-2 rounded-xl border border-white/[0.09] bg-white/[0.02] p-3">
          <p className="break-words text-[12.5px] leading-relaxed text-slate-200">
            {documentName}
          </p>

          {/* Ambiguous means the program didn't resolve to exactly one major.
              Saying which, rather than silently supplying nothing. */}
          {match?.quality === "ambiguous" && (
            <p className="rounded-lg border border-amber-400/25 bg-amber-400/[0.07] px-2.5 py-2 text-[11.5px] leading-relaxed text-amber-200/90">
              Fork can&apos;t tell which program this audit is for
              {match.candidates.length > 0
                ? `. It could be ${match.candidates.map(optionLabel).join(" or ")}.`
                : "."}{" "}
              You can still enter the figure yourself.
            </p>
          )}

          {!whatIf.confirmed && match?.quality === "exact" && (
            <>
              <p className="text-[12px] leading-relaxed text-slate-400">
                Does this look like the right document for{" "}
                {optionLabel(match.program_key!)}?
              </p>
              <button
                type="button"
                disabled={busy === "confirming"}
                onClick={() =>
                  run(
                    "confirming",
                    () => confirmDocument(session.session_id, "what_if"),
                    "Couldn't confirm that document.",
                  )
                }
                className="cursor-pointer rounded-lg bg-cyan-500/90 px-3 py-1.5 text-[12px] font-semibold text-slate-950 transition hover:bg-cyan-400 disabled:opacity-40"
              >
                {busy === "confirming" ? "Applying…" : "Use this What-If audit"}
              </button>
            </>
          )}

          {/* Discrepancies are shown in full, never summarised into a count.
              The point is that the student reads them and decides. */}
          {resolved.requires_acknowledgement && (
            <div className="space-y-2">
              {resolved.discrepancies.map((d) => (
                <p
                  key={d.code + d.magnitude}
                  className="rounded-lg border border-amber-400/25 bg-amber-400/[0.07] px-2.5 py-2 text-[11.5px] leading-relaxed text-amber-200/90"
                >
                  {d.user_message}
                </p>
              ))}
              <button
                type="button"
                disabled={busy === "acknowledging" || !documents.evidence_fingerprint}
                onClick={() =>
                  run(
                    "acknowledging",
                    () =>
                      acknowledgeDiscrepancies(
                        session.session_id,
                        documents.evidence_fingerprint!,
                      ),
                    "Couldn't record that. Your documents may have changed — take another look.",
                  )
                }
                className="cursor-pointer rounded-lg border border-amber-400/40 px-3 py-1.5 text-[12px] text-amber-200 transition hover:bg-amber-400/10 disabled:opacity-40"
              >
                {busy === "acknowledging" ? "Saving…" : "I've read this — use both documents"}
              </button>
            </div>
          )}

          {resolved.option_credits &&
            resolved.option_credits.program_key === selectedProgramKey && (
              <p className="rounded-lg border border-emerald-400/25 bg-emerald-400/[0.06] px-2.5 py-2 text-[11.5px] leading-relaxed text-emerald-200/90">
                Using {resolved.option_credits.credits_transferable} credits toward{" "}
                {optionLabel(resolved.option_credits.program_key)}, from this audit.
              </p>
            )}

          {/* Stored, resolvable, and not for the option on screen. Reporting
              it as applied -- which an earlier version did -- put a
              Psychology figure under a field labelled Information
              Technology. */}
          {resolved.option_credits &&
            resolved.option_credits.program_key !== selectedProgramKey && (
              <p className="rounded-lg border border-white/10 bg-white/[0.02] px-2.5 py-2 text-[11.5px] leading-relaxed text-slate-400">
                Kept for {optionLabel(resolved.option_credits.program_key)}. It
                isn&apos;t used while you&apos;re considering{" "}
                {optionLabel(selectedProgramKey)} — switch to it and Fork will
                use these figures.
              </p>
            )}

          {/* Reasons a present document still supplies nothing. Shown rather
              than leaving the student to wonder why the field didn't change. */}
          {resolved.unresolved.map((reason) => (
            <p key={reason} className="text-[11px] leading-relaxed text-slate-500">
              {reason}
            </p>
          ))}
        </div>
      )}

      {error && (
        <p
          role="alert"
          className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2.5 text-[12.5px] leading-relaxed text-rose-300"
        >
          {error}
        </p>
      )}

      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          // Reset first: picking the same file twice fires no change event
          // otherwise, so a retry after an error would look like nothing
          // happened.
          e.target.value = "";
          if (file) handleFile(file);
        }}
      />
    </div>
  );
}