"use client";

import { useRef, useState } from "react";
import {
  AuditSession,
  CorrectionRequest,
  ReviewSummary,
  confirmAudit,
  fetchSession,
  looksLikePdf,
  revertToManual,
  saveCorrections,
  uploadAudit,
} from "@/lib/audit";
import CourseReviewDialog from "./CourseReviewDialog";
import { ApiError } from "@/lib/types";

/**
 * Upload a degree audit, look at what Fork read, confirm or discard it.
 *
 * Three states, and which one shows is derived from the session rather than
 * tracked separately, so the UI can't disagree with the backend about where
 * the record stands:
 *
 *   no session            -> the dropzone
 *   awaiting_review       -> the review card, manual entry still active
 *   is_active             -> the confirmed banner, with a way back
 *
 * The middle state is the one that matters. A parsed record exists while the
 * student's own numbers are still driving the calculation, and nothing is
 * touched until they say the reading is right.
 */
export default function AuditPanel({
  session,
  onSession,
  onConfirmed,
  onReverted,
  onCorrected,
}: {
  session: AuditSession | null;
  onSession: (s: AuditSession | null) => void;
  /** Fires once the student confirms. The parent decides what to do with
   * the figures — this component never writes to the form itself. */
  onConfirmed: (s: AuditSession) => void;
  onReverted: () => void;
  /** Fires after corrections save. Confirmed figures may have moved, so the
   * parent re-syncs its inputs -- corrections don't reach the calculation
   * until the record is confirmed again. */
  onCorrected: () => void;
}) {
  const [busy, setBusy] = useState<null | "uploading" | "confirming" | "reverting">(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  // Keyed `${courseKey}:${field}` so each message renders beside the input
  // that caused it rather than as one banner over a 36-row form.
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleFile(file: File) {
    setError(null);

    if (!looksLikePdf(file)) {
      setError("Fork reads degree audits saved as PDF. That file isn't one.");
      return;
    }

    setBusy("uploading");
    try {
      onSession(await uploadAudit(file));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong reading that file.");
    } finally {
      setBusy(null);
    }
  }

  async function handleConfirm() {
    if (!session) return;
    setBusy("confirming");
    setError(null);
    try {
      const next = await confirmAudit(session.session_id);
      onSession(next);
      onConfirmed(next);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't confirm that record.");
    } finally {
      setBusy(null);
    }
  }

  async function handleRevert() {
    if (!session) {
      // Cancelling a review that was never confirmed needs no round trip —
      // nothing on the server changed, and the manual values were never
      // touched.
      onSession(null);
      onReverted();
      return;
    }
    setBusy("reverting");
    setError(null);
    try {
      await revertToManual(session.session_id);
      onSession(null);
      onReverted();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't switch back to manual entry.");
    } finally {
      setBusy(null);
    }
  }

  async function handleReopen() {
    if (!session) return;
    // Refetched rather than reusing local state: the server record is
    // authoritative and may have changed since this component last saw it.
    try {
      onSession(await fetchSession(session.session_id));
    } catch {
      // A failed refetch shouldn't block review -- fall through to what we
      // already have rather than showing nothing.
    }
    setDialogOpen(true);
  }

  async function handleSaveCorrections(corrections: CorrectionRequest[]) {
    if (!session) return;
    setSaving(true);
    setError(null);
    try {
      const next = await saveCorrections(session.session_id, corrections);
      const errors: Record<string, string> = {};
      for (const r of next.rejected) {
        errors[`${r.course_key ?? ""}:${r.field}`] = r.message ?? "Couldn't apply that change.";
      }
      setFieldErrors(errors);
      onSession(next);
      // Stay open when something was rejected so the student can see which
      // field and fix it, rather than closing on a partial save.
      if (next.rejected.length === 0) {
        setDialogOpen(false);
        onCorrected();
      }
    } catch (e) {
      // A failed save must not destroy the record or the calculated
      // decision -- the previous session object is left exactly as it was.
      setError(e instanceof ApiError ? e.message : "Couldn't save those corrections.");
    } finally {
      setSaving(false);
    }
  }

  const review = session?.review;
  const confirmed = session?.uploaded_source.is_active ?? false;
  const awaiting = session?.uploaded_source.awaiting_review ?? false;

  return (
    <div className="space-y-3 border-t border-white/[0.07] pt-5">
      <p className="text-[10.5px] uppercase tracking-[0.15em] text-slate-500">
        Degree audit
      </p>

      {!session && !busy && (
        <Dropzone
          dragging={dragging}
          onDragStateChange={setDragging}
          onFile={handleFile}
          onBrowse={() => inputRef.current?.click()}
        />
      )}

      {busy === "uploading" && <Working />}

      {review && awaiting && !busy && (
        <ReviewCard
          review={review}
          onOpenDialog={() => setDialogOpen(true)}
          onConfirm={handleConfirm}
          onCancel={handleRevert}
        />
      )}

      {busy === "confirming" && (
        <p className="text-[12px] text-slate-400">Applying your audit…</p>
      )}

      {confirmed && busy !== "reverting" && (
        <ConfirmedBanner
          review={review}
          onReview={handleReopen}
          onRevert={handleRevert}
        />
      )}

      {busy === "reverting" && (
        <p className="text-[12px] text-slate-400">Switching back to manual entry…</p>
      )}

      {error && (
        <p
          role="alert"
          className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2.5 text-[12.5px] leading-relaxed text-rose-300"
        >
          {error}
        </p>
      )}

      {review && (
        <CourseReviewDialog
          // Remounts on each open so staged edits never survive a close.
          key={dialogOpen ? "open" : "closed"}
          review={review}
          open={dialogOpen}
          saving={saving}
          fieldErrors={fieldErrors}
          onClose={() => setDialogOpen(false)}
          onSave={handleSaveCorrections}
        />
      )}

      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          // Reset first: picking the same file twice in a row fires no
          // change event otherwise, so a retry after an error would look
          // like nothing happened.
          e.target.value = "";
          if (file) handleFile(file);
        }}
      />
    </div>
  );
}

function Dropzone({
  dragging,
  onDragStateChange,
  onFile,
  onBrowse,
}: {
  dragging: boolean;
  onDragStateChange: (v: boolean) => void;
  onFile: (f: File) => void;
  onBrowse: () => void;
}) {
  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        onDragStateChange(true);
      }}
      onDragLeave={() => onDragStateChange(false)}
      onDrop={(e) => {
        e.preventDefault();
        onDragStateChange(false);
        const file = e.dataTransfer.files?.[0];
        if (file) onFile(file);
      }}
      className={`rounded-xl border border-dashed px-3 py-4 text-center transition ${
        dragging
          ? "border-cyan-400/60 bg-cyan-500/[0.06]"
          : "border-white/[0.12] bg-white/[0.02]"
      }`}
    >
      <p className="text-[12.5px] leading-relaxed text-slate-400">
        Drop your UNT degree audit here, or{" "}
        <button
          type="button"
          onClick={onBrowse}
          className="cursor-pointer font-semibold text-cyan-400 underline-offset-2 hover:underline"
        >
          choose a file
        </button>
        .
      </p>
      <p className="mt-1.5 text-[11px] leading-relaxed text-slate-600">
        Optional. Fork reads it in memory and never stores it. You&apos;ll see
        what it found before anything changes.
      </p>
    </div>
  );
}

/**
 * One honest line rather than invented stages.
 *
 * The backend parses in a single call and can't report which part it's on,
 * so a three-step progress display would be theatre — and this finishes in
 * well under a second on a real audit anyway.
 */
function Working() {
  return (
    <div className="flex items-center gap-2.5 rounded-xl border border-white/[0.07] bg-white/[0.02] px-3 py-3">
      <span
        aria-hidden
        className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-cyan-400/30 border-t-cyan-400"
      />
      <p role="status" className="text-[12.5px] text-slate-300">
        Reading your degree audit…
      </p>
    </div>
  );
}

function ReviewCard({
  review,
  onOpenDialog,
  onConfirm,
  onCancel,
}: {
  review: ReviewSummary;
  onOpenDialog: () => void;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="space-y-3 rounded-xl border border-white/[0.09] bg-white/[0.02] p-3.5">
      <p className="text-[12.5px] leading-relaxed text-slate-200">
        {review.headline}
      </p>

      <dl className="space-y-1.5">
        {review.checkpoints.map((c) => (
          <div key={c.key} className="flex justify-between gap-4 text-[12.5px]">
            <dt className="text-slate-500">{c.label}</dt>
            <dd
              className={`shrink-0 text-slate-200 ${
                c.kind === "hours" ? "tabular-nums" : ""
              }`}
            >
              {c.value}
              {c.unit ? ` ${c.unit}` : ""}
            </dd>
          </div>
        ))}
        <div className="flex justify-between gap-4 text-[12.5px]">
          <dt className="text-slate-500">Courses read</dt>
          <dd className="shrink-0 tabular-nums text-slate-200">
            {review.course_count}
          </dd>
        </div>
      </dl>

      {/* Notices are shown, never collapsed behind a toggle. Hiding a
          limitation to make the card look tidy is the one thing this
          screen must not do. */}
      {review.notices.map((n) => (
        <p
          key={n}
          className="rounded-lg border border-amber-400/25 bg-amber-400/[0.07] px-2.5 py-2 text-[11.5px] leading-relaxed text-amber-200/90"
        >
          {n}
        </p>
      ))}

      {/* Opens the pop-out rather than expanding here. 36 courses in a
          320px column produced nested scrollbars and cropped titles. */}
      <button
        type="button"
        onClick={onOpenDialog}
        className="cursor-pointer text-[11.5px] text-slate-500 underline-offset-2 hover:text-slate-300 hover:underline"
      >
        Review or edit the {review.course_count} courses Fork read
      </button>

      <div className="flex gap-2 pt-0.5">
        <button
          type="button"
          onClick={onConfirm}
          className="flex-1 cursor-pointer rounded-lg bg-cyan-500/90 px-3 py-2 text-[12.5px] font-semibold text-slate-950 transition hover:bg-cyan-400"
        >
          Use this degree audit
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="cursor-pointer rounded-lg border border-white/10 px-3 py-2 text-[12.5px] text-slate-300 transition hover:border-white/20 hover:text-slate-100"
        >
          Keep manual entry
        </button>
      </div>
    </div>
  );
}

function ConfirmedBanner({
  review,
  onReview,
  onRevert,
}: {
  review: ReviewSummary | undefined;
  onReview: () => void;
  onRevert: () => void;
}) {
  return (
    <div className="space-y-2 rounded-xl border border-emerald-400/25 bg-emerald-400/[0.06] p-3">
      {/* "Confirmed by you", never "verified". Fork checked that its own
          reading matches what the student says is true; it has not checked
          anything with UNT, and this line is where that distinction is
          most likely to get blurred. */}
      <p className="text-[12.5px] leading-relaxed text-emerald-200/90">
        Using the degree audit you confirmed
        {review?.prepared_at ? `, prepared ${review.prepared_at}` : ""}.
      </p>
      <div className="flex flex-wrap gap-x-3 gap-y-1">
        <button
          type="button"
          onClick={onReview}
          className="cursor-pointer text-[11.5px] text-slate-400 underline-offset-2 hover:text-slate-200 hover:underline"
        >
          Review or correct audit
        </button>
        <button
          type="button"
          onClick={onRevert}
          className="cursor-pointer text-[11.5px] text-slate-400 underline-offset-2 hover:text-slate-200 hover:underline"
        >
          Remove document and use manual entry
        </button>
      </div>
    </div>
  );
}