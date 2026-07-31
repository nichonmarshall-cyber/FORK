"""
Resolves a caller-supplied major key before it reaches the majors table.

This exists because a raw KeyError/"unknown major" from the engine can't
explain WHY a key doesn't work, and three different situations need three
different explanations:

  1. A key that used to exist and was renamed to match UNT's actual current
     program name (e.g. "mechanical_engineering" -> UNT's real program is
     "Mechanical & Energy Engineering"). Old callers keep working; they
     just get a warning telling them to update.
  2. A key that's ambiguous because UNT offers more than one real program
     under that name, and they're genuinely different degrees with
     different requirements — not two labels for the same thing (e.g.
     Psychology: B.A. and B.S. are separate majors at UNT). Silently
     picking one would be a silent wrong answer, so this asks instead.
  3. A key for a real UNT program that this data model doesn't represent
     yet, because its structure doesn't fit what every other major here
     assumes (a single from-scratch degree completed at one institution
     under one tuition model). UNT's Traditional BSN is the current
     example: it's a 60-hour prerequisite phase plus a 60-hour
     nursing-program phase administered through UNT Health, a separate
     institution within the UNT System with its own tuition model and a
     separate admissions process. It's excluded because of that
     structural mismatch, not because 120 hours is somehow an unusual
     total — a 60+60 split is a perfectly normal degree length.

This module only handles those three cases. It does not check a key
against the real majors table — the engine still does that, and still
raises its own error for a key that's simply wrong.
"""

from dataclasses import dataclass

# Old key -> current key. The request still succeeds; the response carries
# a warning noting the rename.
LEGACY_MAJOR_ALIASES: dict[str, str] = {
    "mechanical_engineering": "mechanical_energy_engineering",
}

# Old/generic key -> the current keys that could have been meant.
AMBIGUOUS_MAJORS: dict[str, list[str]] = {
    "psychology": ["psychology_ba", "psychology_bs"],
}

# Key -> why this data model doesn't support it (yet).
UNSUPPORTED_MAJORS: dict[str, str] = {
    "nursing": (
        "UNT's Traditional BSN is administered through UNT Health, a "
        "separate institution within the UNT System with its own tuition "
        "model and admissions process. The program consists of a 60-hour "
        "prerequisite phase (often completed elsewhere) plus a 60-hour "
        "nursing-program phase — a normal 120-hour total, but split across "
        "two institutions rather than completed as one continuous degree "
        "at UNT Denton. It's excluded from this Decision Path because of "
        "that structural difference, not because of its length or "
        "credit-hour total."
    ),
}


class AmbiguousMajorError(ValueError):
    """A major key could refer to more than one real, distinct UNT program.
    Carries the field name and the specific keys to choose between."""

    def __init__(self, field: str, key: str, options: list[str]):
        self.field = field
        self.key = key
        self.options = options
        super().__init__(
            f"'{key}' is ambiguous for {field}: UNT offers this as more "
            f"than one program. Choose one of {options}."
        )


class UnsupportedMajorError(ValueError):
    """A real UNT program this data model doesn't represent yet."""

    def __init__(self, field: str, key: str, explanation: str):
        self.field = field
        self.key = key
        self.explanation = explanation
        super().__init__(f"'{key}' is not supported for {field}: {explanation}")


@dataclass
class ResolvedMajor:
    key: str
    warning: str | None = None


def resolve_major(field: str, key: str) -> ResolvedMajor:
    """
    Resolves one major key. Outcomes:
      - Ambiguous key       -> raises AmbiguousMajorError.
      - Unsupported key     -> raises UnsupportedMajorError.
      - Legacy alias        -> returns the current key plus a warning.
      - Anything else       -> returned unchanged, no warning. This
        includes keys that don't exist at all — that's the engine's error
        to raise, once it looks the key up in the real majors table.
    """
    if key in AMBIGUOUS_MAJORS:
        raise AmbiguousMajorError(field, key, AMBIGUOUS_MAJORS[key])
    if key in UNSUPPORTED_MAJORS:
        raise UnsupportedMajorError(field, key, UNSUPPORTED_MAJORS[key])
    if key in LEGACY_MAJOR_ALIASES:
        new_key = LEGACY_MAJOR_ALIASES[key]
        return ResolvedMajor(
            key=new_key,
            warning=(
                f"'{key}' has been renamed to '{new_key}' to match UNT's "
                "current program name. This request was still processed "
                "using the new key — update the caller when convenient."
            ),
        )
    return ResolvedMajor(key=key)
