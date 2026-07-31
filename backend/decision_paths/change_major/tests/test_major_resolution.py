import pytest

from ..major_resolution import (
    AmbiguousMajorError,
    UnsupportedMajorError,
    resolve_major,
)


def test_unrelated_key_passes_through_unchanged():
    resolved = resolve_major("current_major", "computer_science")
    assert resolved.key == "computer_science"
    assert resolved.warning is None


def test_legacy_mechanical_engineering_alias_maps_to_current_key():
    resolved = resolve_major("prospective_major", "mechanical_engineering")
    assert resolved.key == "mechanical_energy_engineering"
    assert resolved.warning is not None
    assert "renamed" in resolved.warning


def test_generic_psychology_raises_ambiguous_with_both_options():
    with pytest.raises(AmbiguousMajorError) as exc:
        resolve_major("current_major", "psychology")
    assert exc.value.field == "current_major"
    assert exc.value.options == ["psychology_ba", "psychology_bs"]


def test_specific_psychology_variants_pass_through_unchanged():
    """Once a caller has picked a specific variant, it should not be
    treated as ambiguous again."""
    for key in ("psychology_ba", "psychology_bs"):
        resolved = resolve_major("prospective_major", key)
        assert resolved.key == key
        assert resolved.warning is None


def test_nursing_raises_unsupported_with_explanation():
    with pytest.raises(UnsupportedMajorError) as exc:
        resolve_major("prospective_major", "nursing")
    assert exc.value.field == "prospective_major"
    assert "UNT Health" in exc.value.explanation
    # The reason given must be the structural/institutional one, not a
    # claim that the program is somehow too short or unusual in length.
    assert "60" in exc.value.explanation
