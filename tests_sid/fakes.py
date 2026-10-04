"""Offline stand-ins for chat models: no network, scripted answers, provider-style usage."""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from sid_trading_firm.config import load_settings

SONNET_USAGE = {"input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200}


class FakeChatModel(BaseChatModel):
    """Answers ``reply`` and reports ``usage`` the way LangChain providers do."""

    provider: str = "anthropic"
    model_name: str = "claude-sonnet-5-5"
    max_tokens: int = 1000
    usage: dict | None = Field(default_factory=lambda: dict(SONNET_USAGE))
    fail: bool = False
    reply: str = "ok"
    calls: list = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _get_ls_params(self, stop=None, **kwargs):
        return {"ls_provider": self.provider, "ls_model_name": self.model_name,
                "ls_model_type": "chat", "ls_max_tokens": self.max_tokens}

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls.append(messages)
        if self.fail:
            raise RuntimeError("provider down: key sk-ant-api03-SECRETSECRETSECRET")
        message = AIMessage(content=self.reply)
        if self.usage is not None:
            message.usage_metadata = dict(self.usage)
        return ChatResult(generations=[ChatGeneration(message=message)])


def settings(**budgets):
    """Default settings with some budget fields overridden."""
    return load_settings(env_file=None, budgets=budgets) if budgets else load_settings(env_file=None)
