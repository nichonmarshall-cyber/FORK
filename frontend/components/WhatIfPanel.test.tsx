// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import WhatIfPanel from "./WhatIfPanel";
import type { AuditSession, DocumentsState } from "@/lib/audit";

/**
 * The What-If slot.
 *
 * Two behaviours matter more than the rest: a document supplies credits to
 * exactly one program, and a disagreement between confirmed documents has to
 * be read before it can be waved through. Both are enforced on the backend —
 * these check the UI doesn't route around them or misreport what happened.
 */

afterEach(cleanup);

function documents(over: Partial<DocumentsState> = {}): DocumentsState {
  return {
    current_audit: { present: true, confirmed: true },
    what_if: {
      present: true,
      confirmed: true,
      classification: {
        role: "what_if_audit",
        program_name: "Bachelor of Science in Computer Science",
        program_code: "ENBS CSCI",
        catalog_year: "Fall 2026",
        prepared_at: "03/30/2026 07:21 PM",
        match: {
          quality: "exact",
          program_key: "computer_science",
          candidates: [],
          reason: null,
        },
      },
    },
    transcript: { present: false, supported: false, message: "Not supported yet." },
    resolved: {
      credits_completed: 81,
      credits_in_progress: 18,
      credits_source: "UNT Degree Audit, confirmed by you",
      credits_source_date: "08/18/2026 03:18 PM",
      option_credits: {
        program_key: "computer_science",
        credits_transferable: 66,
        source: "UNT What-If Audit — Computer Science, Fall 2026, confirmed by you",
        source_date: "03/30/2026 07:21 PM",
      },
      manual_restore: {},
      discrepancies: [],
      requires_acknowledgement: false,
      unresolved: [],
    },
    evidence_fingerprint: "fp-abc",
    ...over,
  };
}

const session = { session_id: "s1" } as AuditSession;
const labels: Record<string, string> = {
  computer_science: "Computer Science",
  psychology_ba: "Psychology (B.A.)",
  psychology_bs: "Psychology (B.S.)",
};

function renderPanel(
  docs: DocumentsState = documents(),
  selectedProgramKey = "computer_science",
) {
  const onSession = vi.fn();
  render(
    <WhatIfPanel
      session={session}
      documents={docs}
      onSession={onSession}
      optionLabel={(k) => labels[k] ?? k}
      selectedProgramKey={selectedProgramKey}
    />,
  );
  return { onSession };
}

describe("uploading", () => {
  it("offers a dropzone when no document is present", () => {
    renderPanel(
      documents({
        what_if: { present: false, confirmed: false, classification: null },
      }),
    );
    expect(screen.getByText(/drop a what-if audit here/i)).toBeTruthy();
  });

  it("says what a What-If is for rather than assuming the student knows", () => {
    renderPanel(
      documents({
        what_if: { present: false, confirmed: false, classification: null },
      }),
    );
    expect(screen.getByText(/instead of asking you to estimate/i)).toBeTruthy();
  });
});

describe("naming the document", () => {
  it("shows the specific document, not 'your degree audit'", () => {
    renderPanel();
    expect(
      screen.getByText(/UNT What-If Audit — Bachelor of Science in Computer Science — Fall 2026/),
    ).toBeTruthy();
  });
});

describe("program matching", () => {
  it("names the program it will supply before confirmation", () => {
    const docs = documents();
    docs.what_if.confirmed = false;
    docs.resolved.option_credits = null;
    renderPanel(docs);
    expect(screen.getByText(/right document for Computer Science/i)).toBeTruthy();
  });

  it("says which programs it could be when ambiguous, and offers no confirm", () => {
    const docs = documents();
    docs.what_if.confirmed = false;
    docs.resolved.option_credits = null;
    docs.what_if.classification!.match = {
      quality: "ambiguous",
      program_key: null,
      candidates: ["psychology_ba", "psychology_bs"],
      reason: "'Psychology' matches 2 known programs.",
    };
    renderPanel(docs);

    expect(screen.getByText(/Psychology \(B\.A\.\) or Psychology \(B\.S\.\)/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /use this what-if/i })).toBeNull();
  });

  it("reports which program the credits went to, so a wrong match is visible", () => {
    renderPanel();
    expect(screen.getByText(/66 credits toward Computer Science/i)).toBeTruthy();
  });
});

describe("discrepancies", () => {
  function withDiscrepancy(): DocumentsState {
    const docs = documents();
    docs.resolved.requires_acknowledgement = true;
    docs.resolved.option_credits = null;
    docs.resolved.discrepancies = [
      {
        code: "document_date_gap",
        magnitude: "140 days",
        technical_detail: "prepared_at differs by 140 days",
        user_message:
          "These two documents were prepared about 4 months apart. The older one may not include coursework you've finished since.",
      },
    ];
    return docs;
  }

  it("shows the full explanation rather than a count", () => {
    renderPanel(withDiscrepancy());
    expect(screen.getByText(/about 4 months apart/i)).toBeTruthy();
  });

  it("withholds the credits until acknowledged", () => {
    renderPanel(withDiscrepancy());
    expect(screen.queryByText(/credits toward Computer Science/i)).toBeNull();
    expect(screen.getByRole("button", { name: /use both documents/i })).toBeTruthy();
  });

  it("is ready to acknowledge when a fingerprint is present", () => {
    // The fingerprint is what ties permission to the documents that were on
    // screen; without it the backend would have nothing to compare against
    // and stale consent could carry onto changed documents.
    const docs = withDiscrepancy();
    renderPanel(docs);
    expect(docs.evidence_fingerprint).toBe("fp-abc");
    expect(
      screen
        .getByRole("button", { name: /use both documents/i })
        .hasAttribute("disabled"),
    ).toBe(false);
  });

  it("cannot acknowledge without a fingerprint", () => {
    const docs = withDiscrepancy();
    docs.evidence_fingerprint = null;
    renderPanel(docs);
    expect(
      screen
        .getByRole("button", { name: /use both documents/i })
        .hasAttribute("disabled"),
    ).toBe(true);
  });
});

describe("dormancy", () => {
  it("does not claim credits were applied to the option on screen", () => {
    // The reported bug: a Psychology What-If rendering "Using 66 credits
    // toward Psychology" while the form said Information Technology.
    renderPanel(documents(), "information_technology");
    expect(screen.queryByText(/Using 66 credits/i)).toBeNull();
  });

  it("says which option it is kept for, and how to use it", () => {
    renderPanel(documents(), "information_technology");
    expect(screen.getByText(/Kept for Computer Science/i)).toBeTruthy();
    expect(screen.getByText(/switch to it/i)).toBeTruthy();
  });

  it("reports the credits once the matching option is selected", () => {
    renderPanel(documents(), "computer_science");
    expect(screen.getByText(/Using 66 credits toward Computer Science/i)).toBeTruthy();
  });
});

describe("unresolved reasons", () => {
  it("explains why a present document supplied nothing", () => {
    const docs = documents();
    docs.resolved.option_credits = null;
    docs.resolved.unresolved = [
      "This What-If audit doesn't state how many hours apply to the degree overall, so Fork can't use it for that figure yet.",
    ];
    renderPanel(docs);
    expect(screen.getByText(/doesn't state how many hours apply/i)).toBeTruthy();
  });

  it("never claims verification", () => {
    const { container } = render(
      <WhatIfPanel
        session={session}
        documents={documents()}
        onSession={vi.fn()}
        optionLabel={(k) => labels[k] ?? k}
        selectedProgramKey="computer_science"
      />,
    );
    expect(container.textContent?.toLowerCase()).not.toContain("verif");
  });
});