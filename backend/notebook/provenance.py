"""
The four kinds of evidence a notebook fact can rest on.

    confirmed_document  read from a document by Fork and confirmed by the
                        student as a correct reading. NOT verified with the
                        university -- "confirmed" never means "verified".
    student_reported    typed by the student. Their own figure.
    derived             calculated by Fork's deterministic logic from other
                        facts and published reference data.
    what_if             read from a confirmed What-If audit: true for one
                        hypothetical program only, never for the student's
                        record as a whole.

The words a student sees live here too, so no screen has to invent its own
phrasing for these.
"""

CONFIRMED_DOCUMENT = "confirmed_document"
STUDENT_REPORTED = "student_reported"
DERIVED = "derived"
WHAT_IF = "what_if"

ALL = (CONFIRMED_DOCUMENT, STUDENT_REPORTED, DERIVED, WHAT_IF)

LABELS = {
    CONFIRMED_DOCUMENT: "From a document you confirmed",
    STUDENT_REPORTED: "You reported this",
    DERIVED: "Calculated by Fork",
    WHAT_IF: "What-If scenario",
}

#: The source strings the existing engine and audit flow already emit.
#: Matching them exactly is how a saved comparison's inputs are checked
#: against the notebook rather than trusted as labels.
CONFIRMED_AUDIT_SOURCE = "UNT Degree Audit, confirmed by you"
WHAT_IF_SOURCE_PREFIX = "UNT What-If Audit"
STUDENT_SOURCE = "Student-reported"
