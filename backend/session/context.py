"""
The academic context for one session.

Exactly one academic source is active at a time. A student either typed their
numbers in or uploaded a document and confirmed what Fork read from it, and the
two never contribute values at once — a screen showing a manual estimate beside
a document-derived figure invites the reader to average them, and the average
of a guess and a measurement is a guess.

Switching back to manual clears the uploaded record. That is a deliberate
choice for a prototype: keeping it around would mean deciding what to do when a
student edits their manual numbers while a stale parsed record sits behind
them, and the honest answer at this stage is not to keep two.

Nothing here persists. The record lives in memory for as long as the process
does, which is the whole intended lifetime.
"""

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from academic_record.enums import (
    AcademicInputMode,
    ConfirmationStatus,
    ExtractionStatus,
)
from academic_record.models import StudentAcademicRecord


class CorrectionRequest(BaseModel):
    """One student edit to the extracted record.

    `course_key` targets a course; omit it to target a document-level field
    such as `catalog_year`.
    """

    field: str
    value: str | float | None = None
    course_key: str | None = None


class CorrectionOutcome(BaseModel):
    applied: bool
    field: str
    course_key: str | None = None
    previous_value: str | None = None
    new_value: str | None = None
    message: str | None = None


#: Document-level fields a student may correct. Deliberately narrow: parser
#: diagnostics and computed totals are not editable, because editing a total
#: rather than the coursework behind it produces a record that no longer
#: describes any real transcript.
EDITABLE_RECORD_FIELDS = frozenset(
    {"program", "program_code", "catalog_year", "audit_prepared_at"}
)

#: Course fields a student may correct.
EDITABLE_COURSE_FIELDS = frozenset(
    {"subject", "number", "title", "hours", "grade", "term_code", "completion_status"}
)


class StoredDocument(BaseModel):
    """One academic document held for the session.

    `correction_revision` exists so an acknowledgement can be tied to the
    exact version of a document the student was shown. Totals alone aren't
    enough: an edit that lands back on the same number is still a different
    document than the one they agreed to proceed with.
    """

    document_id: str
    record: StudentAcademicRecord
    confirmation_status: ConfirmationStatus = ConfirmationStatus.AWAITING_REVIEW
    correction_revision: int = 0

    @property
    def is_confirmed(self) -> bool:
        return self.confirmation_status == ConfirmationStatus.CONFIRMED


class UploadedSourceState(BaseModel):
    """Whether an uploaded record exists, and where it stands.

    Reported separately from the active mode so a client never has to infer
    one from the other. The combination that matters: `present=True` with
    `is_active=False` is a document parsed and waiting to be reviewed while
    manual entry is still driving the calculation.
    """

    present: bool
    confirmation_status: ConfirmationStatus | None = None
    is_active: bool = False
    awaiting_review: bool = False


class SessionAcademicContext(BaseModel):
    """Which academic information a session is currently working from."""

    session_id: str
    mode: AcademicInputMode = AcademicInputMode.MANUAL
    uploaded_record: StudentAcademicRecord | None = None
    confirmation_status: ConfirmationStatus | None = None
    # One current audit, one What-If, one transcript slot. Deliberately not a
    # generic list: the demo compares one current program against one
    # prospective one, and a collection that permits four What-Ifs implies a
    # workflow that doesn't exist yet.
    what_if_document: StoredDocument | None = None
    transcript_document: StoredDocument | None = Field(
        default=None,
        description="Reserved. No transcript parser exists -- the UI says so "
                    "rather than accepting a file and doing nothing with it.",
    )

    #: What the student typed before a document took over that option, so
    #: reverting restores their own figure rather than an empty field.
    manual_transferable_by_major: dict[str, int] = Field(default_factory=dict)

    #: The evidence fingerprint an acknowledgement was given for. Compared
    #: rather than trusted: any change to the documents produces a different
    #: fingerprint, so old permission cannot carry onto new facts.
    acknowledged_evidence: str | None = None

    degree_match_results: dict | None = Field(
        default=None,
        description="Reserved for the matcher, which is not built yet. Present "
                    "so the session shape doesn't change when it arrives.",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def has_confirmed_record(self) -> bool:
        return (
            self.uploaded_record is not None
            and self.confirmation_status == ConfirmationStatus.CONFIRMED
        )

    @property
    def active_source_description(self) -> str:
        """How to describe the active source to a student.

        Never says "verified". Fork checked that its own reading matches what
        the student says is true; it did not check anything with UNT.

        A label for rendering, not a state to branch on — read `uploaded_source`
        for that.
        """
        if self.mode == AcademicInputMode.CONFIRMED_UPLOAD and self.has_confirmed_record:
            return "the academic information you confirmed"
        return "the information you entered"

    @property
    def uploaded_source(self) -> "UploadedSourceState":
        """The uploaded record's state, independent of which mode is active.

        These are two genuinely separate facts and collapsing them loses a
        case the review UI needs. A parsed record awaiting review exists while
        manual is still the active source — that is the entire review step, and
        a client that infers "is there a document?" from the active mode
        concludes there isn't one.
        """
        if self.uploaded_record is None:
            return UploadedSourceState(present=False)

        return UploadedSourceState(
            present=True,
            confirmation_status=self.confirmation_status,
            is_active=self.mode == AcademicInputMode.CONFIRMED_UPLOAD
            and self.has_confirmed_record,
            awaiting_review=self.confirmation_status
            == ConfirmationStatus.AWAITING_REVIEW,
        )

    def attach_record(self, record: StudentAcademicRecord) -> None:
        """Hold a freshly parsed record pending review.

        Attaching does not switch modes. A record that hasn't been looked at
        yet is not something to calculate from, so the session stays in manual
        until the student confirms.
        """
        self.uploaded_record = record
        self.confirmation_status = ConfirmationStatus.AWAITING_REVIEW
        self.touch()

    def apply_correction(self, correction: CorrectionRequest) -> CorrectionOutcome:
        """Apply one student edit, recording what it replaced.

        Any edit returns the record to awaiting-review. Confirmation applies to
        a specific set of values, so changing one after the fact would leave the
        session claiming the student had agreed to something they hadn't seen.
        """
        if self.uploaded_record is None:
            return CorrectionOutcome(
                applied=False,
                field=correction.field,
                course_key=correction.course_key,
                message="There is no uploaded record to correct.",
            )

        if correction.course_key is not None:
            outcome = self._correct_course(correction)
        else:
            outcome = self._correct_record_field(correction)

        if outcome.applied:
            self.confirmation_status = ConfirmationStatus.AWAITING_REVIEW
            self._recheck_totals()
            self.touch()
        return outcome

    def apply_corrections(
        self, corrections: list[CorrectionRequest]
    ) -> list[CorrectionOutcome]:
        """Apply a batch of edits, reconciling once at the end.

        The review dialog submits everything the student changed in one go.
        Applying them individually would re-run the totals check after each
        field and report intermediate states that never existed on screen.

        Outcomes come back per correction, so a batch where one field is
        invalid still applies the rest and says which one failed rather than
        rejecting the lot.
        """
        outcomes = [self.apply_correction(c) for c in corrections]
        self._recheck_totals()
        return outcomes

    def _recheck_totals(self) -> None:
        """Re-run the parser's self-check against the corrected record.

        `reconciliation` is computed at parse time and stored, while
        `completed_hours` is derived live. Without this the two drift apart
        the moment a student edits an hours field: the totals move and the
        check keeps comparing the figures it saw originally.

        The comparison is still against what the *document* stated, which is
        the point — a correction that pulls the totals away from the printed
        figures is exactly what the student should be told about, not
        something to paper over by re-baselining.
        """
        record = self.uploaded_record
        if record is None or record.reconciliation is None:
            return

        from academic_record.enums import CompletionStatus

        record.reconciliation = record.reconciliation.model_copy(
            update={
                "computed_completed_hours": round(
                    sum(c.hours for c in record.courses if c.counts_toward_earned_hours), 1
                ),
                "computed_in_progress_hours": round(
                    sum(
                        c.hours
                        for c in record.courses
                        if c.completion_status == CompletionStatus.IN_PROGRESS
                    ),
                    1,
                ),
            }
        )

    def _correct_course(self, correction: CorrectionRequest) -> CorrectionOutcome:
        record = self.uploaded_record
        assert record is not None

        course = record.course_by_key(correction.course_key or "")
        if course is None:
            return CorrectionOutcome(
                applied=False,
                field=correction.field,
                course_key=correction.course_key,
                message="That course is not in this record.",
            )
        if correction.field not in EDITABLE_COURSE_FIELDS:
            return CorrectionOutcome(
                applied=False,
                field=correction.field,
                course_key=correction.course_key,
                message=f"'{correction.field}' cannot be edited.",
            )

        previous = getattr(course, correction.field)
        value = correction.value
        if correction.field == "hours":
            try:
                value = float(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return CorrectionOutcome(
                    applied=False,
                    field=correction.field,
                    course_key=correction.course_key,
                    message="Hours must be a number.",
                )

        setattr(course, correction.field, value)
        course.provenance = course.provenance.corrected(str(previous))

        return CorrectionOutcome(
            applied=True,
            field=correction.field,
            course_key=correction.course_key,
            previous_value=str(previous),
            new_value=str(value),
        )

    def _correct_record_field(self, correction: CorrectionRequest) -> CorrectionOutcome:
        record = self.uploaded_record
        assert record is not None

        if correction.field not in EDITABLE_RECORD_FIELDS:
            return CorrectionOutcome(
                applied=False,
                field=correction.field,
                message=f"'{correction.field}' cannot be edited.",
            )

        previous = getattr(record, correction.field)
        setattr(record, correction.field, correction.value)

        existing = record.field_provenance.get(correction.field)
        if existing is None:
            from academic_record.provenance import extracted

            existing = extracted()
        record.field_provenance[correction.field] = existing.corrected(str(previous))

        return CorrectionOutcome(
            applied=True,
            field=correction.field,
            previous_value=str(previous),
            new_value=str(correction.value),
        )

    def confirm(self) -> None:
        """Mark the record confirmed and make it the active academic source.

        Confirmation means the student agrees Fork read their document
        correctly. It does not mean UNT was consulted, and nothing downstream
        may describe it that way.
        """
        if self.uploaded_record is None:
            raise ValueError("There is no uploaded record to confirm.")

        self.confirmation_status = ConfirmationStatus.CONFIRMED
        self.mode = AcademicInputMode.CONFIRMED_UPLOAD

        for provenance in self.uploaded_record.field_provenance.values():
            provenance.confirmed_by_student = True
        for course in self.uploaded_record.courses:
            course.provenance.confirmed_by_student = True

        self.touch()

    def switch_to_manual(self) -> None:
        """Return to manual entry, discarding the uploaded record.

        The clearing is the point. Leaving a confirmed record in place while
        manual values drive the calculation is how two sources end up competing
        without anyone noticing.
        """
        self.mode = AcademicInputMode.MANUAL
        self.uploaded_record = None
        self.confirmation_status = None
        self.degree_match_results = None
        self.touch()

    # --- documents ------------------------------------------------------

    def attach_what_if(self, document: "StoredDocument") -> None:
        """Hold a What-If pending review, replacing any previous one.

        Replacement clears the acknowledgement: permission was given for a
        document that is no longer part of the comparison.
        """
        self.what_if_document = document
        self.acknowledged_evidence = None
        self.touch()

    def remove_what_if(self) -> None:
        """Detach the What-If. Only ever called explicitly -- selecting a
        different option in the UI is view state and must not detach
        anything."""
        self.what_if_document = None
        self.acknowledged_evidence = None
        self.touch()

    def remember_manual_transferable(self, major: str, value: int) -> None:
        self.manual_transferable_by_major[major] = value
        self.touch()

    def acknowledge(self, evidence: str) -> bool:
        """Record that the student accepted a specific set of documents.

        The caller passes the fingerprint it displayed. A stale client
        acknowledging a screen that has since changed is refused rather than
        granted, which is the difference between consent and a leftover flag.
        """
        expected = self.current_evidence_fingerprint()
        if expected is None or evidence != expected:
            return False
        self.acknowledged_evidence = expected
        self.touch()
        return True

    @property
    def is_acknowledged(self) -> bool:
        expected = self.current_evidence_fingerprint()
        return expected is not None and self.acknowledged_evidence == expected

    def current_evidence_fingerprint(self) -> str | None:
        from documents.resolution import (
            classify_document,
            detect_discrepancies,
            evidence_fingerprint,
        )

        current = self.uploaded_record if self.has_confirmed_record else None
        what_if = (
            self.what_if_document.record
            if self.what_if_document and self.what_if_document.is_confirmed
            else None
        )
        if current is None and what_if is None:
            return None

        classification = (
            classify_document(what_if, self._majors) if what_if is not None else None
        )
        return evidence_fingerprint(
            current,
            0,
            what_if,
            self.what_if_document.correction_revision if self.what_if_document else 0,
            classification,
            detect_discrepancies(current, what_if),
        )

    #: Populated by the route from institution reference data. Held rather
    #: than imported so the session stays free of data-loading concerns.
    _majors: dict = {}

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)