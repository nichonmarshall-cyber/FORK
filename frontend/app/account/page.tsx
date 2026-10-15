"use client";

/**
 * Account: who's signed in, what Fork keeps, and how to delete all of it.
 */

import Link from "next/link";
import { useEffect, useId, useState } from "react";
import TopBar from "@/components/notebook/TopBar";
import { Field, INPUT } from "@/components/notebook/AuthPanel";
import { shortDate } from "@/lib/format";
import { ApiError } from "@/lib/types";
import { Student, deleteAccount, getMe, logout } from "@/lib/notebook";

export default function AccountPage() {
  const [student, setStudent] = useState<Student | null | undefined>(undefined);
  const [deleted, setDeleted] = useState(false);

  useEffect(() => {
    getMe()
      .then(setStudent)
      .catch(() => setStudent(null));
  }, []);

  async function signOut() {
    try {
      await logout();
    } finally {
      setStudent(null);
    }
  }

  return (
    <div className="min-h-screen w-full bg-[#05070d] text-slate-200">
      <TopBar student={student ?? null} current="account" onSignOut={signOut} />
      <main className="mx-auto max-w-[720px] space-y-4 px-4 pb-16 pt-8">
        <h1 className="text-[22px] font-semibold tracking-tight text-slate-100">Your account</h1>

        {student === undefined && <p role="status" className="text-[13px] text-slate-500">Loading…</p>}

        {deleted && (
          <p role="status" className="rounded-xl border border-emerald-400/30 bg-emerald-400/10 px-3 py-2.5 text-[13px] text-emerald-200">
            Your account and everything in your notebook have been deleted.
          </p>
        )}

        {student === null && !deleted && (
          <p className="text-[13px] text-slate-400">
            You&rsquo;re not signed in.{" "}
            <Link href="/" className="text-cyan-300 hover:underline">
              Sign in
            </Link>
          </p>
        )}

        {student && (
          <>
            <section className="rounded-2xl border border-white/[0.07] bg-[#0a0e17] p-5">
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-[13px]">
                <dt className="text-slate-500">Email</dt>
                <dd className="text-slate-200">{student.email}</dd>
                {student.display_name && (
                  <>
                    <dt className="text-slate-500">Name</dt>
                    <dd className="text-slate-200">{student.display_name}</dd>
                  </>
                )}
                <dt className="text-slate-500">Notebook started</dt>
                <dd className="text-slate-200">{shortDate(student.created_at)}</dd>
              </dl>
            </section>

            <section className="rounded-2xl border border-white/[0.07] bg-[#0a0e17] p-5">
              <h2 className="text-[15px] font-semibold text-slate-100">What Fork keeps</h2>
              <ul className="mt-3 list-disc space-y-1.5 pl-5 text-[12.5px] leading-relaxed text-slate-400">
                <li>Your account email, name, and a scrambled (hashed) form of your password.</li>
                <li>
                  The academic facts in your notebook and where each came from: completed and
                  in-progress hours, catalog year, program, requirement counts, What-If
                  figures, and anything you entered yourself.
                </li>
                <li>
                  A summary of each document you added. For degree audits Fork keeps what it
                  read and you confirmed — not your course-by-course grade history, and not
                  the PDF.
                </li>
                <li>Your saved comparisons, the plan you marked, and your academic journey.</li>
              </ul>
              <p className="mt-3 text-[12.5px] leading-relaxed text-slate-400">
                Fork keeps this until you delete it. Deleting your account removes all of it
                permanently.
              </p>
            </section>

            {student.is_demo ? (
              <p className="text-[12.5px] text-slate-400">
                This is the shared demo account for a fictional student, so it can&rsquo;t be
                changed or deleted. Sign out and create your own to keep a real notebook.
              </p>
            ) : (
              <DeleteAccount
                onDeleted={() => {
                  setDeleted(true);
                  setStudent(null);
                }}
              />
            )}
          </>
        )}
      </main>
    </div>
  );
}

function DeleteAccount({ onDeleted }: { onDeleted: () => void }) {
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const warningId = useId();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await deleteAccount(password);
      onDeleted();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't delete your account.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-2xl border border-rose-500/20 bg-[#0a0e17] p-5">
      <h2 className="text-[15px] font-semibold text-slate-100">Delete account</h2>
      <p id={warningId} className="mt-1 text-[12.5px] leading-relaxed text-slate-400">
        Permanently deletes your account, documents, saved comparisons, and journey. This
        can&rsquo;t be undone.
      </p>
      {!open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="mt-3 rounded-lg border border-rose-500/40 px-3 py-1.5 text-[12.5px] text-rose-300 hover:bg-rose-500/10"
        >
          Delete my account…
        </button>
      ) : (
        <form onSubmit={submit} className="mt-3 space-y-3" noValidate>
          <Field label="Enter your password to confirm">
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              aria-describedby={warningId}
              className={INPUT}
            />
          </Field>
          {error && (
            <p role="alert" className="text-[12.5px] text-rose-300">
              {error}
            </p>
          )}
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={busy || !password}
              className="rounded-lg bg-rose-500/90 px-3 py-1.5 text-[12.5px] font-semibold text-white hover:bg-rose-500 disabled:opacity-50"
            >
              {busy ? "Deleting…" : "Permanently delete everything"}
            </button>
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                setPassword("");
                setError(null);
              }}
              className="rounded-lg px-3 py-1.5 text-[12.5px] text-slate-400 hover:text-slate-200"
            >
              Cancel
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
