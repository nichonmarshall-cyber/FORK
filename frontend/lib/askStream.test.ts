import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, explainDecision, type AskStage } from "./types";

const BODY = {
  current_major: "computer_science",
  prospective_major: "information_technology",
  credits_completed: 72,
  credits_transferable: 66,
  question: "Explain the biggest difference",
};

function sse(blocks: string[], chunkSplit = 7): Response {
  const text = blocks.join("");
  const encoder = new TextEncoder();
  // Deliberately split mid-event, the way a network delivers it.
  const chunks: Uint8Array[] = [];
  for (let i = 0; i < text.length; i += chunkSplit) chunks.push(encoder.encode(text.slice(i, i + chunkSplit)));
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(c);
      controller.close();
    },
  });
  return new Response(stream, { status: 200, headers: { "content-type": "text/event-stream" } });
}

const ev = (name: string, data: unknown) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;

afterEach(() => vi.unstubAllGlobals());

describe("explainDecision over the stream", () => {
  it("reports each stage in order, then resolves with the answer", async () => {
    const answer = { status: "complete", state: { session_id: "s" }, direct_answer: "A." };
    const fetchMock = vi.fn(async () =>
      sse([ev("stage", "received"), ev("stage", "understanding"), ev("stage", "writing"), ev("stage", "checking"), ev("result", answer)]),
    );
    vi.stubGlobal("fetch", fetchMock);
    const stages: AskStage[] = [];
    const result = await explainDecision(BODY, (s) => stages.push(s));
    expect(stages).toEqual(["received", "understanding", "writing", "checking"]);
    expect(result).toEqual(answer);
    expect(String((fetchMock.mock.calls[0] as unknown[])[0])).toMatch(/\/explain\/stream$/);
  });

  it("hands over an early direct answer before resolving with the full one", async () => {
    const answer = { status: "complete", state: { session_id: "s" }, direct_answer: "A." };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sse([ev("stage", "writing"), ev("partial", { direct_answer: "A." }), ev("stage", "checking"), ev("result", answer)]),
      ),
    );
    const seen: string[] = [];
    const result = await explainDecision(BODY, {
      onStage: (s) => seen.push(`stage:${s}`),
      onPartial: (p) => seen.push(`partial:${p.direct_answer}`),
    });
    expect(seen).toEqual(["stage:writing", "partial:A.", "stage:checking"]);
    expect(result).toEqual(answer);
  });

  it("turns a streamed error into the usual ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => sse([ev("stage", "received"), ev("error", { status_code: 404, detail: "No such institution." })])),
    );
    await expect(explainDecision(BODY)).rejects.toThrow(new ApiError("No such institution."));
  });

  it("falls back to the plain endpoint when the stream route doesn't exist", async () => {
    const answer = { status: "complete", state: { session_id: "s" }, direct_answer: "B." };
    const fetchMock = vi.fn(async (url: string) =>
      url.endsWith("/stream")
        ? new Response('{"detail":"Not Found"}', { status: 404, headers: { "content-type": "application/json" } })
        : new Response(JSON.stringify(answer), { status: 200, headers: { "content-type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    expect(await explainDecision(BODY)).toEqual(answer);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
