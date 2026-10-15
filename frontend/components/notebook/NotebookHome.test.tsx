// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import NotebookHome from "./NotebookHome";
import { EMPTY_NOTEBOOK, FULL_NOTEBOOK } from "@/lib/notebook.fixtures";

vi.mock("@/lib/notebook", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/notebook")>();
  return {
    ...actual,
    updateScenario: vi.fn(),
    getNotebook: vi.fn(),
    updateProfile: vi.fn(),
    removeDocument: vi.fn(),
  };
});

import { getNotebook, removeDocument, updateProfile, updateScenario } from "@/lib/notebook";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("NotebookHome — empty", () => {
  it("guides a new student instead of showing blank cards", () => {
    render(<NotebookHome notebook={EMPTY_NOTEBOOK} onNotebook={() => {}} />);
    expect(screen.getByRole("heading", { name: /your notebook is empty/i })).toBeInTheDocument();
    expect(screen.getByText("No documents yet.")).toBeInTheDocument();
    expect(screen.getByText("Nothing saved yet.")).toBeInTheDocument();
    // Rendered for both layouts; CSS shows one (jsdom applies no CSS).
    expect(screen.getAllByText("Add your UNT degree audit").length).toBeGreaterThan(0);
    // Missing figures say so; none render as zero.
    expect(screen.getAllByText("Not known yet").length).toBeGreaterThan(0);
    expect(screen.queryByText(/^0$/)).not.toBeInTheDocument();
    expect(screen.getByText("Started your Fork notebook.")).toBeInTheDocument();
  });
});

describe("NotebookHome — populated", () => {
  it("shows each figure with where it came from", () => {
    render(<NotebookHome notebook={FULL_NOTEBOOK} onNotebook={() => {}} />);
    const snapshot = screen.getByRole("region", { name: /your academic snapshot/i });

    const completed = within(snapshot).getByText("Credits completed").closest("div")!;
    expect(within(completed).getByText("81")).toBeInTheDocument();
    expect(completed.querySelector('[data-provenance="confirmed_document"]')).not.toBeNull();

    const gpa = within(snapshot).getByText("GPA").closest("div")!;
    expect(gpa.querySelector('[data-provenance="student_reported"]')).not.toBeNull();

    // What-If figures are scoped to their program and badged as such.
    expect(within(snapshot).getByText(/would\s+apply to Psychology \(B\.S\.\)/)).toBeInTheDocument();
    expect(snapshot.querySelector('[data-provenance="what_if"]')).not.toBeNull();

    // Degree progress comes from the audit's own total block.
    expect(within(snapshot).getByText("21 still needed")).toBeInTheDocument();
  });

  it("is honest about documents Fork hasn't read", () => {
    render(<NotebookHome notebook={FULL_NOTEBOOK} onNotebook={() => {}} />);
    const record = screen.getByRole("region", { name: /your academic record/i });
    expect(within(record).getByText("Not read by Fork")).toBeInTheDocument();
    expect(within(record).getByText("Recorded by you, not read by Fork")).toBeInTheDocument();
    expect(within(record).getByText(/Fork read 81 completed and\s+18 in-progress hours/)).toBeInTheDocument();
    // Never "verified".
    expect(record.textContent?.toLowerCase()).not.toContain("verified");
  });

  it("shows the journey newest first with links back", () => {
    render(<NotebookHome notebook={FULL_NOTEBOOK} onNotebook={() => {}} />);
    const journey = screen.getByRole("region", { name: /your academic journey/i });
    const items = within(journey).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Marked staying in Computer Science");
    expect(within(items[0]).getByRole("link", { name: "Open" })).toHaveAttribute(
      "href",
      "/compare?scenario=sc1",
    );
  });

  it("marks a plan through the backend and re-renders from its answer", async () => {
    vi.mocked(updateScenario).mockResolvedValue({ scenario: FULL_NOTEBOOK.scenarios[0] });
    const next = { ...FULL_NOTEBOOK, scenarios: [{ ...FULL_NOTEBOOK.scenarios[0], decision: "computer_science" }] };
    vi.mocked(getNotebook).mockResolvedValue(next);
    const onNotebook = vi.fn();
    render(<NotebookHome notebook={FULL_NOTEBOOK} onNotebook={onNotebook} />);

    fireEvent.click(screen.getByRole("button", { name: "Stay in Computer Science" }));
    await waitFor(() => expect(onNotebook).toHaveBeenCalledWith(next));
    expect(updateScenario).toHaveBeenCalledWith("sc1", { decision: "computer_science" });
  });

  it("asks before removing a document and its figures", async () => {
    vi.mocked(removeDocument).mockResolvedValue(EMPTY_NOTEBOOK);
    const onNotebook = vi.fn();
    render(<NotebookHome notebook={FULL_NOTEBOOK} onNotebook={onNotebook} />);
    const record = screen.getByRole("region", { name: /your academic record/i });
    fireEvent.click(within(record).getAllByRole("button", { name: "Remove from record" })[0]);
    expect(within(record).getByText("Remove it and the figures that come from it?")).toBeInTheDocument();
    expect(removeDocument).not.toHaveBeenCalled();
    fireEvent.click(within(record).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(removeDocument).toHaveBeenCalledWith("doc1"));
  });
});

describe("Updating details", () => {
  it("locks document-backed fields and sends only what changed", async () => {
    vi.mocked(updateProfile).mockResolvedValue(FULL_NOTEBOOK);
    render(<NotebookHome notebook={FULL_NOTEBOOK} onNotebook={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Update your details" }));

    expect(screen.getByLabelText(/^Credits completed/)).toBeDisabled();
    expect(screen.getByLabelText(/^Current major/)).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/^GPA/), { target: { value: "3.6" } });
    fireEvent.click(screen.getByRole("button", { name: "Save my details" }));
    await waitFor(() => expect(updateProfile).toHaveBeenCalledWith({ gpa: 3.6 }));
  });

  it("rejects an impossible GPA before sending anything", () => {
    render(<NotebookHome notebook={EMPTY_NOTEBOOK} onNotebook={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Update your details" }));
    fireEvent.change(screen.getByLabelText(/^GPA/), { target: { value: "4.7" } });
    fireEvent.click(screen.getByRole("button", { name: "Save my details" }));
    expect(screen.getByRole("alert")).toHaveTextContent("between 0.00 and 4.00");
    expect(updateProfile).not.toHaveBeenCalled();
  });
});
