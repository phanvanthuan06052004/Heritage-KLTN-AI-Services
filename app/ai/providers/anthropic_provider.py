"""
Anthropic provider — LLM only (no embedding, no vision).

Supports: Claude Sonnet, Claude Haiku, Claude Opus, etc.
"""

from typing import Optional

from app.ai.agent_protocol import (
    AssistantTurn,
    ToolCall,
    neutral_to_anthropic_messages,
    openai_tools_to_anthropic,
)
from app.ai.providers.base import LLMProvider, ProviderConfig


class AnthropicLLM(LLMProvider):
    """Anthropic Claude LLM provider."""

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.AsyncAnthropic(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
            )
        return self._client

    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
    ) -> str:
        kwargs = {
            "model": self.config.model_id,
            "max_tokens": max_tokens or 16384,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system

        response = await self.client.messages.create(**kwargs)
        return response.content[0].text if response.content else ""

    async def generate_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.2,
    ) -> AssistantTurn:
        anthropic_messages = neutral_to_anthropic_messages(messages)
        anthropic_tools = openai_tools_to_anthropic(tools)

        kwargs: dict = {
            "model": self.config.model_id,
            "max_tokens": max_tokens or 16384,
            "temperature": temperature,
            "messages": anthropic_messages,
            "tools": anthropic_tools,
        }
        if system:
            kwargs["system"] = system

        response = await self.client.messages.create(**kwargs)

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                args = block.input if isinstance(block.input, dict) else {}
                tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=args))

        reason_map = {"end_turn": "end_turn", "tool_use": "tool_use", "max_tokens": "max_tokens"}
        finish_reason = reason_map.get(response.stop_reason or "end_turn", "end_turn")

        return AssistantTurn(
            text="\n".join(text_parts) or None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
        )

    async def test_connection(self) -> tuple[bool, str]:
        try:
            result = await self.generate("Say 'OK'", max_tokens=10, temperature=0)
            return True, f"OK — model={self.config.model_id}, response='{result[:50]}'"
        except Exception as e:
            return False, f"Anthropic error: {e}"
