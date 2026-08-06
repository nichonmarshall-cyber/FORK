// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AskFork from "./AskFork";
import { ApiError } from "@/lib/types";

vi.mock("@/lib/types", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/types")>();
  return { ...actual, explainDecision: vi.fn() };
});

import { explainDecision } from "@/lib/types";

const CALC_RESULT = {
  summary: {
    current_major: "Computer Science",
    prospective_major: "Information Technology",
  },
} as unknown as import("@/lib/types").CalcResult;

const CALC_INPUTS = {
  current_major: "computer_science",
  prospective_major: "information_technology",
  credits_completed: 72,
  credits_transferable: 60,
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AskFork", () => {
  it("is disabled until a calculation exists", () => {
    render(
      <AskFork result={null} calcInputs={CALC_INPUTS} selectedNode={null} onSelectNode={vi.fn()} />,
    );
    expect(
      screen.getByPlaceholderText(/calculate a comparison first/i),
    ).toBeDisabled();
    for (const prompt of ["Explain the biggest difference", "Compare the career outlook"]) {
      expect(screen.getByRole("button", { name: prompt })).toBeDisabled();
    }
  });

  it("sends the selected node's context along with a starter prompt", async () => {
    const mockExplain = vi.mocked(explainDecision);
    mockExplain.mockResolvedValueOnce({
      answer: "Switching adds tuition and delays income.",
      used_fallback: false,
      selected_node_id: "financial",
    });

    render(
      <AskFork
        result={CALC_RESULT}
        calcInputs={CALC_INPUTS}
        selectedNode={{ id: "financial", label: "Financial Impact", question: "What does this cost?" }}
        onSelectNode={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Break down the additional cost" }));

    await waitFor(() => expect(mockExplain).toHaveBeenCalled());
    const sentRequest = mockExplain.mock.calls[0][0];
    expect(sentRequest.question).toBe("Break down the additional cost");
    expect(sentRequest.selected_node_id).toBe("financial");
    expect(sentRequest.selected_node_label).toBe("Financial Impact");
    expect(sentRequest.current_major).toBe("computer_science");
  });

  it("changing the selected node changes what context the next question sends", async () => {
    const mockExplain = vi.mocked(explainDecision);
    mockExplain.mockResolvedValue({
      answer: "Some answer with no numbers.",
      used_fallback: false,
      selected_node_id: null,
    });

    const { rerender } = render(
      <AskFork
        result={CALC_RESULT}
        calcInputs={CALC_INPUTS}
        selectedNode={{ id: "career", label: "Career Outlook", question: "What do graduates earn?" }}
        onSelectNode={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Compare the career outlook" }));
    await waitFor(() => expect(mockExplain).toHaveBeenCalledTimes(1));
    expect(mockExplain.mock.calls[0][0].selected_node_id).toBe("career");

    rerender(
      <AskFork
        result={CALC_RESULT}
        calcInputs={CALC_INPUTS}
        selectedNode={{ id: "financial", label: "Financial Impact", question: "What does this cost?" }}
        onSelectNode={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Break down the additional cost" }));
    await waitFor(() => expect(mockExplain).toHaveBeenCalledTimes(2));
    expect(mockExplain.mock.calls[1][0].selected_node_id).toBe("financial");
  });

  it("shows a clean error and keeps the previous answer when a later question fails", async () => {
    const mockExplain = vi.mocked(explainDecision);
    mockExplain.mockResolvedValueOnce({
      answer: "First answer, successfully grounded.",
      used_fallback: false,
      selected_node_id: null,
    });

    render(
      <AskFork result={CALC_RESULT} calcInputs={CALC_INPUTS} selectedNode={null} onSelectNode={vi.fn()} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Explain the biggest difference" }));
    await waitFor(() =>
      expect(screen.getByText("First answer, successfully grounded.")).toBeInTheDocument(),
    );

    mockExplain.mockRejectedValueOnce(
      new ApiError("We couldn't calculate the difference right now. Please try again."),
    );
    fireEvent.click(screen.getByRole("button", { name: "Why will graduation take longer?" }));

    await waitFor(() =>
      expect(
        screen.getByText("We couldn't calculate the difference right now. Please try again."),
      ).toBeInTheDocument(),
    );

    // The first answer is still on screen — a failed follow-up question
    // must not erase what was already shown, same principle as the main
    // calculation form.
    expect(screen.getByText("First answer, successfully grounded.")).toBeInTheDocument();
  });

  it("never renders a raw error message, even if the thrown error isn't an ApiError", async () => {
    const mockExplain = vi.mocked(explainDecision);
    mockExplain.mockRejectedValueOnce(new Error("TypeError: fetch failed at internal/xyz.js:42"));

    render(
      <AskFork result={CALC_RESULT} calcInputs={CALC_INPUTS} selectedNode={null} onSelectNode={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "What does this data not tell me?" }));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.queryByText(/TypeError/)).not.toBeInTheDocument();
    expect(screen.queryByText(/internal\/xyz\.js/)).not.toBeInTheDocument();
    expect(screen.getByText("Something went wrong.")).toBeInTheDocument();
  });

  it("shows a quiet note, not an error, when the answer used the deterministic fallback", async () => {
    const mockExplain = vi.mocked(explainDecision);
    mockExplain.mockResolvedValueOnce({
      answer: "Here's what the numbers show, based on your reported credits.",
      used_fallback: true,
      selected_node_id: null,
    });

    render(
      <AskFork result={CALC_RESULT} calcInputs={CALC_INPUTS} selectedNode={null} onSelectNode={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Explain the biggest difference" }));

    await waitFor(() =>
      expect(screen.getByText(/simplified summary/i)).toBeInTheDocument(),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("offers to open a node whose label appears verbatim in the answer, and only real nodes", async () => {
    const mockExplain = vi.mocked(explainDecision);
    mockExplain.mockResolvedValueOnce({
      answer: "This is driven mostly by the Financial Impact of the additional tuition.",
      used_fallback: false,
      selected_node_id: null,
    });

    const onSelectNode = vi.fn();
    render(
      <AskFork
        result={CALC_RESULT}
        calcInputs={CALC_INPUTS}
        selectedNode={null}
        onSelectNode={onSelectNode}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Explain the biggest difference" }));

    const openButton = await screen.findByRole("button", { name: "Open Financial Impact" });
    fireEvent.click(openButton);
    expect(onSelectNode).toHaveBeenCalledWith("financial");
  });
});