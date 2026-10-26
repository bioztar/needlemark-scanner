"""Immutable data model shared by every AEMS module."""
from __future__ import annotations

from dataclasses import dataclass, field

MODEL_ID = "aems-0.1"
MODEL_VERSION = MODEL_ID

DIM_NAMES = {
    1: "Context & instructions",
    2: "Harness: guides",
    3: "Harness: sensors",
    4: "Orchestration topology",
    5: "Autonomy & review line",
    6: "Verification & evals",
    7: "Memory & learning loops",
    8: "Governance, security & cost",
    9: "Measurement",
}

LEVEL_NAMES = {
    0: "Ad hoc",
    1: "Assisted",
    2: "Delegated",
    3: "Harnessed",
    4: "Orchestrated",
    5: "Self-improving",
}

ASSESSED_DIMS = (1, 2, 3, 5, 8, 9)
UNASSESSED_DIMS = (4, 6, 7)
CAP_LEVEL = 2
CAP_LABEL = "presence, not maturity"


@dataclass(frozen=True)
class Evidence:
    """One auditable fact: what was seen, and where/how it was seen."""

    label: str
    value: str
    source: str  # file path, glob, or command that produced the value


@dataclass(frozen=True)
class Check:
    """A single evidence requirement for reaching a level."""

    level: int
    label: str
    passed: bool
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class OutcomeCheck:
    """Outcome evidence required to hold a level >= 3 (outcome cap, see README)."""

    passed: bool
    label: str
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class DimScore:
    dim: int
    raw_level: int
    level: int
    capped: bool
    checks: tuple[Check, ...]
    outcome: OutcomeCheck | None
    assessed: bool = True
    hints: tuple[Evidence, ...] = ()

    @property
    def name(self) -> str:
        return DIM_NAMES[self.dim]

    @property
    def label(self) -> str:
        if not self.assessed:
            return "not assessed (needs T2 logs)"
        return CAP_LABEL if self.capped else LEVEL_NAMES[self.level]


@dataclass(frozen=True)
class Commit:
    sha: str
    parents: tuple[str, ...]
    ts: int  # author timestamp, epoch seconds
    subject: str  # used for intent classification only, never rendered
    files: tuple[tuple[str, int, int], ...]  # (path, added, deleted)
    agents: tuple[str, ...]  # agent labels attributed to this commit
    on_first_parent: bool = True
    squash_pr: bool = False
    other_bot: bool = False  # bot author that is not a known coding agent (e.g. dependabot)
    # Opaque, in-memory only: short salted hash of a PERSON author's email, None for bot/agent
    # authors. Used solely to count distinct people for k-anonymity; never rendered or exported.
    author_key: str | None = field(default=None, repr=False, compare=False)
    # Vendor label from the client-local vendors file (query pack only); None = not a vendor.
    vendor: str | None = field(default=None, compare=False)

    @property
    def identity_class(self) -> str:
        """Aggregated identity: an agent label, 'other bot' or 'human'. Never a person."""
        if self.agents:
            return self.agents[0] if len(self.agents) == 1 else "multiple agents"
        return "other bot" if self.other_bot else "human"

    @property
    def is_agent(self) -> bool:
        return bool(self.agents)

    @property
    def is_merge(self) -> bool:
        return len(self.parents) > 1

    @property
    def lines(self) -> int:
        return sum(a + d for _, a, d in self.files)

    @property
    def paths(self) -> frozenset[str]:
        return frozenset(p for p, _, _ in self.files)


@dataclass(frozen=True)
class Recommendation:
    rule_id: str
    dim: int
    move: str
    rationale: str
    source: str
    expected_effect: str
    not_yet: str
    confidence: str
    review_by: str


@dataclass(frozen=True)
class Report:
    repo: str
    scanned_at: str
    model_version: str
    tiers: tuple[str, ...]
    dims: tuple[DimScore, ...]
    overall: int
    median: float
    weakest: tuple[int, ...]
    metrics: dict = field(default_factory=dict)
    recommendations: tuple[Recommendation, ...] = ()
    notes: tuple[str, ...] = ()
