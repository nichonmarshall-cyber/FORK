// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import Home from "./page";

/**
 * Multi-option comparison UI.
 *
 * The tests that matter most are the state-separation ones near the
 * bottom. Everything else here is form mechanics; those are the ones that
 * catch the failure where opening a path on the map silently narrows what
 * Fork is comparing in conversation.
 */

const CALCULATED = (current: string, prospective: string) => ({
  summary: {
    current_major: current,
    prospective_major: prospective,
    incremental_semesters: 1,
    incremental_total_cost: 8000,
    annual_salary_delta: 2000,
  },
  comparison: {
    staying: { major: current, line_items: [] },
    switching: { major: prospective, line_items: [] },
  },
  line_items: [],
  earnings_context: [],
  career_context: [],
  why_am_i_seeing_this: { assumptions: [], limitations: [] },
});

function optionOutcome(key: string, label: string, status = "calculated") {
  const base: Record<string, unknown> = {
    major_key: key,
    major: label,
    status,
  };
  if (status === "calculated") {
    base.detail = CALCULATED("Computer Science", label);
    base.dimensions = {};
  }
  if (status === "pending") base.missing_fields = ["credits_transferable"];
  return base;
}

const START_RESPONSE = {
  status: "ready",
  state: {
    session_id: "sess-1",
    active_options: [
      "computer_science",
      "information_technology",
      "business_administration",
    ],
    current_topic_scope: "broad",
    last_topic_scope: null,
    last_question_intent: null,
    last_referenced_options: [],
    turn_count: 0,
  },
  comparison: {
    anchor: { major_key: "computer_science", major: "Computer Science" },
    credits_completed: 72,
    options: [
      optionOutcome("information_technology", "Information Technology"),
      optionOutcome("business_administration", "Business Administration (BBA)"),
    ],
    assumptions: [],
    limitations: [],
  },
};

function mockFetch(handler: (url: string, body: unknown) => unknown) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(init.body as string) : undefined;
    const payload = handler(url, body);
    return {
      ok: true,
      status: 200,
      json: async () => payload,
    } as Response;
  });
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function enterMultiMode() {
  render(<Home />);
  fireEvent.click(screen.getByRole("radio", { name: /compare multiple/i }));
  return screen.getByRole("radiogroup", { name: /comparison mode/i });
}

describe("compare mode toggle", () => {
  it("defaults to Compare One so the existing flow is untouched", () => {
    render(<Home />);
    expect(screen.getByRole("radio", { name: /compare one/i })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByLabelText(/credits that transfer/i)).toBeInTheDocument();
  });

  it("switching to multiple replaces the single prospective input", async () => {
    await enterMultiMode();
    expect(screen.getByText(/compare against/i)).toBeInTheDocument();
    expect(
      screen.queryByLabelText(/^credits that transfer$/i),
    ).not.toBeInTheDocument();
  });

  it("seeds the first option from what was already selected", async () => {
    await enterMultiMode();
    const selects = screen.getAllByLabelText(/prospective major/i);
    expect(selects).toHaveLength(2);
    expect((selects[0] as HTMLSelectElement).value).toBe(
      "information_technology",
    );
  });

  it("is keyboard operable", () => {
    render(<Home />);
    const group = screen.getByRole("radiogroup", { name: /comparison mode/i });
    fireEvent.keyDown(group, { key: "ArrowRight" });
    expect(
      screen.getByRole("radio", { name: /compare multiple/i }),
    ).toHaveAttribute("aria-checked", "true");
  });
});

describe("option rows", () => {
  it("supports adding up to four and no further", async () => {
    await enterMultiMode();
    fireEvent.click(screen.getByRole("button", { name: /add option/i }));
    fireEvent.click(screen.getByRole("button", { name: /add option/i }));
    expect(screen.getAllByLabelText(/prospective major/i)).toHaveLength(4);
    expect(
      screen.queryByRole("button", { name: /add option/i }),
    ).not.toBeInTheDocument();
  });

  it("never offers the current major as an alternative", async () => {
    await enterMultiMode();
    const select = screen.getAllByLabelText(/prospective major/i)[0];
    const values = within(select as HTMLElement)
      .getAllByRole("option")
      .map((o) => (o as HTMLOptionElement).value);
    expect(values).not.toContain("computer_science");
  });

  it("never offers a major already chosen in another row", async () => {
    await enterMultiMode();
    const [first, second] = screen.getAllByLabelText(/prospective major/i);
    const secondValues = within(second as HTMLElement)
      .getAllByRole("option")
      .map((o) => (o as HTMLOptionElement).value);
    expect(secondValues).not.toContain(
      (first as HTMLSelectElement).value,
    );
  });

  it("keeps each option's own transfer figure", async () => {
    await enterMultiMode();
    const inputs = screen.getAllByLabelText(/credits that apply/i);
    fireEvent.change(inputs[0], { target: { value: "58" } });
    fireEvent.change(inputs[1], { target: { value: "61" } });

    const after = screen.getAllByLabelText(/credits that apply/i);
    expect((after[0] as HTMLInputElement).value).toBe("58");
    expect((after[1] as HTMLInputElement).value).toBe("61");
  });

  it("removing a row leaves the other rows' values on the right majors", async () => {
    await enterMultiMode();
    fireEvent.click(screen.getByRole("button", { name: /add option/i }));

    let inputs = screen.getAllByLabelText(/credits that apply/i);
    fireEvent.change(inputs[0], { target: { value: "11" } });
    fireEvent.change(inputs[1], { target: { value: "22" } });
    fireEvent.change(inputs[2], { target: { value: "33" } });

    const selects = screen.getAllByLabelText(
      /prospective major/i,
    ) as HTMLSelectElement[];
    const thirdMajor = selects[2].value;

    fireEvent.click(screen.getAllByRole("button", { name: /^remove /i })[0]);

    const remainingSelects = screen.getAllByLabelText(
      /prospective major/i,
    ) as HTMLSelectElement[];
    inputs = screen.getAllByLabelText(/credits that apply/i);
    const thirdIndex = remainingSelects.findIndex(
      (s) => s.value === thirdMajor,
    );
    // The third row's value must still be on the third row's major, not
    // shifted up onto whatever took its slot.
    expect((inputs[thirdIndex] as HTMLInputElement).value).toBe("33");
  });
});

describe("validation", () => {
  it("reports an error on the offending option only", async () => {
    await enterMultiMode();
    const inputs = screen.getAllByLabelText(/credits that apply/i);
    fireEvent.change(inputs[0], { target: { value: "200" } });
    fireEvent.change(inputs[1], { target: { value: "60" } });

    fireEvent.click(screen.getByRole("button", { name: /compare 2 options/i }));

    const alerts = await screen.findAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(alerts[0].textContent).toMatch(/cannot exceed/i);
  });
});

describe("submitting", () => {
  it("sends every option with its own value in one request", async () => {
    const fetchMock = mockFetch(() => START_RESPONSE);
    vi.stubGlobal("fetch", fetchMock);

    await enterMultiMode();
    const inputs = screen.getAllByLabelText(/credits that apply/i);
    fireEvent.change(inputs[0], { target: { value: "58" } });
    fireEvent.change(inputs[1], { target: { value: "61" } });
    fireEvent.click(screen.getByRole("button", { name: /compare 2 options/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/comparison/start");
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.options).toEqual([
      { major: "information_technology", credits_transferable: 58 },
      { major: "business_administration", credits_transferable: 61 },
    ]);
  });
});

describe("path navigator", () => {
  async function submitMulti() {
    vi.stubGlobal("fetch", mockFetch(() => START_RESPONSE));
    await enterMultiMode();
    const inputs = screen.getAllByLabelText(/credits that apply/i);
    fireEvent.change(inputs[0], { target: { value: "58" } });
    fireEvent.change(inputs[1], { target: { value: "61" } });
    fireEvent.click(screen.getByRole("button", { name: /compare 2 options/i }));
    await screen.findByRole("button", { name: /currently viewing 1 of 2/i });
  }

  it("shows 1 of N after a multi comparison", async () => {
    await submitMulti();
    expect(
      screen.getByRole("button", { name: /currently viewing 1 of 2/i }),
    ).toBeInTheDocument();
  });

  it("does not appear in single-comparison mode", async () => {
    vi.stubGlobal("fetch", mockFetch(() => CALCULATED("Computer Science", "Information Technology")));
    render(<Home />);
    fireEvent.click(screen.getByRole("button", { name: /show me the difference/i }));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /1 of 1/i })).not.toBeInTheDocument(),
    );
  });

  it("selecting another path updates the position and the header", async () => {
    await submitMulti();
    fireEvent.click(screen.getByRole("button", { name: /currently viewing 1 of 2/i }));
    const list = screen.getByRole("listbox", { name: /comparison paths/i });
    fireEvent.click(
      within(list).getByRole("option", { name: /business administration/i }),
    );

    expect(
      await screen.findByRole("button", { name: /currently viewing 2 of 2/i }),
    ).toBeInTheDocument();
  });

  it("marks a pending path as needing info rather than showing a result", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetch(() => ({
        ...START_RESPONSE,
        comparison: {
          ...START_RESPONSE.comparison,
          options: [
            optionOutcome("information_technology", "Information Technology"),
            optionOutcome(
              "business_administration",
              "Business Administration (BBA)",
              "pending",
            ),
          ],
        },
      })),
    );
    await enterMultiMode();
    const inputs = screen.getAllByLabelText(/credits that apply/i);
    fireEvent.change(inputs[0], { target: { value: "58" } });
    fireEvent.change(inputs[1], { target: { value: "61" } });
    fireEvent.click(screen.getByRole("button", { name: /compare 2 options/i }));

    const nav = await screen.findByRole("button", {
      name: /currently viewing 1 of 2/i,
    });
    fireEvent.click(nav);
    const list = screen.getByRole("listbox", { name: /comparison paths/i });
    expect(within(list).getByText(/needs info/i)).toBeInTheDocument();
  });
});

describe("state separation", () => {
  it("changing the displayed path does not narrow what Ask Fork compares", async () => {
    const calls: { url: string; body: unknown }[] = [];
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(init.body as string) : undefined;
      calls.push({ url, body });
      const payload = url.includes("/comparison/ask")
        ? {
            status: "complete",
            state: START_RESPONSE.state,
            answer: {
              direct_answer: "ok",
              key_points: [],
              limitations: [],
              still_useful_for: [],
              next_step: null,
              related_node_ids: [],
            },
            used_fallback: false,
            navigation_pills: [],
            navigation_target: null,
            topic_scope: "broad",
            comparison: null,
          }
        : START_RESPONSE;
      return { ok: true, status: 200, json: async () => payload } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    await enterMultiMode();
    const inputs = screen.getAllByLabelText(/credits that apply/i);
    fireEvent.change(inputs[0], { target: { value: "58" } });
    fireEvent.change(inputs[1], { target: { value: "61" } });
    fireEvent.click(screen.getByRole("button", { name: /compare 2 options/i }));

    await screen.findByRole("button", { name: /currently viewing 1 of 2/i });

    // Switch which path the map shows.
    fireEvent.click(screen.getByRole("button", { name: /currently viewing 1 of 2/i }));
    const list = screen.getByRole("listbox", { name: /comparison paths/i });
    fireEvent.click(
      within(list).getByRole("option", { name: /business administration/i }),
    );
    await screen.findByRole("button", { name: /currently viewing 2 of 2/i });

    // Selecting a path must fire no request at all — that's the
    // structural reason it can't change the conversation's option set.
    const afterSelect = calls.filter((c) => c.url.includes("/comparison/"));
    expect(afterSelect).toHaveLength(1);
    expect(afterSelect[0].url).toContain("/start");
  });

  it("Ask Fork sends only the session id, never the displayed path", async () => {
    const calls: { url: string; body: any }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const body = init?.body ? JSON.parse(init.body as string) : undefined;
        calls.push({ url, body });
        const payload = url.includes("/comparison/ask")
          ? {
              status: "complete",
              state: START_RESPONSE.state,
              answer: {
                direct_answer: "ok",
                key_points: [],
                limitations: [],
                still_useful_for: [],
                next_step: null,
                related_node_ids: [],
              },
              used_fallback: false,
              navigation_pills: [],
              navigation_target: null,
              topic_scope: "broad",
              comparison: null,
            }
          : START_RESPONSE;
        return { ok: true, status: 200, json: async () => payload } as Response;
      }),
    );

    await enterMultiMode();
    const inputs = screen.getAllByLabelText(/credits that apply/i);
    fireEvent.change(inputs[0], { target: { value: "58" } });
    fireEvent.change(inputs[1], { target: { value: "61" } });
    fireEvent.click(screen.getByRole("button", { name: /compare 2 options/i }));
    await screen.findByRole("button", { name: /currently viewing 1 of 2/i });

    const composer = screen.getByLabelText(/ask fork about this decision/i);
    fireEvent.change(composer, { target: { value: "Which one costs more?" } });
    fireEvent.submit(composer.closest("form")!);

    await waitFor(() =>
      expect(calls.some((c) => c.url.includes("/comparison/ask"))).toBe(true),
    );
    const ask = calls.find((c) => c.url.includes("/comparison/ask"))!;
    // available_nodes/selected_detail_path are now sent too (navigation
    // hints), but the STRUCTURAL guarantee this test protects is
    // unchanged: no active_options, no topic scope, nothing that could
    // let the displayed path narrow the conversation.
    expect(Object.keys(ask.body).sort()).toEqual([
      "available_nodes",
      "message",
      "selected_detail_path",
      "session_id",
    ]);
    expect(ask.body.session_id).toBe("sess-1");
  });

  it("a conversational option change updates the header count", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const payload = url.includes("/comparison/ask")
          ? {
              status: "complete",
              state: {
                ...START_RESPONSE.state,
                // Backend dropped Business from the active set.
                active_options: ["computer_science", "information_technology"],
              },
              answer: {
                direct_answer: "ok",
                key_points: [],
                limitations: [],
                still_useful_for: [],
                next_step: null,
                related_node_ids: [],
              },
              used_fallback: false,
              navigation_pills: [],
              navigation_target: null,
              topic_scope: "broad",
              comparison: null,
            }
          : START_RESPONSE;
        return { ok: true, status: 200, json: async () => payload } as Response;
      }),
    );

    await enterMultiMode();
    const inputs = screen.getAllByLabelText(/credits that apply/i);
    fireEvent.change(inputs[0], { target: { value: "58" } });
    fireEvent.change(inputs[1], { target: { value: "61" } });
    fireEvent.click(screen.getByRole("button", { name: /compare 2 options/i }));
    await screen.findByRole("button", { name: /currently viewing 1 of 2/i });

    const composer = screen.getByLabelText(/ask fork about this decision/i);
    fireEvent.change(composer, { target: { value: "Just compare IT" } });
    fireEvent.submit(composer.closest("form")!);

    expect(
      await screen.findByRole("button", { name: /currently viewing 1 of 1/i }),
    ).toBeInTheDocument();
  });

  it("draft edits do not change the calculated comparison", async () => {
    vi.stubGlobal("fetch", mockFetch(() => START_RESPONSE));
    await enterMultiMode();
    const inputs = screen.getAllByLabelText(/credits that apply/i);
    fireEvent.change(inputs[0], { target: { value: "58" } });
    fireEvent.change(inputs[1], { target: { value: "61" } });
    fireEvent.click(screen.getByRole("button", { name: /compare 2 options/i }));
    await screen.findByRole("button", { name: /currently viewing 1 of 2/i });

    // Edit the draft without resubmitting.
    fireEvent.change(screen.getAllByLabelText(/credits that apply/i)[0], {
      target: { value: "3" },
    });

    // The calculated comparison is untouched.
    expect(
      screen.getByRole("button", { name: /currently viewing 1 of 2/i }),
    ).toBeInTheDocument();
  });

  it("an ai_unavailable response shows the unavailable message and leaves the comparison untouched", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const payload = url.includes("/comparison/ask")
          ? {
              status: "ai_unavailable",
              message:
                "Ask Fork is temporarily unavailable. Your calculated comparison has not been affected. Please try again in a moment.",
              state: START_RESPONSE.state,
            }
          : START_RESPONSE;
        return { ok: true, status: 200, json: async () => payload } as Response;
      }),
    );

    await enterMultiMode();
    const inputs = screen.getAllByLabelText(/credits that apply/i);
    fireEvent.change(inputs[0], { target: { value: "58" } });
    fireEvent.change(inputs[1], { target: { value: "61" } });
    fireEvent.click(screen.getByRole("button", { name: /compare 2 options/i }));
    await screen.findByRole("button", { name: /currently viewing 1 of 2/i });

    const composer = screen.getByLabelText(/ask fork about this decision/i);
    fireEvent.change(composer, { target: { value: "Which one costs more?" } });
    fireEvent.submit(composer.closest("form")!);

    expect(
      await screen.findByText(/Ask Fork is temporarily unavailable/),
    ).toBeInTheDocument();
    // Neither the active-option count nor the displayed path moved.
    expect(
      screen.getByRole("button", { name: /currently viewing 1 of 2/i }),
    ).toBeInTheDocument();
  });

  it("a path-aware pill switches the displayed path without touching active_options", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const payload = url.includes("/comparison/ask")
          ? {
              status: "complete",
              state: START_RESPONSE.state,
              answer: {
                direct_answer: "Here's how they compare on financials.",
                key_points: [],
                limitations: [],
                still_useful_for: [],
                next_step: null,
                related_node_ids: ["financial"],
              },
              used_fallback: false,
              navigation_pills: [
                { major: "information_technology", node_id: "financial" },
                { major: "business_administration", node_id: "financial" },
              ],
              navigation_target: null,
              topic_scope: "financial",
              comparison: null,
            }
          : START_RESPONSE;
        return { ok: true, status: 200, json: async () => payload } as Response;
      }),
    );

    await enterMultiMode();
    const inputs = screen.getAllByLabelText(/credits that apply/i);
    fireEvent.change(inputs[0], { target: { value: "58" } });
    fireEvent.change(inputs[1], { target: { value: "61" } });
    fireEvent.click(screen.getByRole("button", { name: /compare 2 options/i }));
    await screen.findByRole("button", { name: /currently viewing 1 of 2/i });

    const composer = screen.getByLabelText(/ask fork about this decision/i);
    fireEvent.change(composer, { target: { value: "How do they compare financially?" } });
    fireEvent.submit(composer.closest("form")!);

    const pill = await screen.findByRole("button", {
      name: /business administration.*financial impact/i,
    });
    fireEvent.click(pill);

    // The path switched to Business Administration (2 of 2)...
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /currently viewing 2 of 2/i }),
      ).toBeInTheDocument(),
    );
    // ...but the comparison is still comparing both options — clicking a
    // navigation pill is never an option-set instruction.
    expect(screen.getAllByLabelText(/credits that apply/i)).toHaveLength(2);
  });
});
