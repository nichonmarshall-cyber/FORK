// @vitest-environment jsdom
/**
 * The compare page with a signed-in student.
 *
 * Also the regression suite for three provenance bugs fixed on this
 * branch, each of which labelled a confirmed document's figure as
 * "Student-reported" (or kept a document's label on a typed number):
 *   1. Ask Fork recomputed from four bare numbers, dropping provenance and
 *      in-progress hours.
 *   2. A chat-driven option change recalculated without any provenance.
 *   3. Multi-option comparisons never sent provenance at all.
 * Plus the inverse: a document's label stuck to a figure after the
 * student typed over it.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ComparePage from "./page";
import { AUDIT_SOURCE, FULL_NOTEBOOK, STUDENT, WHAT_IF_SOURCE } from "@/lib/notebook.fixtures";

vi.mock("@/lib/types", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/types")>();
  return {
    ...actual,
    calculateChangeMajor: vi.fn(),
    explainDecision: vi.fn(),
    startComparison: vi.fn(),
  };
});
vi.mock("@/lib/notebook", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/notebook")>();
  return {
    ...actual,
    hasSignInHint: vi.fn(() => true),
    getMe: vi.fn(),
    getNotebook: vi.fn(),
    saveScenario: vi.fn(),
  };
});

import { calculateChangeMajor, explainDecision, startComparison } from "@/lib/types";
import { getMe, getNotebook, hasSignInHint, saveScenario } from "@/lib/notebook";

const RESULT = {
  summary: {
    current_major: "Computer Science",
    prospective_major: "Psychology (B.S.)",
    credits_lost: 0,
    incremental_semesters: 0,
    incremental_tuition: 0,
    incremental_total_cost: 0,
    annual_salary_delta: -21000,
  },
  comparison: {
    staying: { major: "Computer Science", line_items: [] },
    switching: { major: "Psychology (B.S.)", line_items: [] },
  },
  line_items: [],
  earnings_context: [],
  career_context: [],
  why_am_i_seeing_this: { assumptions: [], limitations: [] },
};

function visit(search: string) {
  window.history.replaceState(null, "", `/compare${search}`);
}

beforeEach(() => {
  vi.mocked(hasSignInHint).mockReturnValue(true);
  vi.mocked(getMe).mockResolvedValue(STUDENT);
  vi.mocked(getNotebook).mockResolvedValue(FULL_NOTEBOOK);
  vi.mocked(calculateChangeMajor).mockResolvedValue(RESULT as never);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  visit("");
});

async function prefilledFromRecord() {
  visit("?from=record");
  render(<ComparePage />);
  await screen.findByText(/Filled in .* from your notebook/);
}

describe("prefill from the notebook", () => {
  it("fills the form and carries the documents' provenance into the calculation", async () => {
    await prefilledFromRecord();
    expect(screen.getByLabelText(/credits completed/i)).toHaveValue("81");

    fireEvent.change(screen.getByLabelText(/considering/i), { target: { value: "psychology_bs" } });
    // The notebook's What-If covers this program, so its figure comes in.
    expect(screen.getByLabelText(/credits that transfer/i)).toHaveValue("81");

    fireEvent.click(screen.getByRole("button", { name: /show me the difference/i }));
    await waitFor(() => expect(calculateChangeMajor).toHaveBeenCalledTimes(1));
    expect(vi.mocked(calculateChangeMajor).mock.calls[0][0]).toMatchObject({
      current_major: "computer_science",
      prospective_major: "psychology_bs",
      credits_completed: 81,
      credits_transferable: 81,
      credits_source: AUDIT_SOURCE,
      credits_in_progress: 18,
      credits_transferable_source: WHAT_IF_SOURCE,
    });
  });

  it("drops a document's label once the student types over its figure", async () => {
    await prefilledFromRecord();
    fireEvent.change(screen.getByLabelText(/credits completed/i), { target: { value: "84" } });
    fireEvent.change(screen.getByLabelText(/credits that transfer/i), { target: { value: "70" } });
    fireEvent.click(screen.getByRole("button", { name: /show me the difference/i }));
    await waitFor(() => expect(calculateChangeMajor).toHaveBeenCalledTimes(1));
    const sent = vi.mocked(calculateChangeMajor).mock.calls[0][0];
    expect(sent.credits_completed).toBe(84);
    expect(sent.credits_source).toBeUndefined();
    expect(sent.credits_in_progress).toBeUndefined();
    expect(sent.credits_transferable_source).toBeUndefined();
  });
});

describe("provenance regressions", () => {
  it("Ask Fork recomputes with the same provenance and in-progress hours as the map", async () => {
    vi.mocked(explainDecision).mockResolvedValue({
      status: "complete",
      state: { session_id: "x" },
      direct_answer: "A.",
      key_points: [],
      limitations: [],
      still_useful_for: [],
      next_step: null,
      related_node_ids: [],
      navigation_pills: [],
      navigation_target: null,
      topic_scope: "broad",
      used_fallback: false,
    } as never);
    await prefilledFromRecord();
    fireEvent.click(screen.getByRole("button", { name: /show me the difference/i }));
    await waitFor(() => expect(screen.getByText("How this affects you")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Explain the biggest difference" }));
    await waitFor(() => expect(explainDecision).toHaveBeenCalledTimes(1));
    expect(vi.mocked(explainDecision).mock.calls[0][0]).toMatchObject({
      credits_completed: 81,
      credits_source: AUDIT_SOURCE,
      credits_in_progress: 18,
    });
  });

  it("a chat-driven option change keeps the documents' provenance", async () => {
    vi.mocked(explainDecision).mockResolvedValue({
      status: "option_change_applied",
      applied_option_change: { major: "psychology_bs", credits_transferable: 81 },
      state: { session_id: "x" },
    } as never);
    await prefilledFromRecord();
    fireEvent.click(screen.getByRole("button", { name: /show me the difference/i }));
    await waitFor(() => expect(screen.getByText("How this affects you")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Explain the biggest difference" }));
    await waitFor(() => expect(calculateChangeMajor).toHaveBeenCalledTimes(2));
    expect(vi.mocked(calculateChangeMajor).mock.calls[1][0]).toMatchObject({
      prospective_major: "psychology_bs",
      credits_transferable: 81,
      credits_source: AUDIT_SOURCE,
      credits_in_progress: 18,
      credits_transferable_source: WHAT_IF_SOURCE,
    });
  });

  it("multi-option comparisons send provenance, per option", async () => {
    vi.mocked(startComparison).mockRejectedValue(new Error("not needed"));
    await prefilledFromRecord();
    fireEvent.click(screen.getByRole("radio", { name: /multiple/i }));
    // Rows seed from the pairwise form: Information Technology, then the
    // next free major. Point the second row at Psychology (B.S.), the
    // program the notebook's What-If covers.
    const majors = await screen.findAllByLabelText("Prospective major");
    fireEvent.change(majors[1], { target: { value: "psychology_bs" } });
    const figures = screen.getAllByLabelText(/credits that apply/i);
    fireEvent.change(figures[0], { target: { value: "70" } });
    fireEvent.change(figures[1], { target: { value: "81" } });

    fireEvent.click(screen.getByRole("button", { name: /compare 2 options/i }));
    await waitFor(() => expect(startComparison).toHaveBeenCalledTimes(1));
    const sent = vi.mocked(startComparison).mock.calls[0][0];
    expect(sent.credits_source).toBe(AUDIT_SOURCE);
    expect(sent.credits_in_progress).toBe(18);
    const psych = sent.options.find((o) => o.major === "psychology_bs");
    const other = sent.options.find((o) => o.major !== "psychology_bs");
    expect(psych?.credits_transferable_source).toBe(WHAT_IF_SOURCE);
    expect(other?.credits_transferable_source).toBeUndefined();
  });
});

describe("saving to the notebook", () => {
  it("sends the calculated inputs, never the result", async () => {
    vi.mocked(saveScenario).mockResolvedValue({ scenario: { ...FULL_NOTEBOOK.scenarios[0], title: "My plan" } });
    await prefilledFromRecord();
    fireEvent.click(screen.getByRole("button", { name: /show me the difference/i }));
    fireEvent.click(await screen.findByRole("button", { name: "Save to my notebook" }));

    await waitFor(() => expect(saveScenario).toHaveBeenCalledTimes(1));
    const body = vi.mocked(saveScenario).mock.calls[0][0];
    expect(body).toMatchObject({
      current_major: "computer_science",
      credits_completed: 81,
      credits_in_progress: 18,
      credits_source: AUDIT_SOURCE,
      options: [{ major: "information_technology", credits_transferable_source: "Student-reported" }],
    });
    expect(JSON.stringify(body)).not.toContain("incremental");
    expect(await screen.findByText(/Saved to your notebook as “My plan”/)).toBeInTheDocument();
  });

  it("reopens a saved comparison and recalculates it", async () => {
    visit("?scenario=sc1");
    render(<ComparePage />);
    await waitFor(() => expect(calculateChangeMajor).toHaveBeenCalledTimes(1));
    expect(vi.mocked(calculateChangeMajor).mock.calls[0][0]).toMatchObject({
      prospective_major: "psychology_bs",
      credits_source: AUDIT_SOURCE,
      credits_transferable_source: WHAT_IF_SOURCE,
    });
    expect(screen.getByText(/Showing “Compared Computer Science/)).toBeInTheDocument();
  });
});

describe("signed out", () => {
  it("makes no account request and offers sign-in", async () => {
    vi.mocked(hasSignInHint).mockReturnValue(false);
    render(<ComparePage />);
    fireEvent.click(screen.getByRole("button", { name: /show me the difference/i }));
    await waitFor(() => expect(screen.getByText("How this affects you")).toBeInTheDocument());
    expect(getMe).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Save to my notebook" })).not.toBeInTheDocument();
    expect(screen.getByText(/to keep comparisons in a notebook/)).toBeInTheDocument();
  });
});
