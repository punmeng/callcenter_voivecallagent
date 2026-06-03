from __future__ import annotations

import asyncio
import json
from typing import Any

from .agent_runtime import build_azure_openai_agent, build_foundry_agent
from .config import Settings
from .models import JudgementItemResult, RubricItem, TokenUsage, Transcript


class QaJudge:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.agent = self._build_agent()
        self._semaphore = asyncio.Semaphore(settings.judge_concurrency)
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._total_tokens = 0
        self._request_count = 0

    def _build_agent(self):
        instructions = self._load_uc1_prompt()

        foundry_project_endpoint = (self.settings.foundry_project_endpoint or "").strip()
        foundry_agent_name = (self.settings.foundry_agent_name or "").strip()
        foundry_agent_version = (self.settings.foundry_agent_version or "").strip() or None
        foundry_model_deployment_name = (self.settings.foundry_model_deployment_name or "").strip()
        if foundry_project_endpoint and foundry_agent_name:
            return build_foundry_agent(
                name="VoiceCall UC1 Judge",
                project_endpoint=foundry_project_endpoint,
                instructions=instructions,
                agent_name=foundry_agent_name,
                agent_version=foundry_agent_version,
            )

        if foundry_project_endpoint and foundry_model_deployment_name:
            return build_foundry_agent(
                name="VoiceCall UC1 Judge",
                instructions=instructions,
                project_endpoint=foundry_project_endpoint,
                model=foundry_model_deployment_name,
            )

        if not self.settings.aoai_endpoint:
            raise ValueError("AOAI_ENDPOINT is required when Foundry project settings are not provided.")

        endpoint = self.settings.aoai_endpoint.strip().rstrip("/")
        return build_azure_openai_agent(
            name="VoiceCall UC1 Judge",
            instructions=instructions,
            model=self.settings.aoai_deployment,
            azure_endpoint=endpoint,
            api_version=self.settings.aoai_api_version,
            api_key=self.settings.aoai_api_key or None,
        )

    def _load_uc1_prompt(self) -> str:
        prompt_path = self.settings.uc1_prompt_path
        if prompt_path.exists() and prompt_path.is_file():
            return prompt_path.read_text(encoding="utf-8").strip()
        return ""

    def _build_user_prompt(self, mode: str, item: RubricItem, transcript_text: str) -> str:
        sections: list[str] = []
        if mode == "summary":
            sections.append(
                "Output contract override for this task: return JSON only with key 'summary'. "
                "summary must be Traditional Chinese and <= 20 characters."
            )
        else:
            sections.append(
                "Output contract override for this task: return JSON only with keys: verdict, reason, evidence_quote. "
                "Allowed verdict values: 符合, 不符合, N/A. "
                "If verdict is 符合 or N/A, reason should be empty string."
            )

        sections.append(f"Item ID: {item.id}")
        sections.append(f"Criteria: {item.criteria}")
        if item.exception:
            sections.append(f"Exception: {item.exception}")
        sections.append("Transcript:")
        sections.append(transcript_text)
        return "\n\n".join(section for section in sections if section)

    async def judge_items(self, transcript: Transcript, rubric_json: dict[str, Any]) -> list[JudgementItemResult]:
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._total_tokens = 0
        self._request_count = 0

        rubric_items = self._parse_rubric(rubric_json)
        tasks = [self._judge_one(item, transcript.full_text) for item in rubric_items]
        return await asyncio.gather(*tasks)

    def get_last_token_usage(self) -> TokenUsage:
        return TokenUsage(
            input_tokens=self._prompt_tokens,
            output_tokens=self._completion_tokens,
            total_tokens=self._total_tokens,
        )

    def get_last_request_count(self) -> int:
        return self._request_count

    @staticmethod
    def _coerce_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _extract_usage(self, payload: Any) -> tuple[int, int, int] | None:
        if not isinstance(payload, dict):
            return None

        input_tokens = 0
        output_tokens = 0
        total_tokens = 0

        input_keys = (
            "input_token_count",
            "input_tokens",
            "prompt_tokens",
            "inputTokenCount",
            "promptTokenCount",
        )
        output_keys = (
            "output_token_count",
            "output_tokens",
            "completion_tokens",
            "outputTokenCount",
            "completionTokenCount",
        )
        total_keys = (
            "total_token_count",
            "total_tokens",
            "totalTokenCount",
        )

        for key in input_keys:
            if key in payload:
                input_tokens = self._coerce_int(payload.get(key))
                break
        for key in output_keys:
            if key in payload:
                output_tokens = self._coerce_int(payload.get(key))
                break
        for key in total_keys:
            if key in payload:
                total_tokens = self._coerce_int(payload.get(key))
                break

        if total_tokens <= 0 and (input_tokens > 0 or output_tokens > 0):
            total_tokens = input_tokens + output_tokens

        if input_tokens <= 0 and output_tokens <= 0 and total_tokens <= 0:
            return None
        return input_tokens, output_tokens, total_tokens

    def _accumulate_usage(self, response: Any) -> None:
        candidate_dicts: list[dict[str, Any]] = []

        usage_details = getattr(response, "usage_details", None)
        if isinstance(usage_details, dict):
            candidate_dicts.append(usage_details)

        usage = getattr(response, "usage", None)
        if isinstance(usage, dict):
            candidate_dicts.append(usage)
        elif usage is not None:
            candidate_dicts.append(
                {
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(usage, "completion_tokens", 0),
                    "total_tokens": getattr(usage, "total_tokens", 0),
                }
            )

        metadata = getattr(response, "metadata", None)
        if isinstance(metadata, dict):
            for key in ("usage", "usage_details", "model_usage", "modelUsage", "token_usage", "tokenUsage"):
                nested = metadata.get(key)
                if isinstance(nested, dict):
                    candidate_dicts.append(nested)

        for payload in candidate_dicts:
            extracted = self._extract_usage(payload)
            if not extracted:
                continue
            input_tokens, output_tokens, total_tokens = extracted
            self._prompt_tokens += input_tokens
            self._completion_tokens += output_tokens
            self._total_tokens += total_tokens
            return

    def _parse_rubric(self, rubric_json: dict[str, Any]) -> list[RubricItem]:
        items: list[RubricItem] = []
        for row in rubric_json.get("items", []):
            item_id = str(row.get("id", "")).strip()
            item_type = str(row.get("type", "verdict")).strip() or "verdict"
            criteria = str(row.get("criteria", "")).strip()
            exception = row.get("exception")
            exception_text = str(exception).strip() if isinstance(exception, str) and exception.strip() else None
            if item_id and criteria:
                items.append(RubricItem(id=item_id, type=item_type, criteria=criteria, exception=exception_text))
        return items

    async def _judge_one(self, item: RubricItem, transcript_text: str) -> JudgementItemResult:
        async with self._semaphore:
            if item.type == "summary" or item.id in {"1", "2", "3"}:
                return await self._summarize_one(item, transcript_text)
            return await self._verdict_one(item, transcript_text)

    async def _summarize_one(self, item: RubricItem, transcript_text: str) -> JudgementItemResult:
        content = await self._chat_json("summary", item, transcript_text)
        summary = str(content.get("summary", "")).strip()
        if len(summary) > 20:
            summary = summary[:20]

        return JudgementItemResult(
            id=item.id,
            item_type="summary",
            verdict=None,
            reason=None,
            evidence_quote=None,
            summary=summary,
        )

    async def _verdict_one(self, item: RubricItem, transcript_text: str) -> JudgementItemResult:
        try:
            content = await self._chat_json("verdict", item, transcript_text)
            verdict = str(content.get("verdict", "")).strip()
            if verdict not in {"符合", "不符合", "N/A"}:
                verdict = "不符合"
            reason = str(content.get("reason", "")).strip()
            evidence = str(content.get("evidence_quote") or content.get("evidence") or "").strip()

            return JudgementItemResult(
                id=item.id,
                item_type="verdict",
                verdict=verdict,
                reason=reason,
                evidence_quote=evidence,
                summary=None,
            )
        except Exception as exc:
            return JudgementItemResult(
                id=item.id,
                item_type="verdict",
                verdict="判定錯誤",
                reason=f"Judge error: {exc}",
                evidence_quote=None,
                summary=None,
            )

    async def _chat_json(self, mode: str, item: RubricItem, transcript_text: str) -> dict[str, Any]:
        user_message = self._build_user_prompt(mode, item, transcript_text)
        response = await self.agent.run(user_message)

        self._request_count += 1
        self._accumulate_usage(response)

        text = getattr(response, "text", None)
        if not isinstance(text, str):
            text = str(response)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}