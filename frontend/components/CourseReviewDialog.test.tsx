// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import CourseReviewDialog from "./CourseReviewDialog";
import type { ReviewCourse, ReviewSummary } from "@/lib/audit";

/**
 * The dialog exists because 36 courses didn't fit in the sidebar. These
 * check the two things that made the inline version bad — cramped layout
 * and no way to fix a misread — plus the ways it can be closed, since
 * discarding someone's corrections by accident is worse than an extra
 * prompt.
 *
 * Nothing here asserts a total. The dialog deliberately doesn't compute
 * any: totals come back from the backend after corrections are saved, and
 * a second arithmetic path in the UI would eventually disagree with the
 * parser's reconciled one.
 */

function course(over: Partial<ReviewCourse> = {}): ReviewCourse {
  return {
    key: "26.1:CSCE2110",
    course_code: "CSCE 2110",
    title: "FDNS DATA STRUCTURES",
    hours: 3,
    grade: "A",
    term: "Spring 2026",
    status: "completed",
    status_label: "Completed",
    note: null,
    source_label: "UNT Degree Audit",
    ...over,
  };
}

function review(over: Partial<ReviewSummary> = {}): ReviewSummary {
  return {
    program: "Bachelor of Science in Computer Science",
    catalog_year: "Fall 2024",
    prepared_at: "08/18/2026 03:18 PM",
    is_what_if: false,
    completed_hours: 81,
    in_progress_hours: 18,
    course_count: 36,
    headline: "Here's what we read from your audit.",
    checkpoints: [],
    notices: [
      "2 repeated courses are listed separately. Your audit counts only the most recent attempt, and so do we.",
    ],
    totals_confirmed: true,
    courses: Array.from({ length: 36 }, (_, i) =>
      course({ key: `26.1:C${i}`, course_code: `CSCE ${1000 + i}` }),
    ),
    excluded_courses: [
      course({
        key: "23.8:MATH1100",
        course_code: "MATH 1100",
        hours: 0,
        grade: "F",
        status: "not_counted",
        status_label: "Not counted toward hours",
        note: "A later attempt at this course is the one that counts.",
      }),
    ],
    ...over,
  };
}

function renderDialog(props: Partial<Parameters<typeof CourseReviewDialog>[0]> = {}) {
  const onClose = vi.fn();
  const onSave = vi.fn();
  render(
    <CourseReviewDialog
      review={review()}
      open
      saving={false}
      fieldErrors={{}}
      onClose={onClose}
      onSave={onSave}
      {...props}
    />,
  );
  return { onClose, onSave };
}

beforeEach(() => {
  document.body.style.overflow = "";
});

afterEach(cleanup);

describe("opening and closing", () => {
  it("renders nothing when closed", () => {
    renderDialog({ open: false });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shows the courses when open", () => {
    renderDialog();
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getAllByText(/CSCE 10/).length).toBeGreaterThan(0);
  });

  it("closes on the close button", () => {
    const { onClose } = renderDialog();
    fireEvent.click(screen.getByLabelText("Close"));
    expect(onClose).toHaveBeenCalled();
  });

  it("closes on Escape", () => {
    const { onClose } = renderDialog();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("closes on a backdrop click", () => {
    const { onClose } = renderDialog();
    const backdrop = screen.getByRole("dialog").parentElement!;
    fireEvent.mouseDown(backdrop);
    expect(onClose).toHaveBeenCalled();
  });

  it("does not close when the mouse merely ends on the backdrop", () => {
    // Selecting text inside the dialog and releasing outside it shouldn't
    // count as a dismissal.
    const { onClose } = renderDialog();
    fireEvent.mouseDown(screen.getByRole("dialog"));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("locks background scrolling while open", () => {
    renderDialog();
    expect(document.body.style.overflow).toBe("hidden");
  });
});

describe("protecting unsaved corrections", () => {
  function startEditing() {
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const input = screen.getAllByLabelText(/^hours for/)[0];
    fireEvent.change(input, { target: { value: "4" } });
  }

  it("asks before discarding on Escape", () => {
    const { onClose } = renderDialog();
    startEditing();
    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByText(/unsaved corrections/i)).toBeTruthy();
  });

  it("keeps editing when the student declines", () => {
    const { onClose } = renderDialog();
    startEditing();
    fireEvent.click(screen.getByLabelText("Close"));
    fireEvent.click(screen.getByRole("button", { name: /keep editing/i }));

    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes when the student confirms the discard", () => {
    const { onClose } = renderDialog();
    startEditing();
    fireEvent.click(screen.getByLabelText("Close"));
    fireEvent.click(screen.getByRole("button", { name: /discard/i }));

    expect(onClose).toHaveBeenCalled();
  });

  it("closes without asking when nothing was edited", () => {
    const { onClose } = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalled();
  });
});

describe("corrections", () => {
  it("sends only the fields that were actually changed", () => {
    const { onSave } = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getAllByLabelText(/^hours for/)[0], {
      target: { value: "4" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save corrections/i }));

    expect(onSave).toHaveBeenCalledWith([
      { field: "hours", value: 4, course_key: "26.1:C0" },
    ]);
  });

  it("sends hours as a number and text fields as strings", () => {
    const { onSave } = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getAllByLabelText(/^hours for/)[0], {
      target: { value: "4" },
    });
    fireEvent.change(screen.getAllByLabelText(/^grade for/)[0], {
      target: { value: "B" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save corrections/i }));

    const sent = onSave.mock.calls[0][0];
    expect(sent).toContainEqual({ field: "hours", value: 4, course_key: "26.1:C0" });
    expect(sent).toContainEqual({ field: "grade", value: "B", course_key: "26.1:C0" });
  });

  it("cannot save with nothing changed", () => {
    renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(
      screen.getByRole("button", { name: /save corrections/i }).hasAttribute("disabled"),
    ).toBe(true);
  });

  it("cancel drops staged edits and leaves editing mode", () => {
    const { onSave } = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getAllByLabelText(/^hours for/)[0], {
      target: { value: "4" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onSave).not.toHaveBeenCalled();
    // Back to read-only, and Escape no longer prompts — the edits are gone.
    expect(screen.getByRole("button", { name: "Edit" })).toBeTruthy();
  });

  it("shows a rejected field's message beside that field", () => {
    renderDialog({
      fieldErrors: { "26.1:C0:hours": "Hours must be a number." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(screen.getByText("Hours must be a number.")).toBeTruthy();
  });

  it("disables save while a save is in flight", () => {
    renderDialog({ saving: true });
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getAllByLabelText(/^hours for/)[0], {
      target: { value: "4" },
    });
    expect(
      screen.getByRole("button", { name: /saving/i }).hasAttribute("disabled"),
    ).toBe(true);
  });
});

describe("what stays visible", () => {
  it("keeps the repeated-course notice", () => {
    renderDialog();
    expect(screen.getByText(/2 repeated courses are listed separately/)).toBeTruthy();
  });

  it("lists repeated attempts as their own rows rather than merging them", () => {
    renderDialog();
    expect(screen.getByText(/Repeated attempts/i)).toBeTruthy();
    expect(screen.getAllByText("MATH 1100").length).toBeGreaterThan(0);
  });

  it("does not let repeated attempts be edited", () => {
    // They carry zero hours and exist to show history. Editing one would
    // imply it could be made to count, which the audit doesn't allow.
    renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(screen.queryByLabelText("hours for MATH 1100")).toBeNull();
  });

  it("shows the document identity so a wrong upload is obvious", () => {
    renderDialog();
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/Bachelor of Science in Computer Science/)).toBeTruthy();
    expect(within(dialog).getByText(/Fall 2024/)).toBeTruthy();
  });

  it("renders all 36 courses", () => {
    renderDialog();
    // Six editable/readable columns per row; the count is what matters.
    expect(screen.getAllByText(/^CSCE 10\d\d$/).length).toBeGreaterThanOrEqual(36);
  });
});