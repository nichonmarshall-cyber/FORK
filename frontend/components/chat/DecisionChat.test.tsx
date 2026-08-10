// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import DecisionChat from "./DecisionChat";

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
  credits_transferable: 66,
};

const ANSWER: ExplainResponse = {
  direct_answer: "The biggest difference is the earnings comparison.",
  key_points: [
    { title: "Shared category", explanation: "Both majors report under one federal category." },
  ],
  limitations: [
    { title: "Not a personal prediction", explanation: "This is a group figure." },
  ],
  still_useful_for: ["Estimating tuition impact"],
  next_step: { action: "Request a what-if audit.", reason: "It would confirm credits." },
  related_node_ids: ["financial"],
  used_fallback: false,
};

function renderChat(overrides: Partial<Parameters<typeof DecisionChat>[0]> = {}) {
  const props = {
    result: CALC_RESULT,
    calcInputs: CALC_INPUTS,
    selectedNode: null,
    onSelectNode: vi.fn(),
    ...overrides,
  };
  return { ...render(<DecisionChat {...props} />), props };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("DecisionChat", () => {
  it("shows the empty state prompt and suggestion chips before any message", () => {
    renderChat();
    expect(
      screen.getByText("What would you like to understand about this decision?"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Explain the biggest difference" }),
    ).toBeInTheDocument();
  });

  it("renders the user's question and Fork's answer as separate visible turns", async () => {
    vi.mocked(explainDecision).mockResolvedValueOnce(ANSWER);
    renderChat();

    fireEvent.click(screen.getByRole("button", { name: "Explain the biggest difference" }));

    // The user's own message appears as its own turn -- not just as
    // input that vanished into a report.
    await waitFor(() =>
      expect(
        screen.getByText("Explain the biggest difference", { selector: "p" }),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByText("The biggest difference is the earnings comparison."),
    ).toBeInTheDocument();
  });

  it("keeps multiple turns visible, newest last", async () => {
    vi.mocked(explainDecision)
      .mockResolvedValueOnce({ ...ANSWER, direct_answer: "First answer." })
      .mockResolvedValueOnce({ ...ANSWER, direct_answer: "Second answer." });
    renderChat();

    fireEvent.click(screen.getByRole("button", { name: "Explain the biggest difference" }));
    await waitFor(() => expect(screen.getByText("First answer.")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Break down the additional cost" }));
    await waitFor(() => expect(screen.getByText("Second answer.")).toBeInTheDocument());

    // Both exchanges remain -- a new question doesn't replace the old one.
    expect(screen.getByText("First answer.")).toBeInTheDocument();
    expect(
      screen.getByText("Explain the biggest difference", { selector: "p" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Break down the additional cost", { selector: "p" }),
    ).toBeInTheDocument();
  });

  it("renders direct answer, key points, next step and still-useful-for; limitations start collapsed", async () => {
    vi.mocked(explainDecision).mockResolvedValueOnce(ANSWER);
    renderChat();
    fireEvent.click(screen.getByRole("button", { name: "Explain the biggest difference" }));

    await waitFor(() =>
      expect(
        screen.getByText("The biggest difference is the earnings comparison."),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText(/Both majors report under one federal category/)).toBeInTheDocument();
    expect(screen.getByText("Request a what-if audit.")).toBeInTheDocument();
    expect(screen.getByText("Estimating tuition impact")).toBeInTheDocument();

    expect(screen.getByText(/Limitations and assumptions · 1/)).toBeInTheDocument();
    expect(screen.queryByText(/This is a group figure/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText(/Limitations and assumptions · 1/));
    expect(screen.getByText(/This is a group figure/)).toBeInTheDocument();
  });

  it("omits sections that have no content", async () => {
    vi.mocked(explainDecision).mockResolvedValueOnce({
      direct_answer: "Short answer.",
      key_points: [],
      limitations: [],
      still_useful_for: [],
      next_step: null,
      related_node_ids: [],
      used_fallback: false,
    });
    renderChat();
    fireEvent.click(screen.getByRole("button", { name: "Explain the biggest difference" }));

    await waitFor(() => expect(screen.getByText("Short answer.")).toBeInTheDocument());
    expect(screen.queryByText("Still useful for")).not.toBeInTheDocument();
    expect(screen.queryByText(/Limitations and assumptions/)).not.toBeInTheDocument();
  });

  it("never renders raw markdown markers", async () => {
    vi.mocked(explainDecision).mockResolvedValueOnce(ANSWER);
    renderChat();
    fireEvent.click(screen.getByRole("button", { name: "Explain the biggest difference" }));

    await waitFor(() =>
      expect(
        screen.getByText("The biggest difference is the earnings comparison."),
      ).toBeInTheDocument(),
    );
    expect(document.body.textContent).not.toContain("**");
  });

  it("shows the loading placeholder without clearing prior messages", async () => {
    let resolveSecond: (v: ExplainResponse) => void = () => {};
    vi.mocked(explainDecision)
      .mockResolvedValueOnce({ ...ANSWER, direct_answer: "First answer." })
      .mockReturnValueOnce(new Promise((r) => { resolveSecond = r; }));
    renderChat();

    fireEvent.click(screen.getByRole("button", { name: "Explain the biggest difference" }));
    await waitFor(() => expect(screen.getByText("First answer.")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Compare the career outlook" }));
    expect(screen.getByText("Fork is reviewing your decision...")).toBeInTheDocument();
    // Prior conversation stays on screen while loading.
    expect(screen.getByText("First answer.")).toBeInTheDocument();

    resolveSecond(ANSWER);
    await waitFor(() =>
      expect(screen.queryByText("Fork is reviewing your decision...")).not.toBeInTheDocument(),
    );
  });

  it("shows the required error message with Retry, preserving prior turns", async () => {
    vi.mocked(explainDecision)
      .mockResolvedValueOnce({ ...ANSWER, direct_answer: "First answer." })
      .mockRejectedValueOnce(new ApiError("raw provider detail"));
    renderChat();

    fireEvent.click(screen.getByRole("button", { name: "Explain the biggest difference" }));
    await waitFor(() => expect(screen.getByText("First answer.")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Why will graduation take longer?" }));
    await waitFor(() =>
      expect(
        screen.getByText(
          "Fork could not generate an explanation right now. Your decision results are still available.",
        ),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText(/raw provider detail/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.getByText("First answer.")).toBeInTheDocument();
  });

  it("retry resends the failed question and clears the error card", async () => {
    vi.mocked(explainDecision)
      .mockRejectedValueOnce(new ApiError("fail"))
      .mockResolvedValueOnce(ANSWER);
    renderChat();

    fireEvent.click(screen.getByRole("button", { name: "Compare the career outlook" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() =>
      expect(
        screen.getByText("The biggest difference is the earnings comparison."),
      ).toBeInTheDocument(),
    );
    expect(vi.mocked(explainDecision).mock.calls[1][0].question).toBe(
      "Compare the career outlook",
    );
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });

  it("blocks duplicate submissions while a request is in flight", async () => {
    let resolve: (v: ExplainResponse) => void = () => {};
    vi.mocked(explainDecision).mockReturnValueOnce(
      new Promise((r) => { resolve = r; }),
    );
    renderChat();

    const chip = screen.getByRole("button", { name: "Explain the biggest difference" });
    fireEvent.click(chip);
    expect(chip).toBeDisabled();
    fireEvent.click(chip);
    expect(explainDecision).toHaveBeenCalledTimes(1);

    resolve(ANSWER);
    await waitFor(() => expect(chip).not.toBeDisabled());
  });

  it("clicking a related node calls onSelectNode without erasing chat history", async () => {
    vi.mocked(explainDecision).mockResolvedValueOnce(ANSWER);
    const onSelectNode = vi.fn();
    renderChat({ onSelectNode });

    fireEvent.click(screen.getByRole("button", { name: "Explain the biggest difference" }));
    const chip = await screen.findByRole("button", { name: "Financial Impact" });

    fireEvent.click(chip);
    expect(onSelectNode).toHaveBeenCalledWith("financial");
    // The whole conversation survives navigating to a node.
    expect(
      screen.getByText("The biggest difference is the earnings comparison."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Explain the biggest difference", { selector: "p" }),
    ).toBeInTheDocument();
  });

  it("inserts a decision-update boundary when the calculation inputs change", async () => {
    vi.mocked(explainDecision).mockResolvedValueOnce(ANSWER);
    const { rerender } = renderChat();

    fireEvent.click(screen.getByRole("button", { name: "Explain the biggest difference" }));
    await waitFor(() =>
      expect(
        screen.getByText("The biggest difference is the earnings comparison."),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText(/Decision updated/)).not.toBeInTheDocument();

    rerender(
      <DecisionChat
        result={
          {
            summary: {
              current_major: "Computer Science",
              prospective_major: "Psychology (B.S.)",
            },
          } as unknown as import("@/lib/types").CalcResult
        }
        calcInputs={{ ...CALC_INPUTS, prospective_major: "psychology_bs" }}
        selectedNode={null}
        onSelectNode={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByText(/Decision updated/)).toBeInTheDocument());
    // History is preserved, not wiped -- the boundary separates it.
    expect(
      screen.getByText("The biggest difference is the earnings comparison."),
    ).toBeInTheDocument();
  });

  it("never sends prior Fork prose back to the backend as context", async () => {
    vi.mocked(explainDecision).mockResolvedValue(ANSWER);
    renderChat();

    fireEvent.click(screen.getByRole("button", { name: "Explain the biggest difference" }));
    await waitFor(() => expect(explainDecision).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Break down the additional cost" }));
    await waitFor(() => expect(explainDecision).toHaveBeenCalledTimes(2));

    // The second request must carry no trace of the first ANSWER's text.
    const secondRequest = vi.mocked(explainDecision).mock.calls[1][0];
    const serialized = JSON.stringify(secondRequest);
    expect(serialized).not.toContain(ANSWER.direct_answer);
    expect(serialized).not.toContain("Shared category");
    expect(secondRequest.question).toBe("Break down the additional cost");
  });

  it("is disabled until a calculation exists", () => {
    renderChat({ result: null });
    expect(
      screen.getByPlaceholderText("Calculate a comparison first to ask about it"),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Explain the biggest difference" }),
    ).toBeDisabled();
  });
});