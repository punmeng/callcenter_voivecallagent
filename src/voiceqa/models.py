from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class TranscriptTurn:
    speaker: str
    offset_seconds: float
    duration_seconds: float
    text: str


@dataclass
class Transcript:
    turns: list[TranscriptTurn] = field(default_factory=list)
    duration_seconds: float = 0.0
    nbest_samples: list[dict[str, Any]] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n".join(turn.text for turn in self.turns if turn.text.strip())


@dataclass
class RubricItem:
    id: str
    type: str
    criteria: str
    exception: str | None = None


@dataclass
class JudgementItemResult:
    id: str
    item_type: str
    verdict: str | None
    reason: str | None
    evidence_quote: str | None
    summary: str | None


@dataclass
class CallMetadata:
    call_id: str
    blob_name: str
    processed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass
class CallMetrics:
    stt_incoming_call_length_seconds: float = 0.0
    llm_requests: int = 0
    token_usage: TokenUsage = field(default_factory=TokenUsage)


@dataclass
class CallReport:
    metadata: CallMetadata
    transcript: Transcript | None
    item_results: list[JudgementItemResult]
    stt_status: str = "OK"
    metrics: CallMetrics = field(default_factory=CallMetrics)
