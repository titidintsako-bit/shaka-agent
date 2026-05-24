"""Agent Brain for Shaka.

Handles LLM communication, context management, and tool execution.
Models: OpenAI, Anthropic, Groq, Gemini, OpenRouter, Ollama, and OpenAI-compatible providers.

This is the CORE of Shaka - the intelligence layer.
"""

import os
import json
import time
import re
from typing import Any, List, Dict, Optional, Callable
from .message_builder import MessageBuilder
from .fact_extractor import FactExtractor
from .providers import get_provider_spec, normalize_provider
from .automation import RISK_DESTRUCTIVE, RISK_READ_ONLY, RISK_RISKY_WRITE, RISK_SECRET, RiskClassifier, TaskStore
from .redaction import redact_data, redact_text

class LLMProvider:
    """Base class for LLM providers."""

    def generate(self, messages: list, tools: list = None, model: str = None) -> dict:
        raise NotImplementedError

class GroqProvider(LLMProvider):
    """Groq API provider - Free tier available."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.groq.com/openai/v1"
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url,
                )
            except ImportError:
                raise ImportError("openai package required: pip install openai")
        return self._client

    def generate(self, messages: list, tools: list = None, model: str = "llama-3.3-70b-versatile") -> dict:
        client = self._get_client()
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
        }
        if tools:
            kwargs["tools"] = tools
        response = client.chat.completions.create(**kwargs)

        message = response.choices[0].message
        usage = response.usage

        result = {
            "content": message.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments),
                }
                for tc in message.tool_calls
            ] if message.tool_calls else [],
            "tokens_used": usage.total_tokens if usage else 0,
            "raw_id": response.id,
        }
        return result

class OpenAICompatibleProvider(LLMProvider):
    """Provider backed by the OpenAI chat-completions client."""

    def __init__(self, api_key: str, base_url: str = "", headers: dict | None = None):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = headers or {}
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
                kwargs = {"api_key": self.api_key}
                if self.base_url:
                    kwargs["base_url"] = self.base_url
                if self.headers:
                    kwargs["default_headers"] = self.headers
                self._client = OpenAI(**kwargs)
            except ImportError:
                raise ImportError("openai package required: pip install openai")
        return self._client

    def generate(self, messages: list, tools: list = None, model: str = "gpt-4o-mini") -> dict:
        client = self._get_client()
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
        }
        if tools:
            kwargs["tools"] = tools
        response = client.chat.completions.create(**kwargs)

        message = response.choices[0].message
        usage = response.usage

        return {
            "content": message.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments),
                }
                for tc in message.tool_calls
            ] if message.tool_calls else [],
            "tokens_used": usage.total_tokens if usage else 0,
            "raw_id": response.id,
        }


class AnthropicProvider(LLMProvider):
    """Anthropic Messages API provider."""

    def __init__(self, api_key: str, base_url: str = "https://api.anthropic.com"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def generate(self, messages: list, tools: list = None, model: str = "claude-3-5-haiku-latest") -> dict:
        try:
            import requests
        except ImportError:
            raise ImportError("requests package required: pip install requests")

        system_prompt = ""
        anthropic_messages = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content") or ""
            if role == "system":
                system_prompt = f"{system_prompt}\n{content}".strip()
                continue
            if role == "tool":
                role = "user"
            if role not in {"user", "assistant"}:
                continue
            anthropic_messages.append({"role": role, "content": content})

        payload = {
            "model": model,
            "max_tokens": 4096,
            "temperature": 0.7,
            "messages": anthropic_messages or [{"role": "user", "content": "Hello"}],
        }
        if system_prompt:
            payload["system"] = system_prompt

        response = requests.post(
            f"{self.base_url}/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        text_parts = [part.get("text", "") for part in data.get("content", []) if part.get("type") == "text"]
        usage = data.get("usage", {}) or {}
        return {
            "content": "\n".join(part for part in text_parts if part),
            "tool_calls": [],
            "tokens_used": int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0)),
            "raw_id": data.get("id", ""),
        }


class GeminiProvider(LLMProvider):
    """Google AI Studio provider - Free tier available."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                self._client = genai
                self._genai = genai
            except ImportError:
                raise ImportError("google-generativeai package required: pip install google-generativeai")
        return self._client

    def generate(self, messages: list, tools: list = None, model: str = "gemini-2.0-flash") -> dict:
        genai = self._get_client()
        generation_config = {
            "temperature": 0.7,
            "top_p": 0.95,
            "top_k": 40,
            "max_output_tokens": 8192,
        }

        # Build system prompt from first message
        system_prompt = ""
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_prompt = msg["content"]
            else:
                chat_messages.append(msg)

        model_obj = genai.GenerativeModel(
            model_name=model,
            generation_config=generation_config,
            system_instruction=system_prompt if system_prompt else None,
        )

        # Convert OpenAI format to Gemini format
        prompt_parts = []
        for msg in chat_messages:
            role = msg["role"]
            content = msg["content"]
            if role == "assistant":
                role = "model"
            prompt_parts.append({"role": role, "parts": [{"text": content}]})

        response = model_obj.generate_content(
            [p["parts"][0]["text"] for p in prompt_parts] if prompt_parts else ["Hello"]
        )

        return {
            "content": response.text,
            "tool_calls": [],
            "tokens_used": 0,  # Gemini doesn't provide this directly
            "raw_id": "",
        }

class OpenRouterProvider(LLMProvider):
    """OpenRouter provider."""

    def __init__(self, api_key: str, base_url: str = None):
        self.api_key = api_key
        self.base_url = base_url or "https://openrouter.ai/api/v1"
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url,
                    default_headers={
                        "HTTP-Referer": "https://shaka.dev",
                        "X-Title": "Shaka Agent",
                    }
                )
            except ImportError:
                raise ImportError("openai package required: pip install openai")
        return self._client

    def generate(self, messages: list, tools: list = None, model: str = "openai/gpt-4o-mini") -> dict:
        client = self._get_client()
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
        }
        if tools:
            kwargs["tools"] = tools
        response = client.chat.completions.create(**kwargs)

        message = response.choices[0].message
        usage = response.usage

        return {
            "content": message.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments),
                }
                for tc in message.tool_calls
            ] if message.tool_calls else [],
            "tokens_used": usage.total_tokens if usage else 0,
            "raw_id": response.id,
        }

class OllamaProvider(LLMProvider):
    """Local Ollama provider."""

    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    api_key="ollama",  # dummy key
                    base_url=f"{self.base_url}/v1",
                )
            except ImportError:
                raise ImportError("openai package required: pip install openai")
        return self._client

    def generate(self, messages: list, tools: list = None, model: str = "qwen2.5:7b") -> dict:
        client = self._get_client()
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
        }
        if tools:
            kwargs["tools"] = tools
        response = client.chat.completions.create(**kwargs)

        message = response.choices[0].message
        usage = response.usage

        return {
            "content": message.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments),
                }
                for tc in message.tool_calls
            ] if message.tool_calls else [],
            "tokens_used": usage.total_tokens if usage else 0,
            "raw_id": response.id,
        }

class Agent:
    """The brain of Shaka. Manages LLM calls, memory injection, and tool execution."""

    def __init__(self, config, skills_registry, memory_manager, user_id: str = "default"):
        self.config = config
        self.skills_registry = skills_registry
        self.memory = memory_manager
        self.user_id = user_id

        # Initialize the LLM provider
        self.provider = self._create_provider()

        # Track usage
        self.session_messages = []
        self.total_tokens = 0
        self.total_cost = 0.0
        # Initialize helper components
        self.message_builder = MessageBuilder(config, skills_registry, memory_manager, user_id)
        self.fact_extractor = FactExtractor()
        self.task_store = TaskStore(config.paths.base_dir)


    def _create_provider(self) -> LLMProvider:
        """Create the appropriate LLM provider based on config."""
        model_config = self.config.model
        provider_name = normalize_provider(model_config.provider)
        try:
            spec = get_provider_spec(provider_name)
        except KeyError as exc:
            raise ValueError(f"Unknown provider: {provider_name}") from exc

        if provider_name == "gemini":
            return GeminiProvider(model_config.api_key)
        if provider_name == "anthropic":
            return AnthropicProvider(model_config.api_key, model_config.base_url or spec.base_url or "https://api.anthropic.com")
        if provider_name == "ollama":
            return OllamaProvider(model_config.base_url or spec.base_url or "http://localhost:11434")
        if provider_name == "groq":
            return GroqProvider(model_config.api_key)
        if provider_name == "openrouter":
            return OpenRouterProvider(model_config.api_key, model_config.base_url or spec.base_url)
        if spec.openai_compatible:
            headers = {}
            if provider_name == "openrouter":
                headers = {"HTTP-Referer": "https://shaka.dev", "X-Title": "Shaka Agent"}
            return OpenAICompatibleProvider(model_config.api_key, model_config.base_url or spec.base_url, headers=headers)
        raise ValueError(f"Provider is not implemented: {provider_name}")

    def _build_messages(self, user_message: str, session_id: str, extra_system_messages: Optional[list] = None) -> list:
        """Build the full message context for the LLM."""
        return self.message_builder.build_messages(user_message, session_id, extra_system_messages=extra_system_messages)

    def chat(self, message: str, session_id: str = None, extra_system_messages: Optional[list] = None, disable_tools: bool = False) -> dict:
        """Send a message to the agent and get a response."""
        if not session_id:
            session_id = f"session_{int(time.time())}"

        # Get tools from skills
        tools = None if disable_tools else self.skills_registry.get_tools_definition()

        # Build messages with context
        messages = self._build_messages(message, session_id, extra_system_messages=extra_system_messages)

        # Call the LLM
        start_time = time.time()
        response_content = ""
        tool_calls = []
        tokens_used = 0
        used_fallback = False

        try:
            result = self.provider.generate(
                messages=messages,
                tools=tools if tools else None,
                model=self.config.model.model,
            )
            elapsed = time.time() - start_time

            response_content = result.get("content", "")
            tool_calls = result.get("tool_calls", [])
            tokens_used = result.get("tokens_used", 0)
        except Exception as e:
            error_str = str(e)
            # Groq tool calling sometimes fails with malformed function calls
            # Retry without tools as fallback
            if "tool_use_failed" in error_str or "400" in error_str:
                print(f"  [Tool call failed, retrying without tools...]")
                used_fallback = True
                result = self.provider.generate(
                    messages=messages,
                    tools=None,  # No tools on retry
                    model=self.config.model.model,
                )
                elapsed = time.time() - start_time
                response_content = result.get("content", "")
                tokens_used = result.get("tokens_used", 0)
            else:
                raise

        # Track message
        msg_record = {"role": "user", "content": message}
        self.session_messages.append(msg_record)
        self.memory.save_session(self.user_id, session_id, self.session_messages)

        # Execute tool calls if any
        tool_calls_executed = 0
        tool_calls_pending_approval = 0
        if tool_calls:
            for tool_call in tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call.get("arguments", {})
                if isinstance(tool_args, str):
                    try:
                        tool_args = json.loads(tool_args)
                    except:
                        tool_args = {}

                # Add tool result to messages
                # Ensure tool_args is a dict for JSON serialization
                if tool_args is None:
                    tool_args = {}
                elif not isinstance(tool_args, dict):
                    # If it's not a dict, try to parse it as JSON, otherwise make empty dict
                    try:
                        tool_args = json.loads(tool_args) if isinstance(tool_args, str) else {}
                    except:
                        tool_args = {}

                policy = self._tool_policy(tool_name, tool_args)
                if policy["requires_approval"]:
                    tool_result = self._queue_tool_approval(
                        tool_name,
                        tool_args,
                        policy,
                        session_id=session_id,
                    )
                    tool_calls_pending_approval += 1
                else:
                    try:
                        tool_result = self.skills_registry.execute_tool(tool_name, **tool_args)
                        tool_calls_executed += 1
                    except Exception as e:
                        tool_result = f"Error executing {tool_name}: {str(e)}"
                
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": tool_call["id"],
                        "type": "function",
                        "function": {
                            "name": tool_name, 
                            "arguments": json.dumps(tool_args)
                        }
                    }],
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.get("id", "unknown"),
                    "content": str(tool_result),
                })

                # Get final response after tool execution
                final_result = self.provider.generate(
                    messages=messages,
                    model=self.config.model.model,
                )
                response_content = final_result.get("content", response_content)
                tokens_used += final_result.get("tokens_used", 0)

        # Final cleanup: remove any python tags or code blocks the model leaked
        if response_content:
            # Strip <|python_tag|> blocks
            response_content = re.sub(r'<\|python_tag\|>.*?(?:\n|$)', '', response_content)
            # Strip markdown code blocks if they contain the leaked code
            response_content = re.sub(r'```python\s+import.*?```', '', response_content, flags=re.DOTALL)

        # Save assistant response
        assistant_msg = {"role": "assistant", "content": response_content}
        self.session_messages.append(assistant_msg)
        self.memory.save_session(self.user_id, session_id, self.session_messages)

        # Update usage stats
        self.total_tokens += tokens_used

        # Update memory with any new facts the agent extracted
        self._extract_facts(message, response_content)

        return {
            "response": response_content,
            "session_id": session_id,
            "tokens_used": tokens_used,
            "elapsed_seconds": round(elapsed, 2),
            "tool_calls_executed": tool_calls_executed,
            "tool_calls_pending_approval": tool_calls_pending_approval,
        }

    def _tool_policy(self, tool_name: str, tool_args: dict[str, Any]) -> dict[str, Any]:
        """Classify model-requested tools before direct execution."""
        name = (tool_name or "").lower()
        action = str(tool_args.get("action", "")).lower()

        if name == "codeexec":
            risk = RISK_RISKY_WRITE
            summary = "Execute local code"
        elif name == "fileops" and action in {"write", "create"}:
            risk = RISK_RISKY_WRITE
            summary = f"{action.title()} local file"
        elif name == "fileops" and action == "delete":
            risk = RISK_DESTRUCTIVE
            summary = "Delete local path"
        elif name == "fileops" and action in {"read", "list", "exists"}:
            return {
                "risk": RISK_READ_ONLY,
                "summary": f"{action.title()} local path",
                "requires_approval": False,
            }
        else:
            skill_policy = self._skill_declared_policy(tool_name)
            if skill_policy and skill_policy.get("approval_required"):
                return {
                    "risk": skill_policy.get("risk") or RISK_RISKY_WRITE,
                    "summary": f"Run tool: {tool_name}",
                    "requires_approval": True,
                }

            risk = RiskClassifier.classify(f"tool:{name}", command=json.dumps(tool_args, default=str))
            summary = f"Run tool: {tool_name}"
            if risk in {RISK_RISKY_WRITE, RISK_DESTRUCTIVE, RISK_SECRET}:
                return {
                    "risk": risk,
                    "summary": summary,
                    "requires_approval": True,
                }
            return {
                "risk": RISK_READ_ONLY,
                "summary": summary,
                "requires_approval": False,
            }

        return {
            "risk": risk,
            "summary": summary,
            "requires_approval": True,
        }

    def _skill_declared_policy(self, tool_name: str) -> dict[str, Any] | None:
        """Read approval metadata advertised by the skill registry, if present."""
        if not hasattr(self.skills_registry, "list_skills"):
            return None
        try:
            skills = self.skills_registry.list_skills()
        except Exception:
            return None
        for skill in skills:
            if str(skill.get("name", "")).lower() != str(tool_name or "").lower():
                continue
            risk = skill.get("risk") if isinstance(skill.get("risk"), dict) else {}
            return {
                "risk": skill.get("risk_level") or risk.get("level") or RISK_RISKY_WRITE,
                "approval_required": bool(skill.get("approval_required") or risk.get("approval_required")),
                "mutating": bool(skill.get("mutating") or risk.get("mutating")),
            }
        return None

    def _queue_tool_approval(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        policy: dict[str, Any],
        *,
        session_id: str,
    ) -> str:
        """Record a pending approval instead of executing a risky model tool call."""
        safe_args = redact_data(tool_args)
        task = self.task_store.create_task(
            title=f"Approve tool call: {tool_name}",
            kind="agent-tool",
            payload={
                "tool_name": tool_name,
                "arguments": safe_args,
                "session_id": session_id,
                "approval_only": True,
            },
            status="queued",
        )
        self.task_store.add_step(
            task["id"],
            f"Tool call paused for approval: {tool_name}",
            kind="approval_required",
            metadata={"tool_name": tool_name, "risk": policy["risk"], "arguments": safe_args},
        )
        approval = self.task_store.create_approval(
            task["id"],
            action=f"tool:{tool_name}",
            risk=policy["risk"],
            summary=f"{policy['summary']}: {tool_name}",
            payload={"tool_name": tool_name, "arguments": safe_args},
        )
        return (
            "Approval required before Shaka can run this tool. "
            f"Tool: {tool_name}. Risk: {policy['risk']}. "
            f"Task: {task['id']}. Approval: {approval['id']}."
        )

    def _extract_facts(self, user_msg: str, assistant_msg: str) -> list:
        """Extract and remember important facts from conversation."""
        return self.fact_extractor.extract_facts(user_msg, assistant_msg)

    def get_recent_messages(self, session_id: str, limit: int = 10) -> list:
        """Get recent messages from a session."""
        return self.memory.get_recent_messages(self.user_id, session_id, limit)
