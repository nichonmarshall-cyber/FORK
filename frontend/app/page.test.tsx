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
  return { ...actual, calculateChangeMajor: vi.fn() };
});

import { calculateChangeMajor } from "@/lib/types";

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
