"""Safety data models."""

from __future__ import annotations

from dataclasses import dataclass, field


class GuardrailViolation(Exception):
    """Raised when a safety guardrail blocks a request."""

    def __init__(self, reason: str, violation_type: str = "unknown") -> None:
        super().__init__(reason)
        self.reason = reason
        self.violation_type = violation_type


@dataclass
class SafetyResult:
    sanitised_query: str
    pii_redacted: bool = False
    redacted_entities: list[str] = field(default_factory=list)
    injection_detected: bool = False
    content_class: str = "benign"
    passed: bool = True


@dataclass
class OutputGuardResult:
    answer: str
    faithfulness_score: float = 1.0
    toxicity_scores: dict[str, float] = field(default_factory=dict)
    disclaimer_added: bool = False
    blocked: bool = False
