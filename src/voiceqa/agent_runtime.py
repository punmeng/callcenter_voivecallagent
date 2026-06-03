from __future__ import annotations

from dataclasses import dataclass

from agent_framework import Agent
from agent_framework.foundry import FoundryAgent, FoundryChatClient
from agent_framework.openai import OpenAIChatClient
from azure.identity import DefaultAzureCredential


@dataclass(frozen=True)
class AgentRuntimeConfig:
    name: str
    instructions: str


def build_azure_openai_agent(
    *,
    name: str,
    instructions: str,
    model: str,
    azure_endpoint: str,
    api_version: str | None,
    api_key: str | None = None,
) -> Agent:
    is_v1_endpoint = azure_endpoint.rstrip("/").endswith("/openai/v1")
    client_kwargs: dict[str, str | None] = {
        "model": model,
    }
    if is_v1_endpoint:
        client_kwargs["base_url"] = azure_endpoint
    else:
        client_kwargs["azure_endpoint"] = azure_endpoint
        if api_version:
            client_kwargs["api_version"] = api_version
    if api_key:
        client_kwargs["api_key"] = api_key
    else:
        client_kwargs["credential"] = DefaultAzureCredential()

    client = OpenAIChatClient(**client_kwargs)
    return client.as_agent(name=name, instructions=instructions)


def build_foundry_agent(
    *,
    name: str,
    instructions: str,
    project_endpoint: str,
    model: str | None = None,
    agent_name: str | None = None,
    agent_version: str | None = None,
) -> Agent:
    if agent_name:
        return FoundryAgent(
            project_endpoint=project_endpoint,
            agent_name=agent_name,
            agent_version=agent_version,
            credential=DefaultAzureCredential(),
            name=name,
            instructions=instructions,
            default_options={"store": False},
        )

    if not model:
        raise ValueError("A Foundry model deployment name is required when no portal agent name is configured.")

    client = FoundryChatClient(
        project_endpoint=project_endpoint,
        model=model,
        credential=DefaultAzureCredential(),
    )
    return Agent(
        client=client,
        name=name,
        instructions=instructions,
        default_options={"store": False},
    )