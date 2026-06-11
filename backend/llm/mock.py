"""Scripted LLM client for tests — same interface as OpenRouterClient.chat."""
from .openrouter import LLMResponse, ToolCall


class MockLLMClient:
    def __init__(self, scripted_responses):
        """scripted_responses: list of (tool_name, arguments) tuples or LLMResponse."""
        self.model = "mock/mock-model"
        self._responses = list(scripted_responses)
        self.calls = []

    def chat(self, messages, tools=None, tool_choice=None, temperature=0.0, model=None) -> LLMResponse:
        self.calls.append({"messages": messages, "tools": tools})
        if not self._responses:
            return LLMResponse(tool_calls=[ToolCall("finish", {
                "success": False, "summary": "mock script exhausted"})])
        item = self._responses.pop(0)
        if isinstance(item, LLMResponse):
            return item
        name, args = item
        return LLMResponse(tool_calls=[ToolCall(name, args)], prompt_tokens=10, completion_tokens=5)
