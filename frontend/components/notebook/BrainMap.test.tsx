// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import BrainMap from "./BrainMap";
import NotebookHome from "./NotebookHome";
import { FULL_NOTEBOOK } from "@/lib/notebook.fixtures";

beforeAll(() => {
  // Lay the graph out instantly so tests don't wait on animation frames.
  window.matchMedia = ((q: string) => ({
    matches: q.includes("reduce"),
    media: q,
    addEventListener() {},
    removeEventListener() {},
  })) as unknown as typeof window.matchMedia;
});

afterEach(cleanup);

describe("BrainMap", () => {
  it("draws every note and opens one with its linked mentions", () => {
    render(<BrainMap notebook={FULL_NOTEBOOK} />);
    const map = screen.getByRole("group", { name: /brain map/i });
    expect(within(map).getByRole("button", { name: "Documents: Degree audit" })).toBeInTheDocument();
    expect(within(map).getByRole("button", { name: "Majors: Psychology (B.S.)" })).toBeInTheDocument();

    fireEvent.keyDown(within(map).getByRole("button", { name: "Documents: Degree audit" }), { key: "Enter" });
    const note = screen.getByRole("heading", { level: 3 });
    expect(note).toHaveTextContent("Degree audit");
    expect(screen.getByText(/Linked mentions · \d+/)).toBeInTheDocument();
    // Following a mention opens that note.
    const mentions = screen.getByRole("complementary");
    fireEvent.click(within(mentions).getByRole("button", { name: /81 credits completed/ }));
    expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent("81 credits completed");
  });

  it("adds the journey when asked", () => {
    render(<BrainMap notebook={FULL_NOTEBOOK} />);
    expect(screen.queryAllByRole("button", { name: /^Journey:/ })).toHaveLength(0);
    fireEvent.click(screen.getByRole("checkbox", { name: "Show journey" }));
    expect(screen.getAllByRole("button", { name: /^Journey:/ }).length).toBe(FULL_NOTEBOOK.timeline.length);
  });
});

describe("Notebook view switch", () => {
  it("switches between the notebook and the brain map", () => {
    render(<NotebookHome notebook={FULL_NOTEBOOK} onNotebook={() => {}} />);
    fireEvent.click(screen.getByRole("tab", { name: "Brain map" }));
    expect(screen.getByRole("heading", { name: "Brain map" })).toBeInTheDocument();
    expect(window.location.hash).toBe("#map");
    fireEvent.click(screen.getByRole("tab", { name: "Notebook" }));
    expect(screen.getByRole("heading", { name: /your academic snapshot/i })).toBeInTheDocument();
  });
});

describe("Demo notebook", () => {
  const DEMO = { ...FULL_NOTEBOOK, student: { ...FULL_NOTEBOOK.student, is_demo: true } };

  it("says it's fictional and hides every edit control", () => {
    render(<NotebookHome notebook={DEMO} onNotebook={() => {}} />);
    expect(screen.getByText(/fictional student/)).toBeInTheDocument();
    for (const name of [
      "Update your details",
      "Record another document",
      "Remove from record",
      "Recheck against my record",
      "Stay in Computer Science",
    ]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "Make your own" })).toBeInTheDocument();
  });
});
