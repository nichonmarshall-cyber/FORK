"use client";

/**
 * Sign in / create account, in one card with two tabs.
 *
 * Errors come back from the backend already written for a person (and one
 * message for "wrong password" and "no such account", so the form can't be
 * used to find out who has signed up).
 */

import { useId, useState } from "react";
import { ApiError } from "@/lib/types";
import { Student, login, register } from "@/lib/notebook";

type Mode = "sign_in" | "create";

export default function AuthPanel({
  onSignedIn,
  initialMode = "sign_in",
}: {
  onSignedIn: (student: Student) => void;
  initialMode?: Mode;
}) {
  const [mode, setMode] = useState<Mode>(initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const errorId = useId();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (mode === "create" && password.length < 10) {
      setError("Use a password of at least 10 characters.");
      return;
    }
    setBusy(true);
    try {
      const student =
        mode === "create" ? await register(email, password, name) : await login(email, password);
      setPassword("");
      onSignedIn(student);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  const tab = (value: Mode, label: string) => (
    <button
      type="button"
      role="tab"
      aria-selected={mode === value}
      onClick={() => {
        setMode(value);
        setError(null);
      }}
      className={`flex-1 rounded-lg px-3 py-1.5 text-[12.5px] font-medium transition ${
        mode === value ? "bg-cyan-400/10 text-cyan-300" : "text-slate-500 hover:text-slate-300"
      }`}
    >
      {label}
    </button>
  );

  return (
    <div className="rounded-2xl border border-white/[0.07] bg-[#0a0e17] p-5">
      <div role="tablist" aria-label="Account" className="flex gap-1 rounded-xl border border-white/[0.07] bg-white/[0.02] p-1">
        {tab("sign_in", "Sign in")}
        {tab("create", "Create account")}
      </div>

      <form onSubmit={submit} className="mt-5 space-y-4" noValidate>
        {mode === "create" && (
          <Field label="What should Fork call you? (optional)">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoComplete="given-name"
              maxLength={80}
              className={INPUT}
            />
          </Field>
        )}
        <Field label="Email">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            required
            aria-describedby={error ? errorId : undefined}
            className={INPUT}
          />
        </Field>
        <Field
          label="Password"
          hint={mode === "create" ? "At least 10 characters." : undefined}
        >
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === "create" ? "new-password" : "current-password"}
            required
            aria-describedby={error ? errorId : undefined}
            className={INPUT}
          />
        </Field>

        {error && (
          <p
            id={errorId}
            role="alert"
            className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-[12.5px] text-rose-300"
          >
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-xl bg-cyan-500/90 px-4 py-2.5 text-[13.5px] font-semibold text-slate-950 shadow-[0_0_22px_-6px_#22d3ee] transition hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {busy ? "One moment…" : mode === "create" ? "Create my notebook" : "Sign in"}
        </button>
        {mode === "create" && (
          <p className="text-[11.5px] leading-relaxed text-slate-500">
            Fork keeps your notebook until you delete it. You can delete your account and
            everything in it at any time from your account page.
          </p>
        )}
      </form>
    </div>
  );
}

export const INPUT =
  "mt-1.5 w-full rounded-lg border border-white/10 bg-[#0e141f] px-3 py-2 text-[13px] text-slate-200 outline-none focus:border-cyan-400/50";

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-[10.5px] uppercase tracking-[0.15em] text-slate-500">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-slate-600">{hint}</span>}
    </label>
  );
}
