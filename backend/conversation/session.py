"""
Conversation state: who's being compared, what's being discussed, and
enough history to resolve a follow-up.

WHAT THIS STORES, and what it deliberately doesn't:

It stores deterministic metadata — the active option set, the current and
previous topic scope, which majors the last question referred to, how the
router classified the last question, and the text of the student's own
turns. All of that is either something Fork computed or something the
student typed.

It does NOT store anything the AI wrote. Not the explanations, not the
key points, not a summary of them. That's the rule that stops a
hallucination in turn one from becoming trusted evidence in turn two:
there's no field to put it in, so there's no code path that could read it
back. Every factual answer is regrounded against a fresh engine result and
the authorized view built from it.

STORAGE: an in-memory dict, process-local. Restarting the backend clears
every conversation. That's a deliberate choice for this version — the
alternative is a database and a migration story for state that's cheap to
rebuild by asking the student what they're comparing. If Fork ever runs
multiple workers, sessions will need to move somewhere shared, and this
module is the only place that would have to change.
"""

import time
import uuid
from dataclasses import dataclass, field

from decision_paths.change_major.comparison import MultiComparisonSnapshot
from decision_paths.change_major.comparison_inputs import MultiComparisonInputs

from .router import BROAD

# How long an untouched session sticks around. Long enough that a student
# can go read a course catalog and come back, short enough that a
# long-running process doesn't accumulate dead conversations forever.
SESSION_TTL_SECONDS = 6 * 60 * 60


@dataclass
class UserTurn:
    """The student's own words, plus what Fork resolved them to. No AI
    output here by design — see the module docstring."""

    text: str
    topic_scope: str
    question_intent: str
    referenced_options: list[str] = field(default_factory=list)


@dataclass
class PendingFieldRequest:
    """Set when Fork just asked a direct, deterministic question about one
    missing field on one option — e.g. "how many of your credits apply to
    Psychology B.S.?" — so the *next* turn can resolve a bare numeric
    reply ("61") without an AI round-trip. Cleared the moment it's
    answered or the student says something else instead. See
    orchestrator.py."""

    major: str
    field: str


@dataclass
class PendingOptionAction:
    """
    Set when an option-change instruction couldn't fully resolve --
    either the classifier itself asked for clarification (a "replace"
    with no target major named), or a resolved change failed validation
    (e.g. MAX_OPTIONS). Carries whatever WAS understood about the
    instruction, so a follow-up ("psychology bs", "can you replace it")
    can be interpreted in light of it instead of starting from nothing.

    This is validated, structured metadata Fork itself produced from the
    student's own words -- not AI prose, and not a fact the explanation
    layer could treat as evidence. It exists purely to keep the
    CONVERSATION coherent across a clarification, the same way
    last_referenced_options already does for topic follow-ups. See
    orchestrator.py's _apply_option_change and clarification handling.
    """

    action: str  # one of option_intent.py's ACTION_* constants
    remove_majors: list[str] = field(default_factory=list)
    add_majors: list[str] = field(default_factory=list)


@dataclass
class PendingAnalysisQuestion:
    """
    Set when a turn resolved a real, freshly-stated analytical topic (not
    "unchanged") but couldn't be answered THIS turn because a required
    field was missing -- e.g. "replace Psych BA with Psych BS, then tell
    me which is fastest" when Psych BS's transfer credits aren't known
    yet. Consulted once the blocking field is filled, so the student
    never has to repeat the question. `topic_scope` is a resolved,
    concrete scope (never "unchanged"/"unclear"); `original_message` is
    the student's own words, used to frame the resumed explanation call.

    Discarded immediately by any turn that doesn't resolve the pending
    field it's paired with -- see orchestrator.py's lifetime handling.
    """

    topic_scope: str
    original_message: str


@dataclass
class ConversationSession:
    session_id: str

    # Trusted inputs and the snapshot they produced. The snapshot is
    # regenerated whenever inputs change; it's a cache of engine output,
    # never of anything a model said.
    inputs: MultiComparisonInputs | None = None
    snapshot: MultiComparisonSnapshot | None = None
    # Which inputs the cached snapshot was built from. Compared against a
    # freshly computed fingerprint each turn so corrected inputs can't
    # leave a stale snapshot in place.
    snapshot_fingerprint: str | None = None
    institution_id: str = "unt"

    # WHO is being compared. Includes the anchor.
    active_options: list[str] = field(default_factory=list)

    # WHAT is being discussed. Strictly independent of active_options —
    # nothing in this class may update one as a side effect of the other.
    current_topic_scope: str = BROAD
    last_topic_scope: str | None = None
    last_referenced_options: list[str] = field(default_factory=list)
    last_question_intent: str | None = None

    # An explicitly stated priority (one of the topic-scope constants),
    # set only from a validated ConversationIntent.priority_update — never
    # inferred from a reaction like "CS looks nice". Survives topic and
    # option-set changes; cleared only by an explicit statement or a
    # session reset. See apply_priority_update().
    stated_priority: str | None = None

    # Set when Fork's last turn ended in a direct, deterministic ask for
    # one missing field on one option (see PendingFieldRequest). Consulted
    # by the orchestrator before running full intent classification on the
    # next message, so a bare numeric reply doesn't need an AI call.
    pending_field_request: PendingFieldRequest | None = None

    # Set when an option-change instruction (add/remove/replace) couldn't
    # fully resolve this turn (see PendingOptionAction). Passed to the
    # classifier as context on the next turn so a short follow-up gets
    # interpreted as completing THIS pending action, and so a repeated
    # clarification asks about the right thing instead of defaulting to
    # a generic "which major should I add?".
    pending_option_action: PendingOptionAction | None = None

    # Set alongside pending_field_request when the same turn that
    # triggered it also asked a real, freshly-stated analytical question
    # (see PendingAnalysisQuestion). Always set and cleared together with
    # pending_field_request -- they share one lifetime.
    pending_analysis_question: PendingAnalysisQuestion | None = None

    turns: list[UserTurn] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)

    # --- option state ----------------------------------------------------

    def all_known_options(self) -> list[str]:
        """Everyone the current inputs cover, anchor first. This is what
        "compare all of them again" restores to."""
        return self.inputs.all_majors() if self.inputs else list(self.active_options)

    def set_active_options(self, options: list[str]) -> None:
        """Only ever called from an explicit option-change instruction.
        Topic scope is untouched here, on purpose."""
        self.active_options = list(options)
        self.updated_at = time.time()

    # --- topic state -----------------------------------------------------

    def set_topic_scope(self, scope: str, intent: str) -> None:
        """Only ever called from the router. Active options are untouched
        here, on purpose."""
        if scope != self.current_topic_scope:
            self.last_topic_scope = self.current_topic_scope
        self.current_topic_scope = scope
        self.last_question_intent = intent
        self.updated_at = time.time()

    # --- priority ----------------------------------------------------------

    def apply_priority_update(self, priority_update: str | None) -> None:
        """Only ever called with a validated ConversationIntent.priority_update.
        None means "no statement this turn" and leaves stated_priority
        untouched — most turns don't restate a priority, and silence must
        never read as retraction. "cleared" is the one explicit removal
        path; anything else overwrites the prior value outright, since
        only one priority is stored at a time (see the schema's
        conflicting_priority clarification for the case where a single
        message states two at once — nothing is committed there)."""
        if priority_update is None:
            return
        self.stated_priority = None if priority_update == "cleared" else priority_update
        self.updated_at = time.time()

    # --- inputs (Compare Multiple only) -------------------------------------

    def set_inputs(self, inputs: MultiComparisonInputs) -> None:
        """Replace the session's comparison inputs mid-conversation — used
        when a chat instruction adds a genuinely new option or fills in a
        previously-missing transfer figure. Deliberately just an
        assignment: the next ensure_snapshot() call detects the changed
        inputs_fingerprint() and rebuilds automatically, so there's
        nothing else to invalidate here."""
        self.inputs = inputs
        self.updated_at = time.time()

    # --- turns -----------------------------------------------------------

    def record_turn(
        self,
        text: str,
        topic_scope: str,
        question_intent: str,
        referenced_options: list[str],
    ) -> None:
        self.turns.append(
            UserTurn(
                text=text,
                topic_scope=topic_scope,
                question_intent=question_intent,
                referenced_options=list(referenced_options),
            )
        )
        self.last_referenced_options = list(referenced_options)
        self.updated_at = time.time()

    def recent_questions(self, limit: int = 4) -> list[str]:
        """The student's last few questions, for resolving what a vague
        follow-up refers to. Their words only."""
        return [t.text for t in self.turns[-limit:]]

    # --- snapshot freshness ----------------------------------------------

    def inputs_fingerprint(self) -> str | None:
        """Identifies which set of inputs the cached snapshot belongs to.
        Same idea as the frontend's buildDecisionFingerprint: if the
        student corrects their credit count mid-conversation, the cached
        snapshot describes a decision that no longer exists and has to be
        rebuilt rather than quietly reused."""
        if self.inputs is None:
            return None
        parts = [
            self.inputs.current_major,
            str(self.inputs.credits_completed),
            self.institution_id,
        ]
        for option in sorted(self.inputs.options, key=lambda o: o.major):
            parts.append(
                f"{option.major}:{option.credits_transferable}:"
                f"{option.prospective_credits_required}"
            )
        return "|".join(parts)

    def to_state_dict(self) -> dict:
        """The conversational state the API hands back, so a client (and
        later, a UI control) can render what's currently being compared."""
        return {
            "session_id": self.session_id,
            "active_options": list(self.active_options),
            "current_topic_scope": self.current_topic_scope,
            "last_topic_scope": self.last_topic_scope,
            "last_question_intent": self.last_question_intent,
            "last_referenced_options": list(self.last_referenced_options),
            "stated_priority": self.stated_priority,
            "turn_count": len(self.turns),
        }


class SessionStore:
    """
    Process-local session storage.

    Deliberately not a database. See the module docstring for the
    reasoning and the limitation that comes with it.
    """

    def __init__(self, ttl_seconds: int = SESSION_TTL_SECONDS):
        self._sessions: dict[str, ConversationSession] = {}
        self._ttl = ttl_seconds

    def create(self, institution_id: str = "unt") -> ConversationSession:
        session_id = uuid.uuid4().hex
        session = ConversationSession(
            session_id=session_id, institution_id=institution_id
        )
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> ConversationSession | None:
        self._expire()
        return self._sessions.get(session_id)

    def get_or_create(
        self, session_id: str | None, institution_id: str = "unt"
    ) -> ConversationSession:
        """A missing or expired session id produces a fresh session rather
        than an error. Losing conversational context is annoying; a hard
        failure mid-conversation because a server restarted is worse."""
        if session_id:
            existing = self.get(session_id)
            if existing is not None:
                return existing
        return self.create(institution_id)

    def _expire(self) -> None:
        cutoff = time.time() - self._ttl
        dead = [sid for sid, s in self._sessions.items() if s.updated_at < cutoff]
        for sid in dead:
            del self._sessions[sid]

    def __len__(self) -> int:
        return len(self._sessions)


# One store per process. Imported directly rather than injected, because
# there's exactly one and pretending otherwise would add indirection
# without adding a seam anyone needs.
SESSIONS = SessionStore()
