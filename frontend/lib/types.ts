/**
 * Mirrors what the backend actually returns. If formatter.py changes shape,
 * this file changes with it — that's the only coupling between frontend and
 * backend, and it's deliberate.
 */

export interface LineItem {
  label: string;
  // null when the underlying figure genuinely isn't available (federal
  // privacy suppression, or no data reported). Render "not available" plus
  // status_note — never 0, and never a blank cell.
  value: number | null;
  source: string;
  source_date: string;
  // Only present when something is off; absent means the value is good.
  status?: "privacy_suppressed" | "unavailable" | "partial";
  status_note?: string | null;
}

export interface EarningsTrajectoryPoint {
  period: "1yr" | "4yr" | "5yr";
  label: string;
  value: number | null;
  status: "available" | "privacy_suppressed" | "unavailable";
  status_note: string | null;
  graduates_measured: number | null;
}

export interface EarningsContext {
  major: string;
  field_of_study: string | null;
  degrees_awarded_in_field: number | null;
  degrees_awarded_label: string;
  // Present when the federal category is broader than the single program
  // (e.g. CS and IT share one category), explaining what the number covers.
  covers: string | null;
  population_note: string | null;
  trajectory: EarningsTrajectoryPoint[];
  source: string;
  source_date: string;
}

export interface PathComparison {
  major: string;
  line_items: LineItem[];
  // Present when the reference data supplies them (real institution data
  // does; older or synthetic reference data may not).
  official_program_name?: string;
  degree_type?: string;
}

export interface Occupation {
  title: string;
  median_annual_wage: number | null;
  national_employment: number | null;
  percent_change_2024_2034: number | null;
  annual_openings: number | null;
  typical_education: string | null;
}

export interface CareerContext {
  major: string;
  occupations: Occupation[];
  // Ranking rule, always "Most common nationally" — labelled explicitly
  // so this doesn't read as a best-fit or recommended-for-you ordering.
  sort_order: string;
  crosswalk_source: string | null;
  crosswalk_source_url: string | null;
  crosswalk_limitation: string | null;
  wage_source: string | null;
  wage_release: string | null;
  projections_source: string | null;
  projections_cycle: string | null;
  retrieved: string | null;
}

export interface CalcResult {
  summary: {
    current_major: string;
    prospective_major: string;
    credits_lost: number;
    incremental_semesters: number;
    incremental_tuition: number;
    incremental_total_cost: number;
    annual_salary_delta: number;
  };
  comparison: {
    staying: PathComparison;
    switching: PathComparison;
  };
  line_items: LineItem[];
  // Display-only career context: the 1/4/5-year earnings trajectory per
  // program. Never feeds a calculation.
  earnings_context: EarningsContext[];
  // Occupations connected to each major via the federal CIP-SOC crosswalk,
  // with BLS wage/growth context. Also display-only.
  career_context: CareerContext[];
  why_am_i_seeing_this: {
    assumptions: string[];
    limitations: string[];
  };
  // Non-fatal notes about the request itself — e.g. a caller used a
  // renamed major key and the request was still processed under the new
  // one. Absent when there's nothing to flag.
  warnings?: string[];
}

export interface CalcRequest {
  current_major: string;
  prospective_major: string;
  credits_completed: number;
  credits_transferable: number;
  credits_source?: string;
  credits_transferable_source?: string;
  credits_source_date?: string;
  credits_in_progress?: number;
  // Which school to calculate against. Optional because the backend
  // defaults to "unt" when omitted — only send this once there's more
  // than one supported institution to choose from.
  institution_id?: string;
}
/** One node's id and label — the frontend's own canonical list, sent to
 * the backend so it knows which ids are real and can validate the
 * model's related_node_ids against them. Kept minimal on purpose; the
 * backend only needs enough to name and constrain the model's choices,
 * not the full node definition. */
export interface AvailableNode {
  id: string;
  label: string;
}

/**
 * Everything /explain needs: the same inputs /calculate takes (the
 * backend recomputes the result itself rather than trusting a
 * client-supplied one — see main.py's _run_change_major_calculation),
 * plus the question, which node is currently open, and the full list of
 * nodes that exist (so the backend can validate related_node_ids).
 */
export interface ExplainRequest extends CalcRequest {
  question: string;
  selected_node_id?: string;
  selected_node_label?: string;
  selected_node_question?: string;
  available_nodes?: AvailableNode[];
  // Optional continuity for Compare One's chat — lets Ask Fork resolve a
  // topic-word-free follow-up and remember a stated priority across
  // turns. Omitted (or unrecognized/expired server-side) just starts a
  // fresh session; /explain still recomputes the projection itself
  // either way. See conversation/session.py.
  session_id?: string;
}

export interface ExplainKeyPoint {
  title: string;
  explanation: string;
}

export interface ExplainLimitation {
  title: string;
  explanation: string;
}

export interface ExplainNextStep {
  action: string;
  reason: string;
}

/** One clickable navigation chip. `major` is null for a plain node-only
 * pill (Compare One always; Compare Multiple when there's no single
 * relevant path — see conversation/orchestrator.py's _compute_navigation
 * for the three-case rule this renders). A non-null `major` names which
 * alternative's path the pill points to. */
export interface NavigationPill {
  major: string | null;
  node_id: string;
}

/** What Ask Fork proactively focuses this turn, if anything — computed
 * server-side from the same inputs as navigation_pills, never authored by
 * the explanation model. `major: null` means "focus this node on
 * whichever path is currently displayed"; a non-null major means the
 * student explicitly named that alternative this turn, so the path
 * switches too. See the architecture plan's auto-focus rule. */
export interface NavigationTarget {
  major: string | null;
  node_id: string;
}

/** The explanation content itself — title/body sections, no navigation or
 * status wrapping. Compare One's /explain merges this flat into its
 * response (see ExplainResponse); Compare Multiple's /comparison/ask
 * nests it under "answer" alongside sibling navigation/status fields
 * (see ComparisonAskResponse). Same shape either way. */
export interface DecisionExplanationCore {
  direct_answer: string;
  key_points: ExplainKeyPoint[];
  limitations: ExplainLimitation[];
  still_useful_for: string[];
  next_step: ExplainNextStep | null;
  // Real node ids the answer specifically discusses — already filtered
  // server-side against the ids this request supplied, so anything here
  // is guaranteed to exist on the map. Still worth treating defensively
  // in the UI (see AskFork's NODES_BY_ID lookup) rather than assuming.
  related_node_ids: string[];
}

export interface ExplainResponse extends DecisionExplanationCore {
  navigation_pills: NavigationPill[];
  navigation_target: NavigationTarget | null;
  // The classified topic scope for this turn, or null on a short-circuit
  // response (e.g. a deterministic add-confirmation) that never reached
  // the explanation step.
  topic_scope: string | null;
  // True when the AI couldn't produce a valid, grounded structured
  // answer twice in a row and a deterministic template was used instead.
  // Still fully grounded and trustworthy — just plainer — so the UI
  // should show this as a quiet note, not an error.
  used_fallback: boolean;
}

/** One alternative's transfer-credit figure, applied via chat rather than
 * the manual form — e.g. "switch to Computer Science; 61 credits apply."
 * The frontend reacts to this by updating its own draft/calculated state
 * and re-running the existing calculate/explain flow, the same trust
 * path a manual form submission already goes through. */
export interface AppliedOptionChange {
  major: string;
  credits_transferable: number | null;
}

/**
 * The full shape /explain can now return. Compare One's chat can resolve
 * an option-change instruction ("compare me to X instead") instead of
 * answering a question that turn — see
 * conversation.orchestrator.handle_pairwise_turn.
 */
export type ExplainTurnResponse =
  | ({ status: "complete"; state: { session_id: string } } & ExplainResponse)
  | { status: "clarification_required"; message: string; state: { session_id: string } }
  | { status: "ai_unavailable"; message: string; state: { session_id: string } }
  | {
      status: "option_change_applied";
      applied_option_change: AppliedOptionChange;
      state: { session_id: string };
    };

/**
 * Every distinct failure shape the API (or the network under it) can
 * produce, mapped to exactly one user-facing sentence each. This is the
 * single place that decides what a person sees when something goes
 * wrong — nowhere else should reach into a response body and build its
 * own message, or a raw backend shape will eventually leak through some
 * other path.
 *
 * Kept as a pure function of (response status, parsed body, thrown
 * error) so it's testable without a live server.
 */
export interface ParsedApiError {
  message: string;
  /** Which field a validation error points at, when there is one — lets
   * the form move focus to the right input. */
  field?: string;
}

export function parseApiError(input: {
  status?: number;
  body?: unknown;
  networkError?: unknown;
}): ParsedApiError {
  const { status, body, networkError } = input;

  // The request never reached the server, or the response wasn't JSON —
  // fetch() throwing, DNS failure, the backend being down entirely.
  if (networkError || status === undefined) {
    if (networkError) {
      // Deliberate: technical detail stays in the dev console, never in
      // the UI. See requirement 5.
      console.error("Fork: network error calling the API", networkError);
    }
    return {
      message: "We couldn't calculate the difference right now. Please try again.",
    };
  }

  const detail = (body as { detail?: unknown } | null)?.detail;

  // Shape 1: structured backend errors, all of the form
  // { status: "...", message: "...", ... }. Covers validation_error
  // (this fix), clarification_required and unsupported_program (major
  // resolution, added earlier).
  if (detail && typeof detail === "object" && "message" in detail) {
    const d = detail as { status?: string; message: string; errors?: { field?: string; message: string }[] };
    const field = d.errors?.[0]?.field;
    return { message: d.message, field };
  }

  // Shape 2: a plain string detail. FastAPI emits this for its own
  // built-in errors (e.g. a 404 from an unknown institution_id) — these
  // are already short and written for a human, so pass them through.
  if (typeof detail === "string") {
    return { message: detail };
  }

  // Shape 3: something came back, but not a shape we recognize — an old
  // deploy, a proxy error page, a future backend change we haven't
  // updated this parser for. Never show it raw.
  console.error("Fork: unrecognized API error shape", { status, body });
  if (status >= 500) {
    return {
      message: "We couldn't calculate the difference right now. Please try again.",
    };
  }
  return {
    message: "Something went wrong with that request. Please check your inputs and try again.",
  };
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export async function calculateChangeMajor(
  body: CalcRequest,
): Promise<CalcResult> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/decision-paths/change-major/calculate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (networkError) {
    const parsed = parseApiError({ networkError });
    throw new ApiError(parsed.message, parsed.field);
  }

  if (!res.ok) {
    const parsedBody = await res.json().catch(() => null);
    const parsed = parseApiError({ status: res.status, body: parsedBody });
    throw new ApiError(parsed.message, parsed.field);
  }

  return res.json();
}

/** Thrown by calculateChangeMajor. Carries the already-cleaned message —
 * callers should never need to inspect a response body themselves. */
export class ApiError extends Error {
  field?: string;
  constructor(message: string, field?: string) {
    super(message);
    this.name = "ApiError";
    this.field = field;
  }
}

export async function explainDecision(
  body: ExplainRequest,
): Promise<ExplainTurnResponse> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/decision-paths/change-major/explain`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (networkError) {
    const parsed = parseApiError({ networkError });
    throw new ApiError(parsed.message, parsed.field);
  }

  if (!res.ok) {
    const parsedBody = await res.json().catch(() => null);
    const parsed = parseApiError({ status: res.status, body: parsedBody });
    throw new ApiError(parsed.message, parsed.field);
  }

  return res.json();
}

/** Find a line item by a distinctive fragment of its label. */
export function findLineItem(
  result: CalcResult,
  fragment: string,
): LineItem | undefined {
  const all = [
    ...result.line_items,
    ...result.comparison.staying.line_items,
    ...result.comparison.switching.line_items,
  ];
  return all.find((li) =>
    li.label.toLowerCase().includes(fragment.toLowerCase()),
  );
}
// =====================================================================
// Multi-option comparison
// =====================================================================
//
// The pairwise calls above compare exactly two majors and replace their
// result each time. These call the session-aware endpoints instead: one
// request sets up a comparison across several alternatives, and every
// question after that runs against the whole set at once.
//
// The backend holds the conversation state (which majors are active,
// what topic is being discussed). The client holds only the session id.
// That's deliberate — a future "Comparing: …" control and a typed
// instruction like "just compare CS and IT" both have to change the same
// state, and duplicating it here would let the two drift apart.

/** One alternative in a multi-option comparison. credits_transferable is
 * optional: leaving it out marks that option pending rather than failing
 * the whole comparison, and the backend will say which field it needs. */
export interface ComparisonOptionRequest {
  major: string;
  credits_transferable?: number;
  credits_transferable_source?: string;
}

export interface StartComparisonRequest {
  current_major: string;
  credits_completed: number;
  options: ComparisonOptionRequest[];
  credits_source?: string;
  credits_source_date?: string;
  credits_in_progress?: number;
  institution_id?: string;
  /** Reuses an existing conversation when supplied. Omit to start fresh. */
  session_id?: string;
}

/** Conversation state as the backend sees it. Read-only here — the client
 * never edits this, it just renders it. */
export interface ComparisonState {
  session_id: string;
  /** Includes the anchor (the student's current major) as the first entry. */
  active_options: string[];
  current_topic_scope: string;
  last_topic_scope: string | null;
  last_question_intent: string | null;
  last_referenced_options: string[];
  /** Set only when the student explicitly stated it this conversation —
   * never inferred from a reaction. Survives topic and option-set
   * changes; cleared only by an explicit statement or a session reset. */
  stated_priority: string | null;
  turn_count: number;
}

/** One alternative's outcome. "pending" means an input is missing and no
 * figures were produced for it — the UI must not render a number for a
 * pending option, because there isn't one. */
export interface ComparisonOptionOutcome {
  major_key: string;
  major: string;
  status: "calculated" | "pending" | "failed";
  dimensions?: Record<string, Record<string, LineItem>>;
  /** The full pairwise result for this alternative — the same shape
   * /calculate returns, so the Decision Map and node system can render it
   * directly. Present only on calculated options; a pending one has no
   * result, and there must be no way for the UI to show a figure for it.
   * This is what lets the path navigator switch which map is displayed
   * without a network call or a recalculation. */
  detail?: CalcResult;
  missing_fields?: string[];
  error?: string;
}

export interface MultiComparisonResponse {
  status: "ready";
  state: ComparisonState;
  comparison: {
    anchor: { major_key: string; major: string };
    credits_completed: number;
    options: ComparisonOptionOutcome[];
    assumptions: string[];
    limitations: string[];
  };
}

/** A turn either answers, asks a question back, changes the comparison,
 * or — if the intent-classification provider call itself fails — reports
 * unavailability. Clarification and unavailability are both real
 * outcomes, not errors: neither one guesses, and neither mutates
 * active_options, topic scope, or stated priority. */
export type ComparisonAskResponse =
  | {
      status: "complete";
      state: ComparisonState;
      answer: DecisionExplanationCore;
      used_fallback: boolean;
      navigation_pills: NavigationPill[];
      navigation_target: NavigationTarget | null;
      topic_scope: string | null;
      /** Always present on "complete" now that a chat instruction can
       * change the option set mid-conversation — the same shape
       * /comparison/start returns, so the Decision Map and PathNavigator
       * can show a genuinely new option the moment it's added. */
      comparison: MultiComparisonResponse["comparison"] | null;
    }
  | {
      status: "clarification_required";
      state: ComparisonState;
      message: string;
    }
  | {
      status: "ai_unavailable";
      state: ComparisonState;
      message: string;
    };

export async function startComparison(
  body: StartComparisonRequest,
): Promise<MultiComparisonResponse> {
  let res: Response;
  try {
    res = await fetch(
      `${API_BASE}/decision-paths/change-major/comparison/start`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    );
  } catch (networkError) {
    const parsed = parseApiError({ networkError });
    throw new ApiError(parsed.message, parsed.field);
  }

  if (!res.ok) {
    const parsedBody = await res.json().catch(() => null);
    const parsed = parseApiError({ status: res.status, body: parsedBody });
    throw new ApiError(parsed.message, parsed.field);
  }

  return res.json();
}

export async function askComparison(
  sessionId: string,
  message: string,
  options?: {
    /** Which alternative's map is currently displayed — a per-request
     * hint, never persisted server-side. Used only to resolve "this one"
     * and to decide whether an auto-focus should also switch paths;
     * never affects active_options. */
    selectedDetailPath?: string | null;
    availableNodes?: AvailableNode[];
  },
): Promise<ComparisonAskResponse> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/decision-paths/change-major/comparison/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        message,
        selected_detail_path: options?.selectedDetailPath ?? undefined,
        available_nodes: options?.availableNodes ?? [],
      }),
    });
  } catch (networkError) {
    const parsed = parseApiError({ networkError });
    throw new ApiError(parsed.message, parsed.field);
  }

  if (!res.ok) {
    // 404 here specifically means the session is gone -- sessions live in
    // the backend's memory and are cleared when it restarts. Worth its own
    // message, since "try again" is wrong advice: the comparison has to be
    // set up again.
    if (res.status === 404) {
      throw new ApiError(
        "That comparison isn't available any more. Set it up again to continue.",
      );
    }
    const parsedBody = await res.json().catch(() => null);
    const parsed = parseApiError({ status: res.status, body: parsedBody });
    throw new ApiError(parsed.message, parsed.field);
  }

  return res.json();
}