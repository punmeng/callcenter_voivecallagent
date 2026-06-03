from __future__ import annotations

import json
from pathlib import Path

from .config import Settings
from .models import CallReport, JudgementItemResult


class MarkdownWriter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def render_report(self, report: CallReport) -> str:
        item_results = report.item_results
        summary_items = [row for row in item_results if row.item_type == "summary"]
        verdict_items = [row for row in item_results if row.item_type == "verdict"]

        pass_count = sum(1 for row in verdict_items if row.verdict == "符合")
        fail_count = sum(1 for row in verdict_items if row.verdict == "不符合")

        duration = 0.0
        if report.transcript:
            duration = report.transcript.duration_seconds

        lines: list[str] = []
        lines.append(f"# 語音質檢報告 — {report.metadata.call_id}")
        lines.append("")
        lines.append("| 欄位 | 值 |")
        lines.append("|---|---|")
        lines.append(f"| 音檔 | {report.metadata.blob_name} |")
        lines.append(f"| 時長 | {duration:.2f}s |")
        lines.append(f"| 處理時間 | {report.metadata.processed_at.isoformat()} |")
        lines.append(f"| STT 來電長度 | {report.metrics.stt_incoming_call_length_seconds:.2f}s |")
        lines.append(
            "| LLM Token 用量 (Input / Output / Total) | "
            f"{report.metrics.token_usage.input_tokens} / "
            f"{report.metrics.token_usage.output_tokens} / "
            f"{report.metrics.token_usage.total_tokens} |"
        )
        lines.append(f"| LLM 呼叫次數 | {report.metrics.llm_requests} |")

        if report.stt_status != "OK":
            lines.append(f"| 判定結果 | STT_FAILED ({report.stt_status}) |")
        else:
            lines.append(f"| 判定結果 | 符合 {pass_count} / 不符合 {fail_count} |")

        lines.append("")
        lines.append("## 摘要（項目 1–3）")
        for item in summary_items:
            lines.append(f"- **項目 {item.id}：** {item.summary or ''}")

        lines.append("")
        lines.append("## 評分明細")
        lines.append("| 項目 | 判定 | 原因 | 佐證 |")
        lines.append("|---|---|---|---|")
        for item in verdict_items:
            lines.append(self._render_verdict_row(item))

        if self.settings.include_transcript:
            lines.append("")
            lines.append("## 逐字稿")
            if report.transcript and report.transcript.turns:
                for turn in report.transcript.turns:
                    lines.append(f"> [{turn.offset_seconds:06.2f}] {turn.speaker}：{turn.text}")
            else:
                lines.append("> (empty transcript)")

        return "\n".join(lines) + "\n"

    def write_local(self, call_id: str, markdown_content: str) -> Path:
        self.settings.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.settings.output_dir / f"{call_id}.md"
        output_path.write_text(markdown_content, encoding="utf-8")
        return output_path

    def write_scoring_details_json(self, report: CallReport) -> Path:
        self.settings.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.settings.output_dir / f"{report.metadata.call_id}.scoring.json"

        summary_items = [
            {
                "id": item.id,
                "summary": item.summary or "",
            }
            for item in report.item_results
            if item.item_type == "summary"
        ]
        scoring_details = [
            {
                "id": item.id,
                "verdict": item.verdict,
                "reason": item.reason,
                "evidence_quote": item.evidence_quote,
            }
            for item in report.item_results
            if item.item_type == "verdict"
        ]

        payload = {
            "call_id": report.metadata.call_id,
            "audio": report.metadata.blob_name,
            "processed_at": report.metadata.processed_at.isoformat(),
            "stt_status": report.stt_status,
            "metrics": {
                "stt_incoming_call_length_seconds": report.metrics.stt_incoming_call_length_seconds,
                "llm_requests": report.metrics.llm_requests,
                "token_usage": {
                    "input_tokens": report.metrics.token_usage.input_tokens,
                    "output_tokens": report.metrics.token_usage.output_tokens,
                    "total_tokens": report.metrics.token_usage.total_tokens,
                },
            },
            "summary": summary_items,
            "scoring_details": scoring_details,
        }
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return output_path

    def write_call_metrics_json(self, report: CallReport) -> Path:
        self.settings.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.settings.output_dir / f"{report.metadata.call_id}.metrics.json"

        payload = {
            "call_id": report.metadata.call_id,
            "audio": report.metadata.blob_name,
            "processed_at": report.metadata.processed_at.isoformat(),
            "stt_status": report.stt_status,
            "stt_incoming_call_length_seconds": report.metrics.stt_incoming_call_length_seconds,
            "llm_requests": report.metrics.llm_requests,
            "token_usage": {
                "input_tokens": report.metrics.token_usage.input_tokens,
                "output_tokens": report.metrics.token_usage.output_tokens,
                "total_tokens": report.metrics.token_usage.total_tokens,
            },
        }
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return output_path

    def write_scoring_rules_json(self, rubric_json: dict) -> Path:
        self.settings.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.settings.output_dir / "scoring_rules.json"

        items = rubric_json.get("items", []) if isinstance(rubric_json, dict) else []
        scoring_rules: list[dict[str, str | None]] = []
        for row in items:
            if not isinstance(row, dict):
                continue
            if str(row.get("type", "")).strip() != "verdict":
                continue

            rule_id = str(row.get("id", "")).strip()
            criteria = str(row.get("criteria", "")).strip()
            exception_raw = row.get("exception")
            exception = str(exception_raw).strip() if isinstance(exception_raw, str) and exception_raw.strip() else None
            if not rule_id:
                continue

            scoring_rules.append(
                {
                    "id": rule_id,
                    "criteria": criteria,
                    "exception": exception,
                }
            )

        payload = {
            "name": "評分明細規則",
            "version": 1,
            "scoring_rules": scoring_rules,
        }
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return output_path

    def render_index(self, reports: list[tuple[str, Path]]) -> str:
        lines = ["# QA Reports Index", "", "| Call ID | Local Path |", "|---|---|"]
        for call_id, path in reports:
            lines.append(f"| {call_id} | [{path.name}]({path.name}) |")
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _render_verdict_row(item: JudgementItemResult) -> str:
        verdict = item.verdict or ""
        if verdict == "符合":
            display_verdict = "✅ 符合"
        elif verdict == "不符合":
            display_verdict = "❌ 不符合"
        else:
            display_verdict = f"⚠️ {verdict}" if verdict else ""

        reason = (item.reason or "").replace("|", "\\|")
        evidence = (item.evidence_quote or "").replace("|", "\\|")
        return f"| {item.id} | {display_verdict} | {reason} | {evidence} |"