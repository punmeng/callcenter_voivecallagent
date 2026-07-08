from __future__ import annotations

import json
import re
from pathlib import Path


class CorrectionEngine:
    def __init__(self, corrections: dict[str, list[str]]) -> None:
        # Sort variants longest-first so a broader mishearing (e.g. "哈維亞比較")
        # is replaced before a shorter prefix of it ("哈維亞比"), which otherwise
        # leaves trailing garbage (e.g. "...較").
        pairs: list[tuple[str, str]] = [
            (variant, canonical)
            for canonical, variants in corrections.items()
            for variant in variants
        ]
        pairs.sort(key=lambda pair: len(pair[0]), reverse=True)
        self._rules: list[tuple[re.Pattern[str], str]] = [
            (re.compile(re.escape(variant), flags=re.IGNORECASE), canonical)
            for variant, canonical in pairs
        ]

    @classmethod
    def from_file(cls, path: Path) -> "CorrectionEngine":
        if not path.exists():
            return cls({})

        content = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(content, dict):
            return cls({})

        normalized: dict[str, list[str]] = {}
        for canonical, variants in content.items():
            if not isinstance(canonical, str) or not isinstance(variants, list):
                continue
            normalized[canonical] = [str(v) for v in variants if isinstance(v, str)]

        return cls(normalized)

    def apply(self, text: str) -> str:
        corrected = text
        for pattern, canonical in self._rules:
            corrected = pattern.sub(canonical, corrected)
        return corrected
