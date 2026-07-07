from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class Settings:
    input_source: str
    blob_account_url: str
    blob_container_in: str
    blob_container_out: str
    blob_connection_string: str | None
    input_blob_name: str | None
    input_prefix: str | None
    local_audio_path: Path | None
    local_audio_dir: Path | None
    rubric_blob_path: str
    rubric_local_path: Path | None
    output_dir: Path
    output_to_blob: bool
    include_transcript: bool
    judge_concurrency: int

    speech_key: str | None
    speech_region: str | None
    speech_endpoint: str | None
    speech_custom_endpoint_id: str | None
    speech_languages: list[str]
    phrase_list_path: Path
    corrections_path: Path

    aoai_api_key: str
    aoai_endpoint: str
    aoai_deployment: str
    aoai_api_version: str
    aoai_use_entra_id: bool
    aoai_scope: str
    foundry_project_endpoint: str | None
    foundry_agent_name: str | None
    foundry_agent_version: str | None
    foundry_model_deployment_name: str | None
    uc1_prompt_path: Path



def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return None



def load_settings() -> Settings:
    load_dotenv(override=False)

    # Accept both repo-native and Azure-prefixed env names.
    speech_languages_raw = _first_env("SPEECH_LANGUAGES", "AZURE_SPEECH_LOCALE") or "zh-TW,en-US"
    speech_languages = [token.strip() for token in speech_languages_raw.split(",") if token.strip()]

    return Settings(
        input_source=os.getenv("INPUT_SOURCE", "blob").strip().lower(),
        blob_account_url=os.getenv("BLOB_ACCOUNT_URL", ""),
        blob_container_in=os.getenv("BLOB_CONTAINER_IN", "calls"),
        blob_container_out=os.getenv("BLOB_CONTAINER_OUT", "reports"),
        blob_connection_string=os.getenv("BLOB_CONNECTION_STRING") or None,
        input_blob_name=os.getenv("INPUT_BLOB_NAME") or None,
        input_prefix=os.getenv("INPUT_PREFIX") or None,
        local_audio_path=Path(os.getenv("LOCAL_AUDIO_PATH")) if os.getenv("LOCAL_AUDIO_PATH") else None,
        local_audio_dir=Path(os.getenv("LOCAL_AUDIO_DIR")) if os.getenv("LOCAL_AUDIO_DIR") else None,
        rubric_blob_path=os.getenv("RUBRIC_BLOB_PATH", "rubric/rubric.json"),
        rubric_local_path=Path(os.getenv("RUBRIC_LOCAL_PATH")) if os.getenv("RUBRIC_LOCAL_PATH") else None,
        output_dir=Path(os.getenv("OUTPUT_DIR", "reports/quality_checks")),
        output_to_blob=_bool_env("OUTPUT_TO_BLOB", True),
        include_transcript=_bool_env("INCLUDE_TRANSCRIPT", True),
        judge_concurrency=int(os.getenv("JUDGE_CONCURRENCY", "4")),
        speech_key=_first_env("SPEECH_KEY", "AZURE_SPEECH_KEY"),
        speech_region=_first_env("SPEECH_REGION", "AZURE_SPEECH_REGION"),
        speech_endpoint=_first_env("SPEECH_ENDPOINT", "AZURE_SPEECH_ENDPOINT"),
        speech_custom_endpoint_id=os.getenv("SPEECH_CUSTOM_ENDPOINT_ID") or None,
        speech_languages=speech_languages,
        phrase_list_path=Path(os.getenv("PHRASE_LIST_PATH", "assets/phrase_list.txt")),
        corrections_path=Path(os.getenv("CORRECTIONS_PATH", "assets/corrections.json")),
        aoai_api_key=os.getenv("AOAI_API_KEY", ""),
        aoai_endpoint=os.getenv("AOAI_ENDPOINT", ""),
        aoai_deployment=os.getenv("AOAI_DEPLOYMENT", "gpt-4.1-mini"),
        aoai_api_version=os.getenv("AOAI_API_VERSION", "2024-10-21"),
        aoai_use_entra_id=_bool_env("AOAI_USE_ENTRA_ID", False),
        aoai_scope=os.getenv("AOAI_SCOPE", "https://cognitiveservices.azure.com/.default"),
        foundry_project_endpoint=os.getenv("FOUNDRY_PROJECT_ENDPOINT") or os.getenv("UC1_FOUNDRY_PROJECT_ENDPOINT") or None,
        # Prefer UC1-specific names so a shared FOUNDRY_AGENT_NAME set by another
        # use case's launch script (e.g. start_uc3.ps1) can't hijack UC1's judge agent.
        foundry_agent_name=os.getenv("UC1_FOUNDRY_AGENT_NAME") or os.getenv("FOUNDRY_AGENT_NAME") or None,
        foundry_agent_version=os.getenv("UC1_FOUNDRY_AGENT_VERSION") or os.getenv("FOUNDRY_AGENT_VERSION") or None,
        foundry_model_deployment_name=os.getenv("FOUNDRY_MODEL_DEPLOYMENT_NAME")
        or os.getenv("UC1_FOUNDRY_MODEL_DEPLOYMENT_NAME")
        or None,
        uc1_prompt_path=Path(os.getenv("UC1_PROMPT_PATH", "assets/uc1_prompt.txt")),
    )
