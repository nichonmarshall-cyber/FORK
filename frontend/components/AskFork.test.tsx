// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AskFork from "./AskFork";

vi.mock("@/lib/types", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/types")>();
  return { ...actual, explainDecision: vi.fn() };
});

import { ApiError, ExplainResponse, explainDecision } from "@/lib/types";

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

const FULL_ANSWER: ExplainResponse = {
  direct_answer: "The biggest uncertainty is the salary comparison.",
  key_points: [
    { title: "Shared category", explanation: "UNT reports both majors under one federal category." },
  ],
  limitations: [
    { title: "Not a personal prediction", explanation: "This is a group figure, not a guarantee for you." },
  ],
  still_useful_for: ["Estimating tuition impact"],
  next_step: { action: "Request a what-if audit.", reason: "It would confirm the credit count." },
  related_node_ids: ["financial"],
  used_fallback: false,
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
    expect(screen.getByPlaceholderText(/calculate a comparison first/i)).toBeDisabled();
    expect(screen.getByRole("button", { name: "Explain the biggest difference" })).toBeDisabled();
  });

  it("sends available_nodes and the selected node's context with a starter prompt", async () => {
    const mockExplain = vi.mocked(explainDecision);
    mockExplain.mockResolvedValueOnce(FULL_ANSWER);

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
    expect(sentRequest.available_nodes).toBeDefined();
    expect(sentRequest.available_nodes!.length).toBeGreaterThan(0);
  });

  it("renders the direct answer, key points, limitations (collapsed), still-useful-for, and next step", async () => {
    const mockExplain = vi.mocked(explainDecision);
    mockExplain.mockResolvedValueOnce(FULL_ANSWER);

    render(
      <AskFork result={CALC_RESULT} calcInputs={CALC_INPUTS} selectedNode={null} onSelectNode={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Explain the biggest difference" }));

    await waitFor(() =>
      expect(screen.getByText("The biggest uncertainty is the salary comparison.")).toBeInTheDocument(),
    );

    expect(screen.getByText(/UNT reports both majors/)).toBeInTheDocument();
    expect(screen.getByText("Still useful for")).toBeInTheDocument();
    expect(screen.getByText("Estimating tuition impact")).toBeInTheDocument();
    expect(screen.getByText("Request a what-if audit.")).toBeInTheDocument();

    // Limitations start collapsed — the count shows, the content doesn't
    // until expanded.
    expect(screen.getByText("Limitations (1)")).toBeInTheDocument();
    expect(screen.queryByText(/This is a group figure/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Limitations (1)"));
    expect(screen.getByText(/This is a group figure/)).toBeInTheDocument();
  });

  it("never uses dangerouslySetInnerHTML or any raw-HTML rendering path", async () => {
    // The actual guarantee behind "no literal Markdown markers": this
    // component never parses or injects raw HTML/Markdown at all. Visual
    // emphasis (titles, next-step, still-useful-for) comes from the
    // structured schema's separate fields plus CSS classes, not from
    // inline "**bold**" syntax the model would have to produce and this
    // component would have to interpret. Asserting on the component's
    // own source is a stronger guarantee here than asserting on one
    // rendered string, since it holds regardless of what text the model
    // (or the deterministic fallback) happens to return.
    const fs = await import("fs");
    const source = fs.readFileSync("components/AskFork.tsx", "utf-8");
    expect(source).not.toContain("dangerouslySetInnerHTML");
  });

  it("gives key point titles visual weight via CSS, not inline markdown syntax", async () => {
    const mockExplain = vi.mocked(explainDecision);
    mockExplain.mockResolvedValueOnce(FULL_ANSWER);

    render(
      <AskFork result={CALC_RESULT} calcInputs={CALC_INPUTS} selectedNode={null} onSelectNode={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Explain the biggest difference" }));

    const title = await screen.findByText("Shared category:");
    // font-medium is the CSS mechanism doing the job markdown's ** would
    // otherwise be asked to do -- and the literal text never contains an
    // asterisk, because the schema never needed one.
    expect(title.className).toContain("font-medium");
    expect(document.body.textContent).not.toContain("**");
  });

  it("omits empty sections rather than rendering them blank", async () => {
    const mockExplain = vi.mocked(explainDecision);
    mockExplain.mockResolvedValueOnce({
      direct_answer: "Short answer only.",
      key_points: [],
      limitations: [],
      still_useful_for: [],
      next_step: null,
      related_node_ids: [],
      used_fallback: false,
    });

    render(
      <AskFork result={CALC_RESULT} calcInputs={CALC_INPUTS} selectedNode={null} onSelectNode={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Explain the biggest difference" }));

    await waitFor(() => expect(screen.getByText("Short answer only.")).toBeInTheDocument());
    expect(screen.queryByText("Still useful for")).not.toBeInTheDocument();
    expect(screen.queryByText("Next step")).not.toBeInTheDocument();
    expect(screen.queryByText(/Limitations \(/)).not.toBeInTheDocument();
  });

  it("uses stable node ids for related-node chips, not text matching, and clicking one calls onSelectNode without resetting anything", async () => {
    const mockExplain = vi.mocked(explainDecision);
    mockExplain.mockResolvedValueOnce(FULL_ANSWER);

    const onSelectNode = vi.fn();
    render(
      <AskFork result={CALC_RESULT} calcInputs={CALC_INPUTS} selectedNode={null} onSelectNode={onSelectNode} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Explain the biggest difference" }));

    const chip = await screen.findByRole("button", { name: /Related: Financial Impact/ });
    fireEvent.click(chip);
    expect(onSelectNode).toHaveBeenCalledWith("financial");
    // The answer itself is untouched by selecting a related node.
    expect(screen.getByText("The biggest uncertainty is the salary comparison.")).toBeInTheDocument();
  });

  it("shows the required failure message and a retry action, and keeps the previous answer visible", async () => {
    const mockExplain = vi.mocked(explainDecision);
    mockExplain.mockResolvedValueOnce(FULL_ANSWER);

    render(
      <AskFork result={CALC_RESULT} calcInputs={CALC_INPUTS} selectedNode={null} onSelectNode={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Explain the biggest difference" }));
    await waitFor(() =>
      expect(screen.getByText("The biggest uncertainty is the salary comparison.")).toBeInTheDocument(),
    );

    mockExplain.mockRejectedValueOnce(new ApiError("some backend detail that shouldn't show"));
    fireEvent.click(screen.getByRole("button", { name: "Why will graduation take longer?" }));

    await waitFor(() =>
      expect(
        screen.getByText(
          "Fork could not generate an explanation right now. Your calculation is still available.",
        ),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText(/some backend detail/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();

    // The previous successful answer is still fully visible underneath
    // the error.
    expect(screen.getByText("The biggest uncertainty is the salary comparison.")).toBeInTheDocument();
  });

  it("retry resends the same question that failed", async () => {
    const mockExplain = vi.mocked(explainDecision);
    mockExplain.mockRejectedValueOnce(new ApiError("fail once"));
    mockExplain.mockResolvedValueOnce(FULL_ANSWER);

    render(
      <AskFork result={CALC_RESULT} calcInputs={CALC_INPUTS} selectedNode={null} onSelectNode={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Compare the career outlook" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() =>
      expect(screen.getByText("The biggest uncertainty is the salary comparison.")).toBeInTheDocument(),
    );
    expect(mockExplain).toHaveBeenCalledTimes(2);
    expect(mockExplain.mock.calls[1][0].question).toBe("Compare the career outlook");
  });

  it("shows a quiet note, not an error, when the answer used the deterministic fallback", async () => {
    const mockExplain = vi.mocked(explainDecision);
    mockExplain.mockResolvedValueOnce({ ...FULL_ANSWER, used_fallback: true });

    render(
      <AskFork result={CALC_RESULT} calcInputs={CALC_INPUTS} selectedNode={null} onSelectNode={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Explain the biggest difference" }));

    await waitFor(() => expect(screen.getByText(/simplified summary/i)).toBeInTheDocument());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("prevents a duplicate submission while a request is already loading", async () => {
    const mockExplain = vi.mocked(explainDecision);
    let resolvePromise: (v: ExplainResponse) => void = () => {};
    mockExplain.mockReturnValueOnce(
      new Promise((resolve) => {
        resolvePromise = resolve;
      }),
    );

    render(
      <AskFork result={CALC_RESULT} calcInputs={CALC_INPUTS} selectedNode={null} onSelectNode={vi.fn()} />,
    );
    const button = screen.getByRole("button", { name: "Explain the biggest difference" });
    fireEvent.click(button);
    // Still loading -- the same button (and every starter prompt) is
    // disabled, so a second click can't fire a second request.
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(mockExplain).toHaveBeenCalledTimes(1);

    resolvePromise(FULL_ANSWER);
    await waitFor(() => expect(button).not.toBeDisabled());
  });

  it("each starter prompt sends its own exact question text", async () => {
    const mockExplain = vi.mocked(explainDecision);
    mockExplain.mockResolvedValue(FULL_ANSWER);

    const prompts = [
      "Explain the biggest difference",
      "Why will graduation take longer?",
      "Break down the additional cost",
      "Compare the career outlook",
      "What does this data not tell me?",
    ];

    for (const [i, prompt] of prompts.entries()) {
      cleanup();
      render(
        <AskFork result={CALC_RESULT} calcInputs={CALC_INPUTS} selectedNode={null} onSelectNode={vi.fn()} />,
      );
      fireEvent.click(screen.getByRole("button", { name: prompt }));
      await waitFor(() => expect(mockExplain).toHaveBeenCalledTimes(i + 1));
      expect(mockExplain.mock.calls[i][0].question).toBe(prompt);
    }
  });
});