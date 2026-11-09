"""Explicit native-agent registry, not an agent harness or plugin loader."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from .codex import Codex
from .controls import validate_settings


class Agent(Protocol):
    token: str
    conversation: str

    @property
    def usable(self) -> bool: ...
    async def start(self): ...
    async def turn(self, text: str): ...
    async def cancel(self): ...
    async def close(self): ...
    async def options(self) -> dict: ...
    async def probe(self) -> dict: ...
    async def decide(self, identifier, approved=None, answers=None, *, decision=None, scope="turn"): ...


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    factory: Callable[..., Agent]
    validate: Callable[[dict, dict], dict]
    executable: Callable[[], str | None]
    capabilities: tuple[str, ...]

    def describe(self):
        return {"id": self.id, "label": self.label,
                "installed": bool(self.executable()),
                "capabilities": list(self.capabilities)}


PROVIDERS = {
    "codex": Provider("codex", "Codex", Codex, validate_settings, Codex.executable,
                      ("model", "mode", "permissions", "resume", "stop")),
}


def provider(identifier: str | None) -> Provider:
    # Missing identity is accepted only for existing pre-migration records.
    identifier = identifier or "codex"
    try:
        return PROVIDERS[identifier]
    except KeyError:
        raise ValueError(f"Agent '{identifier}' is not supported by this Studio installation.") from None


def create_agent(store, conversation: str, url: str, *, metadata_only=False) -> Agent:
    value = store.require("conversation", conversation)
    return provider(value.get("provider")).factory(store, conversation, url, metadata_only=metadata_only)
