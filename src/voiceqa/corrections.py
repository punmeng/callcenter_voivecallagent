from __future__ import annotations

import json
import re
from pathlib import Path


class CorrectionEngine:
    def __init__(self, corrections: dict[str, list[str]]) -> None:
        self._rules: list[tuple[re.Pattern[str], str]] = []
        for canonical, variants in corrections.items():
            for variant in variants:
                pattern = re.compile(re.escape(variant), flags=re.IGNORECASE)
                self._rules.append((pattern, canonical))

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
