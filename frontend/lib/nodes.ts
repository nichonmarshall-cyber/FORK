/**
 * The decision map: what nodes exist, where they sit, and — importantly —
 * where each one's number comes from.
 *
 * A node is only "completed" if the engine actually produced a value for it.
 * Everything else is "needs info" (we could get it, we don't have it yet) or
 * "locked" (the platform can't answer this yet, and says so). Locked nodes
 * are not placeholders for a future demo — they're the honest answer to
 * "why isn't this filled in", and each one carries its reason.
 */

import { CalcResult, LineItem, findLineItem } from "./types";

export type NodeState =
  | "completed"
  | "at_risk"
  | "needs_info"
  | "locked"
  | "idle";

export type BranchId =
  | "center"
  | "academic"
  | "financial"
  | "career"
  | "graduation"
  | "approval";

export const BRANCH_COLOR: Record<BranchId, string> = {
  center: "#22d3ee",
  academic: "#34d399",
  financial: "#38bdf8",
  career: "#fb923c",
  graduation: "#a855f7",
  approval: "#facc15",
};

export interface ResolvedNode {
  state: NodeState;
  /** Short value shown in the panel headline, already formatted. */
  display?: string;
  /** The engine line item behind it, if any — this is what powers provenance. */
  lineItem?: LineItem;
  /** Why this node can't be answered, when it can't. */
  reason?: string;
  /**
   * The figures this value was derived from. A number that says "calculated
   * from the two salary figures above" is useless if those figures aren't
   * shown, so derived nodes carry their inputs with them.
   */
  derivedFrom?: LineItem[];
  /** Facts already established for this node, shown as "What we know". */
  known?: string[];
  /** What would fill this in, shown as "What we still need". */
  stillNeed?: string[];
  /**
   * Caveats about the DATA itself, shown as a always-visible "Data
   * limitation" section rather than buried inside the collapsible
   * provenance block. A limitation the student never opens is a
   * limitation that wasn't really disclosed.
   *
   * Text comes from the API response, never hardcoded here — different
   * majors carry different caveats and a single universal warning would
   * be wrong for most of them.
   */
  dataLimitations?: string[];
  /**
   * Extra figures worth showing but NOT part of the calculation — e.g.
   * the 4- and 5-year earnings trajectory. Generic on purpose so any node
   * can supply supporting numbers without the panel needing to know which
   * node it's rendering.
   */
  contextGroups?: ContextGroup[];
}

export interface ContextRow {
  label: string;
  /** Pre-formatted for display, or the plain-English absence text. */
  value: string;
  /** Why a value is absent, when it is. */
  note?: string;
  /** Renders muted when the figure isn't a real number. */
  muted?: boolean;
}

export interface ContextGroup {
  title: string;
  rows: ContextRow[];
  /** Source line shown under the group. */
  source?: string;
}

export interface NodeDef {
  id: string;
  label: string;
  x: number;
  y: number;
  branch: BranchId;
  kind: "center" | "hub" | "leaf";
  /** Parent node id — used to draw the connector. */
  parent?: string;
  /** What this node is asking, in the student's words. */
  question: string;
  /** Glyph drawn inside hub nodes. Keys map to paths in DecisionMap. */
  icon?: "leaf" | "book" | "dollar" | "briefcase" | "calendar" | "check";
  resolve: (r: CalcResult | null) => ResolvedNode;
}

// --- formatting helpers ------------------------------------------------

const money = (n: number) =>
  `${n < 0 ? "−" : ""}$${Math.abs(n).toLocaleString("en-US", {
    maximumFractionDigits: 0,
  })}`;

const semesters = (n: number) => {
  const abs = Math.abs(n);
  const unit = abs === 1 ? "semester" : "semesters";
  if (n === 0) return "No change";
  return n > 0 ? `+${abs} ${unit}` : `−${abs} ${unit} (sooner)`;
};

const credits = (n: number) => `${n} credit${n === 1 ? "" : "s"}`;

// --- earnings helpers ---------------------------------------------------
// These read from result.earnings_context, which the backend builds from
// the processed College Scorecard file. Nothing about any specific major is
// encoded here: whether a figure is shared across programs, suppressed, or
// missing is the data's business, not this file's.

/** Plain-English caveats for the majors involved, straight from the API. */
function earningsLimitations(r: CalcResult, onlyMajors?: string[]): string[] {
  const contexts = onlyMajors
    ? r.earnings_context.filter((c) => onlyMajors.includes(c.major))
    : r.earnings_context;

  const out: string[] = [];

  // Who the figures actually describe. Identical across majors, so it's
  // stated once rather than repeated per program.
  const population = contexts.find((c) => c.population_note)?.population_note;
  if (population) out.push(population);

  // Where one federal category covers more than the single program the
  // student picked. Only present when it genuinely applies.
  for (const c of contexts) {
    if (c.covers) out.push(`${c.major}: ${c.covers}`);
  }

  // Figures that exist but can't be shown, and figures that don't exist.
  // Kept as distinct states — they mean different things.
  for (const c of contexts) {
    for (const t of c.trajectory) {
      if (t.status !== "available" && t.status_note) {
        out.push(`${c.major} — ${t.label.toLowerCase()}: ${t.status_note}`);
      }
    }
  }

  return out;
}

/** The 1/4/5-year trajectory for one major, formatted for display. */
function earningsGroup(r: CalcResult, major: string): ContextGroup | undefined {
  const ctx = r.earnings_context.find((c) => c.major === major);
  if (!ctx) return undefined;

  return {
    title: major,
    source: `${ctx.source} · ${ctx.source_date}`,
    rows: ctx.trajectory.map((t) => {
      if (t.status === "available" && t.value !== null) {
        return { label: t.label, value: money(t.value) };
      }
      // Never $0, and the two absence states stay distinguishable.
      return {
        label: t.label,
        value:
          t.status === "privacy_suppressed" ? "Not published" : "Not reported",
        note: t.status_note ?? undefined,
        muted: true,
      };
    }),
  };
}

/** One sentence comparing the two majors, or an honest note if we can't. */
function earningsComparison(r: CalcResult): string {
  const delta = r.summary.annual_salary_delta;
  const cur = r.summary.current_major;
  const pro = r.summary.prospective_major;

  if (delta === null || delta === undefined) {
    return `Fork can't compare early-career earnings for ${cur} and ${pro} because at least one of them has no published figure.`;
  }
  if (delta === 0) {
    return `Graduates of ${cur} and ${pro} report the same median earnings one year after graduating.`;
  }
  const dir = delta > 0 ? "more" : "less";
  return `One year after graduating, ${pro} graduates report a median of ${money(
    Math.abs(delta),
  )} ${dir} per year than ${cur} graduates. This is a median across a group, not a prediction for any individual.`;
}

/** A node the platform cannot answer yet. */
const locked = (reason: string) => (): ResolvedNode => ({
  state: "locked",
  reason,
});

/** A node that needs something from the student before it can be answered. */
const needsInfo = (reason: string) => (): ResolvedNode => ({
  state: "needs_info",
  reason,
});

const idle: ResolvedNode = { state: "idle" };

// --- the map -----------------------------------------------------------

export const NODES: NodeDef[] = [
  {
    id: "root",
    label: "Change Major",
    x: 500,
    y: 360,
    branch: "center",
    kind: "center",
    question: "What does switching actually cost me?",
    icon: "leaf",
    resolve: (r) =>
      !r
        ? idle
        : {
            // A cost increase isn't a verdict, but it is worth flagging as
            // moving against the student rather than rendering it identically
            // to a saving.
            state: r.summary.incremental_total_cost > 0 ? "at_risk" : "completed",
            display: money(r.summary.incremental_total_cost),
            lineItem: findLineItem(r, "Estimated total difference"),
            derivedFrom: [
              findLineItem(r, "Additional tuition"),
              // Label renamed in Stage 4. The old fragment silently matched
              // nothing, so this node was quietly showing one input instead
              // of two — no error, just a missing row.
              findLineItem(r, "Estimated early-career income delayed"),
            ].filter(Boolean) as LineItem[],
            dataLimitations: earningsLimitations(r, [
              r.summary.current_major,
            ]),
            known: [
              `Current major: ${r.summary.current_major}`,
              `Considering: ${r.summary.prospective_major}`,
              `Additional semesters: ${r.summary.incremental_semesters}`,
            ],
          },
  },

  // --- Academic ---------------------------------------------------------
  {
    id: "academic",
    label: "Academic Requirements",
    x: 272,
    y: 300,
    branch: "academic",
    kind: "hub",
    parent: "root",
    question: "What coursework carries over, and what doesn't?",
    icon: "book",
    resolve: (r) =>
      !r
        ? idle
        : {
            state: r.summary.credits_lost > 0 ? "at_risk" : "completed",
            display: credits(r.summary.credits_lost) + " lost",
            lineItem: findLineItem(r, "count toward nothing"),
            derivedFrom: [
              findLineItem(r, "Credits already completed"),
              findLineItem(r, "Credits that transfer"),
            ].filter(Boolean) as LineItem[],
            known: [
              `Completed: ${r.comparison.staying.line_items[1]?.value ?? "—"} credits`,
              `Transferring: ${r.comparison.switching.line_items[1]?.value ?? "—"} credits`,
            ],
          },
  },
  {
    id: "credit_transfer",
    label: "Credit Transfer",
    x: 122,
    y: 372,
    branch: "academic",
    kind: "leaf",
    parent: "academic",
    question: "How many of my completed credits count toward the new degree?",
    resolve: (r) => {
      if (!r) return idle;
      const li = findLineItem(r, "Credits that transfer");
      // A student's own estimate is not the registrar's answer. Say so.
      const isEstimate =
        li?.source.toLowerCase().includes("student-reported") ||
        li?.source.toLowerCase().includes("estimate");
      return {
        state: isEstimate ? "needs_info" : "completed",
        display: li && li.value !== null ? credits(li.value) : undefined,
        lineItem: li,
        reason: isEstimate
          ? "This figure is your own estimate. A what-if degree audit run against the new major would replace it with the registrar's number."
          : undefined,
        known: [
          `Current major: ${r.summary.current_major}`,
          `Considering: ${r.summary.prospective_major}`,
          `Completed credits: ${r.comparison.staying.line_items[1]?.value ?? "—"}`,
        ],
        stillNeed: isEstimate
          ? [
              "A what-if degree audit run against the new major",
              "Or your advisor's written credit evaluation",
            ]
          : undefined,
      };
    },
  },
  {
    id: "degree_audit",
    label: "Degree Audit",
    x: 190,
    y: 438,
    branch: "academic",
    kind: "leaf",
    parent: "academic",
    question: "What has my registrar actually recorded?",
    resolve: () => ({
      state: "needs_info",
      reason:
        "Fork can read completed hours straight out of a degree audit PDF, so the number comes from your registrar rather than from memory.",
      stillNeed: [
        "Upload your degree audit PDF",
        "Confirm the hours Fork reads back to you",
      ],
    }),
  },
  {
    id: "prerequisite_check",
    label: "Prerequisite Check",
    x: 106,
    y: 258,
    branch: "academic",
    kind: "leaf",
    parent: "academic",
    question: "Am I eligible for the courses the new major requires?",
    resolve: locked(
      "Needs a course-level prerequisite graph from the university catalog. Not integrated yet.",
    ),
  },
  {
    id: "gpa_eligibility",
    label: "GPA Eligibility",
    x: 178,
    y: 158,
    branch: "academic",
    kind: "leaf",
    parent: "academic",
    question: "Does my GPA meet the new major's admission requirement?",
    resolve: locked(
      "Needs per-major admission GPA thresholds from the university catalog. Not integrated yet.",
    ),
  },

  // --- Financial --------------------------------------------------------
  {
    id: "financial",
    label: "Financial Impact",
    x: 728,
    y: 300,
    branch: "financial",
    kind: "hub",
    parent: "root",
    question: "What's the difference in what I'll pay?",
    icon: "dollar",
    resolve: (r) =>
      !r
        ? idle
        : {
            state: r.summary.incremental_tuition > 0 ? "at_risk" : "completed",
            display: money(r.summary.incremental_tuition),
            lineItem: findLineItem(r, "Additional tuition"),
            derivedFrom: [
              r.comparison.staying.line_items[4],
              r.comparison.switching.line_items[4],
            ].filter(Boolean) as LineItem[],
          },
  },
  {
    id: "tuition_difference",
    label: "Tuition Difference",
    x: 872,
    y: 214,
    branch: "financial",
    kind: "leaf",
    parent: "financial",
    question: "How much more (or less) tuition will I pay?",
    resolve: (r) =>
      !r
        ? idle
        : {
            state: r.summary.incremental_tuition > 0 ? "at_risk" : "completed",
            display: money(r.summary.incremental_tuition),
            lineItem: findLineItem(r, "Additional tuition"),
            derivedFrom: [
              r.comparison.staying.line_items[4],
              r.comparison.switching.line_items[4],
            ].filter(Boolean) as LineItem[],
          },
  },
  {
    id: "financial_aid",
    label: "Financial Aid Impact",
    x: 894,
    y: 324,
    branch: "financial",
    kind: "leaf",
    parent: "financial",
    question: "Does switching change my aid package?",
    resolve: locked(
      "Depends on your individual FAFSA and award letter. Fork has no access to those and won't guess at them.",
    ),
  },
  {
    id: "scholarships",
    label: "Scholarships & Grants",
    x: 850,
    y: 430,
    branch: "financial",
    kind: "leaf",
    parent: "financial",
    question: "Are any of my awards tied to my current major?",
    resolve: locked(
      "Major-restricted awards vary by donor and department. Requires your specific award terms.",
    ),
  },

  // --- Graduation timeline ----------------------------------------------
  {
    id: "graduation",
    label: "Graduation Timeline",
    x: 500,
    y: 166,
    branch: "graduation",
    kind: "hub",
    parent: "root",
    question: "When do I finish either way?",
    icon: "calendar",
    resolve: (r) =>
      !r
        ? idle
        : {
            state: r.summary.incremental_semesters > 0 ? "at_risk" : "completed",
            display: semesters(r.summary.incremental_semesters),
            lineItem: findLineItem(r, "Additional semesters"),
            derivedFrom: [
              r.comparison.staying.line_items[3],
              r.comparison.switching.line_items[3],
            ].filter(Boolean) as LineItem[],
          },
  },
  {
    id: "time_to_graduate",
    label: "Time to Graduate",
    x: 500,
    y: 62,
    branch: "graduation",
    kind: "leaf",
    parent: "graduation",
    question: "How much longer will this take?",
    resolve: (r) =>
      !r
        ? idle
        : {
            state: r.summary.incremental_semesters > 0 ? "at_risk" : "completed",
            display: semesters(r.summary.incremental_semesters),
            lineItem: findLineItem(r, "Additional semesters"),
            derivedFrom: [
              r.comparison.staying.line_items[3],
              r.comparison.switching.line_items[3],
            ].filter(Boolean) as LineItem[],
          },
  },
  {
    id: "summer_courses",
    label: "Summer Courses",
    x: 348,
    y: 92,
    branch: "graduation",
    kind: "leaf",
    parent: "graduation",
    question: "Could summer terms close the gap?",
    resolve: locked(
      "Needs summer course availability and per-term tuition rates. Not modeled yet.",
    ),
  },
  {
    id: "internship_impact",
    label: "Internship Impact",
    x: 656,
    y: 92,
    branch: "graduation",
    kind: "leaf",
    parent: "graduation",
    question: "Does a co-op or internship shift my timeline?",
    resolve: locked(
      "This is its own decision with its own tradeoffs. Planned as a separate decision path rather than a footnote on this one.",
    ),
  },

  // --- Career -----------------------------------------------------------
  {
    id: "career",
    label: "Career Outlook",
    x: 330,
    y: 548,
    branch: "career",
    kind: "hub",
    parent: "root",
    question: "What do graduates of each major earn?",
    icon: "briefcase",
    resolve: (r) => {
      if (!r) return idle;
      const delta = r.summary.annual_salary_delta;
      const li = findLineItem(r, "Difference in early-career earnings");
      return {
        // A missing comparison isn't a negative one — don't render it as
        // though switching costs earnings when we simply don't know.
        state:
          delta === null || delta === undefined
            ? "needs_info"
            : delta < 0
              ? "at_risk"
              : "completed",
        display:
          delta === null || delta === undefined
            ? undefined
            : money(delta) + "/yr",
        lineItem: li,
        derivedFrom: [
          findLineItem(
            r,
            `Median earnings 1 year after graduation — ${r.summary.current_major}`,
          ),
          findLineItem(
            r,
            `Median earnings 1 year after graduation — ${r.summary.prospective_major}`,
          ),
        ].filter(Boolean) as LineItem[],
        known: [
          `Current major: ${r.summary.current_major}`,
          `Considering: ${r.summary.prospective_major}`,
        ],
        reason: earningsComparison(r),
        contextGroups: [
          earningsGroup(r, r.summary.current_major),
          earningsGroup(r, r.summary.prospective_major),
        ].filter(Boolean) as ContextGroup[],
        dataLimitations: earningsLimitations(r),
      };
    },
  },
  {
    id: "salary_outlook",
    label: "Salary Outlook",
    x: 248,
    y: 656,
    branch: "career",
    kind: "leaf",
    parent: "career",
    question:
      "What do graduates of the major I'm considering earn early on?",
    resolve: (r) => {
      if (!r) return idle;
      // Headline is the PROSPECTIVE major's own figure rather than a
      // difference, so the number on screen belongs to one named program
      // and one named time point instead of being an unattributed delta.
      const pro = r.summary.prospective_major;
      const li = findLineItem(
        r,
        `Median earnings 1 year after graduation — ${pro}`,
      );
      const available = li != null && li.value !== null;
      return {
        state: available ? "completed" : "needs_info",
        display: available ? money(li!.value as number) : undefined,
        lineItem: li,
        known: [
          `Major shown: ${pro}`,
          "Time point: 1 year after graduation",
          `Compared against: ${r.summary.current_major}`,
        ],
        reason: available
          ? earningsComparison(r)
          : (li?.status_note ??
            "No published earnings figure for this program."),
        contextGroups: [earningsGroup(r, pro)].filter(
          Boolean,
        ) as ContextGroup[],
        dataLimitations: earningsLimitations(r, [pro]),
      };
    },
  },
  {
    id: "job_market",
    label: "Job Market Demand",
    x: 168,
    y: 516,
    branch: "career",
    kind: "leaf",
    parent: "career",
    question: "Is this field projected to grow?",
    resolve: locked(
      "Bureau of Labor Statistics occupational projections aren't wired in yet. Planned, not guessed at.",
    ),
  },

  // --- Approval ---------------------------------------------------------
  {
    id: "approval",
    label: "Advisor Approval",
    x: 646,
    y: 556,
    branch: "approval",
    kind: "hub",
    parent: "root",
    question: "What does the university need from me to actually switch?",
    icon: "check",
    resolve: locked(
      "Fork prices the decision. Approving it is your advisor's job, and this tool doesn't replace that conversation.",
    ),
  },
  {
    id: "department_requirements",
    label: "Department Requirements",
    x: 650,
    y: 672,
    branch: "approval",
    kind: "leaf",
    parent: "approval",
    question: "Does the department gate entry to this major?",
    resolve: locked(
      "Departmental admission rules vary by program and change year to year. Requires catalog integration.",
    ),
  },
];

export const NODES_BY_ID = new Map(NODES.map((n) => [n.id, n]));

export const STATE_LABEL: Record<NodeState, string> = {
  completed: "Answered",
  at_risk: "Moves against you",
  needs_info: "Needs info",
  locked: "Not available yet",
  idle: "Waiting",
};
