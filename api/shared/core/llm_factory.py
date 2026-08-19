from __future__ import annotations

import asyncio
import time
import json
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from openai import AsyncAzureOpenAI, AsyncOpenAI

from .settings import get_settings


def _is_configured_secret(value: str | None) -> bool:
    if not value:
        return False

    normalized = value.strip().lower()
    if not normalized:
        return False

    placeholder_markers = (
        "your-",
        "replace-",
        "example",
        "placeholder",
        "changeme",
    )
    return not any(marker in normalized for marker in placeholder_markers)


class LLMProvider(str, Enum):
    OPENAI = "openai"
    AZURE_OPENAI = "azure_openai"
    GEMINI = "gemini"
    MOCK = "mock"


class LLMClient(Protocol):
    async def agenerate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        ...


@dataclass
class LLMSelection:
    client: LLMClient
    provider: LLMProvider
    fallback_reason: str | None = None


@dataclass
class OpenAILLMClient:
    client: AsyncOpenAI
    model: str

    async def agenerate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        settings = get_settings()
        completion = await asyncio.wait_for(
            self.client.chat.completions.create(
                model=self.model,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            ),
            timeout=max(3, settings.llm_timeout_seconds),
        )

        return (completion.choices[0].message.content or "").strip()

    async def agenerate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        settings = get_settings()
        completion = await asyncio.wait_for(
            self.client.chat.completions.create(
                model=self.model,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            ),
            timeout=max(3, settings.llm_timeout_seconds),
        )
        return (completion.choices[0].message.content or "").strip()


class MockLLMClient:
    async def agenerate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        del system_prompt, temperature, max_tokens
        prompt = user_prompt.strip()
        if len(prompt) > 600:
            prompt = f"{prompt[:600]}..."
        return (
            "I can help with consultant discovery and planning. "
            "Based on your request, I suggest we shortlist candidates by domain, skills, "
            f"and availability.\n\nRequest summary: {prompt}"
        )


    async def agenerate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        del system_prompt, temperature, max_tokens
        prompt = user_prompt.strip()
        primary = "your selected business challenge"
        sub = "your selected sub-hurdle"
        if "Primary Challenge:" in prompt:
            primary = prompt.split("Primary Challenge:", 1)[1].split("\n", 1)[0].strip() or primary
        if "Sub-Hurdle:" in prompt:
            sub = prompt.split("Sub-Hurdle:", 1)[1].split("\n", 1)[0].strip() or sub
        return json.dumps({
            "focus_title": f"Strategic Agenda: {primary}",
            "validation_summary": (
                f"Your focus on {sub} reflects a typical bottleneck where daily "
                f"constraints outpace the current operating model. The root organisational "
                f"bottleneck is the absence of a single accountable process owner across {primary}."
            ),
            "recommended_agenda_items": [
                f"Strategic discovery: align leadership on the macro implications of {primary}.",
                f"Tactical discovery: remove the immediate constraints driving {sub}.",
            ],
        })


@dataclass
class GeminiLLMClient:
    model: str
    api_key: str

    async def agenerate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        import google.generativeai as genai  # type: ignore[import]
        genai.configure(api_key=self.api_key)
        gemini = genai.GenerativeModel(
            model_name=self.model,
            system_instruction=system_prompt,
        )
        settings = get_settings()
        resp = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                None,
                lambda: gemini.generate_content(
                    user_prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=temperature,
                        max_output_tokens=max_tokens,
                    ),
                ),
            ),
            timeout=max(3, settings.llm_timeout_seconds),
        )
        return (resp.text or "").strip()
    async def agenerate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        import google.generativeai as genai
        genai.configure(api_key=self.api_key)
        gemini = genai.GenerativeModel(
            model_name=self.model,
            system_instruction=system_prompt,
        )
        settings = get_settings()
        resp = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                None,
                lambda: gemini.generate_content(
                    user_prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=temperature,
                        max_output_tokens=max_tokens,
                        response_mime_type="application/json",
                    ),
                ),
            ),
            timeout=max(3, settings.llm_timeout_seconds),
        )
        return (resp.text or "").strip()


class LLMFactory:
    def __init__(self):
        self._settings = get_settings()
        self._openai_client: AsyncOpenAI | None = None
        self._azure_openai_client: AsyncAzureOpenAI | None = None
        self._provider_failures: dict[LLMProvider, int] = {
            LLMProvider.OPENAI: 0,
            LLMProvider.AZURE_OPENAI: 0,
            LLMProvider.GEMINI: 0,
            LLMProvider.MOCK: 0,
        }
        self._provider_open_until: dict[LLMProvider, float] = {
            LLMProvider.OPENAI: 0.0,
            LLMProvider.AZURE_OPENAI: 0.0,
            LLMProvider.GEMINI: 0.0,
            LLMProvider.MOCK: 0.0,
        }

    def _is_provider_open(self, provider: LLMProvider) -> bool:
        return time.time() < self._provider_open_until.get(provider, 0.0)

    def _record_provider_success(self, provider: LLMProvider) -> None:
        self._provider_failures[provider] = 0
        self._provider_open_until[provider] = 0.0

    def _record_provider_failure(self, provider: LLMProvider) -> None:
        failures = self._provider_failures.get(provider, 0) + 1
        self._provider_failures[provider] = failures
        threshold = max(1, self._settings.llm_circuit_fail_threshold)
        if failures >= threshold:
            cooldown = max(5, self._settings.llm_circuit_reset_seconds)
            self._provider_open_until[provider] = time.time() + cooldown

    def _get_openai_client(self) -> AsyncOpenAI:
        if self._openai_client is None:
            self._openai_client = AsyncOpenAI(api_key=self._settings.openai_api_key)
        return self._openai_client

    def _get_azure_openai_client(self) -> AsyncAzureOpenAI:
        if self._azure_openai_client is None:
            if not self._settings.azure_openai_endpoint:
                raise RuntimeError("Azure OpenAI endpoint is required.")

            api_key = self._settings.azure_openai_api_key
            if api_key:
                self._azure_openai_client = AsyncAzureOpenAI(
                    api_key=api_key,
                    azure_endpoint=self._settings.azure_openai_endpoint,
                    api_version=self._settings.azure_openai_api_version,
                )
            else:
                # No API key configured: authenticate via the Function App's managed
                # identity (mid-ofs-foundry-001) instead, same pattern used by
                # careers_agentic/vat_resume_analyzer.py. Use the SYNC azure-identity
                # credential (not azure.identity.aio) — the aio variant requires the
                # aiohttp package, which is not in requirements.txt, and the OpenAI
                # SDK's async client accepts sync token-provider callables just fine.
                from azure.identity import DefaultAzureCredential, get_bearer_token_provider

                token_provider = get_bearer_token_provider(
                    DefaultAzureCredential(),
                    "https://cognitiveservices.azure.com/.default",
                )
                self._azure_openai_client = AsyncAzureOpenAI(
                    azure_endpoint=self._settings.azure_openai_endpoint,
                    azure_ad_token_provider=token_provider,
                    api_version=self._settings.azure_openai_api_version,
                )
        return self._azure_openai_client

    async def get_healthy_llm(self) -> tuple[LLMClient, LLMProvider]:
        selected = await self.get_healthy_llm_with_metadata()
        return selected.client, selected.provider

    async def get_healthy_llm_with_metadata(self) -> LLMSelection:
        provider = (self._settings.llm_provider or LLMProvider.OPENAI.value).lower()
        openai_configured = _is_configured_secret(self._settings.openai_api_key)
        # Azure OpenAI only strictly needs an endpoint: if no API key is set, we
        # authenticate via managed identity instead (see _get_azure_openai_client).
        azure_configured = bool((self._settings.azure_openai_endpoint or "").strip())

        if provider == LLMProvider.MOCK.value:
            if self._settings.allow_mock_provider:
                return LLMSelection(client=MockLLMClient(), provider=LLMProvider.MOCK)
            raise RuntimeError("Mock LLM provider is disabled.")

        if provider == LLMProvider.AZURE_OPENAI.value:
            if self._is_provider_open(LLMProvider.AZURE_OPENAI):
                if self._settings.allow_mock_provider:
                    return LLMSelection(
                        client=MockLLMClient(),
                        provider=LLMProvider.MOCK,
                        fallback_reason="azure_openai_circuit_open",
                    )
                raise RuntimeError("Azure OpenAI circuit breaker is open.")

            if azure_configured:
                deployment = self._settings.azure_openai_deployment or self._settings.model_name
                self._record_provider_success(LLMProvider.AZURE_OPENAI)
                return LLMSelection(
                    client=OpenAILLMClient(
                        client=self._get_azure_openai_client(),
                        model=deployment,
                    ),
                    provider=LLMProvider.AZURE_OPENAI,
                )

            if self._settings.allow_mock_provider:
                self._record_provider_failure(LLMProvider.AZURE_OPENAI)
                return LLMSelection(
                    client=MockLLMClient(),
                    provider=LLMProvider.MOCK,
                    fallback_reason="azure_openai_not_configured",
                )

            raise RuntimeError("Azure OpenAI is not configured.")

        # ── Gemini fallback when Azure OpenAI circuit is open ──
        gemini_key = _is_configured_secret(self._settings.gemini_api_key)
        if provider == LLMProvider.AZURE_OPENAI.value and self._is_provider_open(LLMProvider.AZURE_OPENAI):
            if gemini_key and not self._is_provider_open(LLMProvider.GEMINI):
                self._record_provider_success(LLMProvider.GEMINI)
                return LLMSelection(
                    client=GeminiLLMClient(
                        model=self._settings.gemini_model,
                        api_key=self._settings.gemini_api_key,  # type: ignore[arg-type]
                    ),
                    provider=LLMProvider.GEMINI,
                    fallback_reason="azure_openai_circuit_open_gemini_fallback",
                )

        if self._is_provider_open(LLMProvider.OPENAI):
            if self._settings.allow_mock_provider:
                return LLMSelection(
                    client=MockLLMClient(),
                    provider=LLMProvider.MOCK,
                    fallback_reason="openai_circuit_open",
                )
            raise RuntimeError("OpenAI circuit breaker is open.")

        if openai_configured:
            self._record_provider_success(LLMProvider.OPENAI)
            return LLMSelection(
                client=OpenAILLMClient(
                    client=self._get_openai_client(),
                    model=self._settings.model_name,
                ),
                provider=LLMProvider.OPENAI,
            )

        if self._settings.allow_mock_provider:
            self._record_provider_failure(LLMProvider.OPENAI)
            return LLMSelection(
                client=MockLLMClient(),
                provider=LLMProvider.MOCK,
                fallback_reason="openai_not_configured",
            )

        raise RuntimeError("No healthy LLM provider available.")

    def mark_provider_result(self, provider: LLMProvider, *, success: bool) -> None:
        if success:
            self._record_provider_success(provider)
            return
        self._record_provider_failure(provider)


_factory = LLMFactory()


def get_llm_factory() -> LLMFactory:
    return _factory
