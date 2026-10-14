// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Home from "./page";
import { ApiError } from "@/lib/types";

// Mocks calculateChangeMajor specifically rather than global fetch — this
// test is about page.tsx's STATE HANDLING around success/failure, not
// about re-testing the fetch plumbing (that's covered in lib/types.test.ts).
vi.mock("@/lib/types", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/types")>();
  return { ...actual, calculateChangeMajor: vi.fn(), explainDecision: vi.fn() };
});

import { calculateChangeMajor, explainDecision } from "@/lib/types";

const GOOD_RESULT = {
  summary: {
    current_major: "Computer Science",
    prospective_major: "Information Technology",
    credits_lost: 6,
    incremental_semesters: 0.8,
    incremental_tuition: 4800,
    incremental_total_cost: 34800,
    annual_salary_delta: 0,
  },
  comparison: {
    staying: { major: "Computer Science", line_items: [] },
    switching: { major: "Information Technology", line_items: [] },
  },
  line_items: [],
  earnings_context: [],
  career_context: [],
  why_am_i_seeing_this: { assumptions: [], limitations: [] },
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Home — failed request handling", () => {
  it("preserves the last successful result when a later request fails", async () => {
    const mockCalc = vi.mocked(calculateChangeMajor);
    mockCalc.mockResolvedValueOnce(GOOD_RESULT);

    render(<Home />);

    fireEvent.click(screen.getByRole("button", { name: /show me the difference/i }));

    // "How this affects you" only renders when `result` is set — this is
    // the direct proxy for "the map/summary is populated" without needing
    // to reach into DecisionMap's SVG internals.
    await waitFor(() =>
      expect(screen.getByText("How this affects you")).toBeInTheDocument(),
    );

    // Now the SAME form, same valid inputs, but the next request fails.
    mockCalc.mockRejectedValueOnce(
      new ApiError("We couldn't calculate the difference right now. Please try again."),
    );
    fireEvent.click(screen.getByRole("button", { name: /show me the difference/i }));

    await waitFor(() =>
      expect(
        screen.getByText("We couldn't calculate the difference right now. Please try again."),
      ).toBeInTheDocument(),
    );

    // The critical assertion: the PREVIOUS successful result must still be
    // on screen. A failed request must never null out a good one.
    expect(screen.getByText("How this affects you")).toBeInTheDocument();
  });

  it("never sends a request at all when client-side validation fails", async () => {
    const mockCalc = vi.mocked(calculateChangeMajor);
    render(<Home />);

    const completedInput = screen.getByLabelText(/credits completed/i);
    const transferableInput = screen.getByLabelText(/credits that transfer/i);

    fireEvent.change(completedInput, { target: { value: "72" } });
    fireEvent.change(transferableInput, { target: { value: "74" } });

    const button = screen.getByRole("button", { name: /show me the difference/i });
    // aria-disabled, not the native `disabled` attribute — see the
    // comment on the button in page.tsx for why: a natively disabled
    // button can never fire a click handler, which would make it
    // impossible to move focus to the invalid field "after an attempted
    // submission" (there'd be nothing to attempt). The button still LOOKS
    // and behaves disabled to a user; handleSubmit is the real gate.
    expect(button).toHaveAttribute("aria-disabled", "true");

    fireEvent.click(button);
    expect(mockCalc).not.toHaveBeenCalled();

    await waitFor(() =>
      expect(
        screen.getByText(/Transferable credits cannot exceed completed credits/i),
      ).toBeInTheDocument(),
    );
    expect(transferableInput).toHaveFocus();
  });
});


describe("Ask Fork uses the calculated snapshot, not draft form state", () => {
  const ANSWER = {
    direct_answer: "A.",
    key_points: [],
    limitations: [],
    still_useful_for: [],
    next_step: null,
    related_node_ids: [],
    used_fallback: false,
  };

  function resultFor(cur: string, pro: string) {
    return {
      ...GOOD_RESULT,
      summary: { ...GOOD_RESULT.summary, current_major: cur, prospective_major: pro },
    };
  }

  it("keeps asking about the calculated decision after dropdowns change without recalculating", async () => {
    const mockCalc = vi.mocked(calculateChangeMajor);
    const mockExplain = vi.mocked(explainDecision);
    mockExplain.mockResolvedValue(ANSWER as never);

    render(<Home />);

    // 1. Calculate Psychology (B.A.) -> Computer Science.
    fireEvent.change(screen.getByLabelText(/current major/i), {
      target: { value: "psychology_ba" },
    });
    fireEvent.change(screen.getByLabelText(/considering/i), {
      target: { value: "computer_science" },
    });
    mockCalc.mockResolvedValueOnce(
      resultFor("Psychology (B.A.)", "Computer Science") as never,
    );
    fireEvent.click(screen.getByRole("button", { name: /show me the difference/i }));
    await waitFor(() => expect(screen.getByText("How this affects you")).toBeInTheDocument());

    // 2. Change the dropdowns to CS -> IT. Do NOT recalculate.
    fireEvent.change(screen.getByLabelText(/current major/i), {
      target: { value: "computer_science" },
    });
    fireEvent.change(screen.getByLabelText(/considering/i), {
      target: { value: "information_technology" },
    });

    // 3. Ask Fork a question.
    fireEvent.click(screen.getByRole("button", { name: "Explain the biggest difference" }));
    await waitFor(() => expect(mockExplain).toHaveBeenCalledTimes(1));

    // 4. The request must describe the decision still on screen, not the
    //    unsubmitted draft.
    const first = mockExplain.mock.calls[0][0];
    expect(first.current_major).toBe("psychology_ba");
    expect(first.prospective_major).toBe("computer_science");

    // 5. Now actually recalculate.
    mockCalc.mockResolvedValueOnce(
      resultFor("Computer Science", "Information Technology") as never,
    );
    fireEvent.click(screen.getByRole("button", { name: /show me the difference/i }));
    await waitFor(() => expect(mockCalc).toHaveBeenCalledTimes(2));

    // 6-7. The next question uses the NEW snapshot.
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Break down the additional cost" }),
      ).not.toBeDisabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Break down the additional cost" }));
    await waitFor(() => expect(mockExplain).toHaveBeenCalledTimes(2));

    const second = mockExplain.mock.calls[1][0];
    expect(second.current_major).toBe("computer_science");
    expect(second.prospective_major).toBe("information_technology");
  });

  it("disables Ask Fork until the first calculation has actually run", () => {
    render(<Home />);
    expect(
      screen.getByRole("button", { name: "Explain the biggest difference" }),
    ).toBeDisabled();
  });
});