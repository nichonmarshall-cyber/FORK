"""Registry metadata for the Change Major Decision Path. The API layer
discovers available Decision Paths through objects like this one rather
than hardcoding routes — adding a new Decision Path means adding a new
metadata.py, not editing this one."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DecisionPathMetadata:
    id: str
    display_name: str
    description: str
    version: str
    data_sources: list[str]


CHANGE_MAJOR_METADATA = DecisionPathMetadata(
    id="change_major",
    display_name="Change My Major",
    description=(
        "Projects the credit, cost, and earnings impact of switching from "
        "your current major to a prospective one."
    ),
    version="0.1.0",
    data_sources=[
        "University tuition and fee schedule",
        "U.S. Department of Education College Scorecard (planned; static "
        "reference table in v1)",
    ],
)