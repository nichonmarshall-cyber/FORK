"use client";

import Link from "next/link";
import type { Student } from "@/lib/notebook";

export type TopBarSection = "notebook" | "compare" | "account";

/**
 * Site navigation. Signed in, it links the notebook, the compare tool, and
 * the account page; signed out, it offers sign-in without blocking the
 * anonymous compare tool.
 */
export default function TopBar({
  student,
  current,
  onSignOut,
}: {
  student: Student | null;
  current: TopBarSection;
  onSignOut?: () => void;
}) {
  const link = (href: string, label: string, section: TopBarSection) => (
    <Link
      href={href}
      aria-current={current === section ? "page" : undefined}
      className={`rounded-lg px-3 py-1.5 text-[13px] transition ${
        current === section
          ? "bg-cyan-400/10 font-medium text-cyan-300"
          : "text-slate-400 hover:text-slate-200"
      }`}
    >
      {label}
    </Link>
  );

  return (
    <header className="border-b border-white/[0.06] bg-[#05070d]/90">
      <div className="mx-auto flex max-w-[1240px] flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div className="flex items-center gap-4">
          <Link href="/" aria-label="Fork home" className="flex items-center">
            {/* eslint-disable-next-line @next/next/no-img-element -- tiny static asset */}
            <img src="/fork-logo.png" alt="Fork" className="h-6 w-auto select-none" draggable={false} />
          </Link>
          <nav aria-label="Main" className="flex items-center gap-1">
            {student ? link("/", "Notebook", "notebook") : null}
            {link("/compare", "Compare paths", "compare")}
          </nav>
        </div>
        <div className="flex items-center gap-2 text-[12.5px]">
          {student ? (
            <>
              <Link
                href="/account"
                aria-current={current === "account" ? "page" : undefined}
                className="max-w-[200px] truncate text-slate-400 hover:text-slate-200"
                title={student.email}
              >
                {student.display_name || student.email}
              </Link>
              {student.is_demo && (
                <span className="rounded-full border border-amber-300/30 bg-amber-300/10 px-2 py-0.5 text-[10.5px] uppercase tracking-[0.1em] text-amber-200">
                  Demo
                </span>
              )}
              {onSignOut && (
                <button
                  type="button"
                  onClick={onSignOut}
                  className="rounded-lg border border-white/10 px-2.5 py-1 text-slate-400 hover:text-slate-200"
                >
                  Sign out
                </button>
              )}
            </>
          ) : (
            <Link
              href="/"
              className="rounded-lg border border-white/10 px-2.5 py-1 text-slate-300 hover:border-cyan-400/40 hover:text-cyan-200"
            >
              Sign in
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}
