from __future__ import annotations

import hashlib
from dataclasses import dataclass
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


class EmbeddingClient(Protocol):
    async def aembed_query(self, text: str) -> list[float]:
        ...

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        ...


@dataclass
class OpenAIEmbeddingClient:
    client: AsyncOpenAI
    model: str

    async def aembed_query(self, text: str) -> list[float]:
        response = await self.client.embeddings.create(model=self.model, input=text)
        return response.data[0].embedding

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self.client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in response.data]


@dataclass
class AzureOpenAIEmbeddingClient:
    client: AsyncAzureOpenAI
    model: str

    async def aembed_query(self, text: str) -> list[float]:
        response = await self.client.embeddings.create(model=self.model, input=text)
        return response.data[0].embedding

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self.client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in response.data]


class MockEmbeddingClient:
    def __init__(self, dimension: int):
        self._dimension = max(8, dimension)

    def _embed(self, text: str) -> list[float]:
        data = text.encode("utf-8", errors="ignore")
        digest = hashlib.sha256(data).digest()
        vector: list[float] = []

        seed = digest
        while len(vector) < self._dimension:
            for byte in seed:
                vector.append((byte / 255.0) * 2.0 - 1.0)
                if len(vector) >= self._dimension:
                    break
            seed = hashlib.sha256(seed).digest()

        return vector

    async def aembed_query(self, text: str) -> list[float]:
        return self._embed(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]


class EmbeddingFactory:
    def __init__(self):
        self._settings = get_settings()
        self._openai_client: AsyncOpenAI | None = None
        self._azure_openai_client: AsyncAzureOpenAI | None = None
        self._instance: EmbeddingClient | None = None

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
                # identity (mid-ofs-foundry-001) instead. Use the SYNC azure-identity
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

    def get_instance(self) -> EmbeddingClient:
        if self._instance is not None:
            return self._instance

        provider = (self._settings.llm_provider or "openai").lower()
        openai_configured = _is_configured_secret(self._settings.openai_api_key)
        # Azure OpenAI only strictly needs an endpoint: if no API key is set, we
        # authenticate via managed identity instead (see _get_azure_openai_client).
        azure_configured = bool((self._settings.azure_openai_endpoint or "").strip())

        if provider == "azure_openai" and azure_configured:
            self._instance = AzureOpenAIEmbeddingClient(
                client=self._get_azure_openai_client(),
                model=self._settings.azure_openai_embedding_deployment or self._settings.embedding_model,
            )
        elif openai_configured:
            self._instance = OpenAIEmbeddingClient(
                client=self._get_openai_client(),
                model=self._settings.embedding_model,
            )
        elif self._settings.allow_mock_provider:
            self._instance = MockEmbeddingClient(self._settings.embedding_dimension)
        else:
            raise RuntimeError("No embedding provider configured.")

        return self._instance


_factory = EmbeddingFactory()


def get_embedding_factory() -> EmbeddingFactory:
    return _factory
