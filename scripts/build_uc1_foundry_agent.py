from __future__ import annotations

import argparse
import os
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a new Foundry Prompt Agent version for UC1 and print the resulting name/version."
    )
    parser.add_argument(
        "--project-endpoint",
        default=os.getenv("FOUNDRY_PROJECT_ENDPOINT"),
        help="Foundry project endpoint (env: FOUNDRY_PROJECT_ENDPOINT)",
    )
    parser.add_argument(
        "--agent-name",
        default=os.getenv("FOUNDRY_AGENT_NAME", "voicecall-uc1-judge"),
        help="Foundry agent name (env: FOUNDRY_AGENT_NAME)",
    )
    parser.add_argument(
        "--model",
        default=(
            os.getenv("FOUNDRY_MODEL_DEPLOYMENT_NAME")
            or os.getenv("AOAI_DEPLOYMENT")
            or "gpt-5.4"
        ),
        help="Foundry model deployment name (env: FOUNDRY_MODEL_DEPLOYMENT_NAME, AOAI_DEPLOYMENT)",
    )
    parser.add_argument(
        "--prompt-file",
        default=os.getenv("UC1_PROMPT_PATH", "assets/uc1_prompt.txt"),
        help="Prompt file path for UC1 instructions (env: UC1_PROMPT_PATH)",
    )
    parser.add_argument(
        "--description",
        default="VoiceCall Verify UC1 rubric judge",
        help="Agent version description",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="Prompt agent temperature",
    )
    return parser.parse_args()


def require_value(name: str, value: str | None) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise ValueError(f"Missing required value: {name}")
    return cleaned


def main() -> None:
    load_dotenv(override=False)
    args = parse_args()

    project_endpoint = require_value("project endpoint", args.project_endpoint)
    agent_name = require_value("agent name", args.agent_name)
    model_name = require_value("model deployment name", args.model)

    prompt_path = Path(args.prompt_file)
    if not prompt_path.exists() or not prompt_path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    instructions = prompt_path.read_text(encoding="utf-8").strip()
    if not instructions:
        raise ValueError(f"Prompt file is empty: {prompt_path}")

    client = AIProjectClient(
        endpoint=project_endpoint,
        credential=DefaultAzureCredential(),
    )

    definition = PromptAgentDefinition(
        model=model_name,
        instructions=instructions,
        temperature=args.temperature,
    )

    result = client.agents.create_version(
        agent_name,
        definition=definition,
        description=args.description,
    )

    print("Foundry UC1 agent version created")
    print(f"agent_name={result.name}")
    print(f"agent_version={result.version}")
    print(f"status={result.status}")
    print()
    print("Set these for UC1 runtime:")
    print(f"FOUNDRY_PROJECT_ENDPOINT={project_endpoint}")
    print(f"FOUNDRY_AGENT_NAME={result.name}")
    print(f"FOUNDRY_AGENT_VERSION={result.version}")


if __name__ == "__main__":
    main()
