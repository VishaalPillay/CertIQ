"""
CertIQ — Base Agent
====================

Base class that ALL specialist agents inherit from.

Provides:
  - OpenAI client configured for GitHub Models
  - Structured output parsing into AgentResponse
  - Retry logic with exponential backoff for 429 rate limits
  - Latency tracking
  - Confidence-based self-reflection trigger

Usage:
    class MyCoolAgent(BaseAgent):
        def __init__(self):
            super().__init__(
                name="my_cool_agent",
                system_prompt="You are a cool agent...",
                model_tier="primary",  # or "lite"
            )

        async def process(self, user_message: str, **kwargs) -> AgentResponse:
            return await self.run(user_message, **kwargs)
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from openai import OpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from agents.config import settings
from agents.schemas import AgentResponse, VerificationResult

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    """Raised when GitHub Models returns a 429 rate limit error."""
    pass


class BaseAgent:
    """
    Base class for all CertIQ agents.

    Handles:
      - OpenAI client setup pointed at GitHub Models
      - Message formatting and structured output parsing
      - Retry with exponential backoff for rate limits
      - Latency measurement
      - Confidence threshold checking
    """

    def __init__(
        self,
        name: str,
        system_prompt: str = "",
        model_tier: str = "primary",
        tools: list[dict] | None = None,
    ):
        """
        Initialize a CertIQ agent.

        Args:
            name: Agent identifier (must match AgentName enum values)
            system_prompt: The system prompt including inline critic instructions
            model_tier: "primary" (gpt-4o) or "lite" (gpt-4o-mini)
            tools: Optional list of tool definitions for function calling
        """
        self.name = name
        self.system_prompt = system_prompt
        self.model_tier = model_tier
        self.model = settings.get_model(model_tier)
        self.tools = tools

        # Initialize OpenAI client pointing at GitHub Models
        self.client = OpenAI(
            base_url=settings.github_models_endpoint,
            api_key=settings.github_token,
        )

        logger.info(
            "Agent '%s' initialized | model=%s | tier=%s",
            self.name, self.model, self.model_tier,
        )

    # ------------------------------------------------------------------
    # Core LLM call with retry
    # ------------------------------------------------------------------

    @retry(
        retry=retry_if_exception_type(RateLimitError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def _call_llm(
        self,
        messages: list[dict[str, str]],
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: dict | None = None,
    ) -> Any:
        """
        Make a single LLM call to GitHub Models with retry on rate limits.

        Args:
            messages: Chat messages (system + user + assistant history)
            tools: Optional tool definitions for function calling
            temperature: Sampling temperature
            max_tokens: Maximum tokens in response
            response_format: Optional response format (e.g., {"type": "json_object"})

        Returns:
            The OpenAI ChatCompletion response object

        Raises:
            RateLimitError: On 429 responses (triggers retry)
        """
        try:
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }

            if tools:
                kwargs["tools"] = tools
            if response_format:
                kwargs["response_format"] = response_format

            return self.client.chat.completions.create(**kwargs)

        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "rate_limit" in error_str.lower():
                logger.warning(
                    "Rate limit hit for agent '%s'. Retrying with backoff...",
                    self.name,
                )
                raise RateLimitError(error_str) from e
            raise

    # ------------------------------------------------------------------
    # High-level run method
    # ------------------------------------------------------------------

    def run(
        self,
        user_message: str,
        context: dict[str, Any] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AgentResponse:
        """
        Run the agent on a user message and return a structured AgentResponse.

        This method:
          1. Builds the message chain (system + history + user)
          2. Calls the LLM via GitHub Models
          3. Parses the response into AgentResponse
          4. Records latency and model used

        Args:
            user_message: The user's input message
            context: Optional additional context (learner data, etc.)
            conversation_history: Optional prior messages for multi-turn
            temperature: Sampling temperature
            max_tokens: Maximum tokens in response

        Returns:
            AgentResponse with confidence_score, verification, etc.
        """
        # Build messages
        messages = self._build_messages(user_message, context, conversation_history)

        # Track latency
        start_time = time.perf_counter()

        # Call LLM
        response = self._call_llm(
            messages=messages,
            tools=self.tools,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )

        latency_ms = (time.perf_counter() - start_time) * 1000

        # Parse response into AgentResponse
        agent_response = self._parse_response(response)
        agent_response.model_used = self.model
        agent_response.latency_ms = round(latency_ms, 2)
        agent_response.agent_name = self.name

        logger.info(
            "Agent '%s' completed | confidence=%.2f | latency=%.0fms | model=%s",
            self.name,
            agent_response.confidence_score,
            agent_response.latency_ms,
            agent_response.model_used,
        )

        return agent_response

    # ------------------------------------------------------------------
    # Tool call handling
    # ------------------------------------------------------------------

    def run_with_tools(
        self,
        user_message: str,
        tool_handlers: dict[str, Any],
        context: dict[str, Any] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
        max_tool_rounds: int = 5,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AgentResponse:
        """
        Run the agent with function calling / tool use.

        This handles the full tool-call loop:
          1. LLM returns tool_calls
          2. Execute each tool via tool_handlers
          3. Send results back to LLM
          4. Repeat until LLM returns a final text response

        Args:
            user_message: The user's input
            tool_handlers: Dict mapping function names to callable handlers
            context: Optional additional context
            conversation_history: Optional prior messages
            max_tool_rounds: Max tool call rounds to prevent infinite loops
            temperature: Sampling temperature
            max_tokens: Maximum tokens in response

        Returns:
            AgentResponse after all tool calls are resolved
        """
        messages = self._build_messages(user_message, context, conversation_history)
        start_time = time.perf_counter()

        for _round in range(max_tool_rounds):
            response = self._call_llm(
                messages=messages,
                tools=self.tools,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            message = response.choices[0].message

            # If no tool calls, we have the final response
            if not message.tool_calls:
                break

            # Process each tool call
            messages.append(message.model_dump())

            for tool_call in message.tool_calls:
                func_name = tool_call.function.name
                func_args = json.loads(tool_call.function.arguments)

                logger.info(
                    "Agent '%s' calling tool: %s(%s)",
                    self.name, func_name, json.dumps(func_args, indent=None)[:200],
                )

                # Execute the tool
                handler = tool_handlers.get(func_name)
                if handler:
                    try:
                        result = handler(**func_args)
                        result_str = json.dumps(result) if not isinstance(result, str) else result
                    except Exception as e:
                        logger.error("Tool '%s' failed: %s", func_name, e)
                        result_str = json.dumps({"error": str(e)})
                else:
                    result_str = json.dumps({"error": f"Unknown tool: {func_name}"})

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_str,
                })

        latency_ms = (time.perf_counter() - start_time) * 1000

        # Parse final response
        agent_response = self._parse_response(response)
        agent_response.model_used = self.model
        agent_response.latency_ms = round(latency_ms, 2)
        agent_response.agent_name = self.name

        return agent_response

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_messages(
        self,
        user_message: str,
        context: dict[str, Any] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> list[dict[str, str]]:
        """Build the full message chain for the LLM call."""
        messages = []

        # System prompt
        if self.system_prompt:
            system_content = self.system_prompt
            if context:
                system_content += f"\n\n## Current Context\n```json\n{json.dumps(context, indent=2, default=str)}\n```"
            messages.append({"role": "system", "content": system_content})

        # Conversation history
        if conversation_history:
            messages.extend(conversation_history)

        # Current user message
        messages.append({"role": "user", "content": user_message})

        return messages

    def _parse_response(self, response: Any) -> AgentResponse:
        """
        Parse an LLM response into an AgentResponse.

        Attempts to parse the response as JSON conforming to AgentResponse.
        Falls back to wrapping raw text if JSON parsing fails.
        """
        content = response.choices[0].message.content or ""

        try:
            # Try to parse as JSON AgentResponse
            data = json.loads(content)
            return AgentResponse(**data)
        except (json.JSONDecodeError, Exception) as e:
            logger.debug(
                "Agent '%s' response is not structured JSON, wrapping: %s",
                self.name, str(e)[:100],
            )
            # Wrap raw text as a basic AgentResponse
            return AgentResponse(
                agent_name=self.name,
                result=content,
                confidence_score=0.5,
                verification=VerificationResult(
                    passed=False,
                    checks_performed=["auto_wrap"],
                    issues_found=["Response was not in structured JSON format"],
                    was_revised=False,
                ),
                reasoning_trace=["Raw text response — not structured"],
            )

    def needs_reflection(self, response: AgentResponse) -> bool:
        """
        Check if a response's confidence is below the threshold,
        indicating the Orchestrator should trigger self-reflection.
        """
        return response.confidence_score < settings.confidence_threshold

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name='{self.name}' model='{self.model}'>"
