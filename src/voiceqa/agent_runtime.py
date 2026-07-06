from __future__ import annotations

from agent_framework import Agent
from agent_framework.foundry import FoundryAgent, FoundryChatClient
from agent_framework.openai import OpenAIChatClient
from azure.identity import DefaultAzureCredential


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
    allow_preview: bool = False,
    use_portal_instructions: bool = False,
) -> Agent:
    if agent_name:
        # allow_preview=True routes through get_openai_client(agent_name=...), which
        # runs the portal agent WITH its server-side tools (e.g. File search /
        # knowledge). The non-preview path strips tools, so attached knowledge is
        # ignored — set allow_preview=True for agents that rely on knowledge.
        #
        # use_portal_instructions=True omits our local instructions so the portal
        # agent's OWN published instructions drive (e.g. edits made in the portal
        # like "return NTD 1799 by default"). Otherwise our instructions override them.
        agent_kwargs: dict[str, object] = {
            "project_endpoint": project_endpoint,
            "agent_name": agent_name,
            "agent_version": agent_version,
            "credential": DefaultAzureCredential(),
            "name": name,
            "default_options": {"store": False},
            "allow_preview": allow_preview,
        }
        if not use_portal_instructions:
            agent_kwargs["instructions"] = instructions
        return FoundryAgent(**agent_kwargs)

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