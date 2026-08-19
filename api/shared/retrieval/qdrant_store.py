from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import uuid
from dataclasses import dataclass
from typing import Any
from urllib import error as url_error
from urllib import parse as url_parse
from urllib import request as url_request

from qdrant_client import AsyncQdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointStruct,
    VectorParams,
)

from core.embedding_factory import get_embedding_factory
from core.settings import get_settings


_logger = logging.getLogger("ofstride.vector_store")


@dataclass
class RetrievedDocument:
    page_content: str
    metadata: dict[str, Any]
    score: float | None = None


class QdrantStore:
    def __init__(self):
        self._settings = get_settings()
        self._embedding = get_embedding_factory().get_instance()
        self._memory_docs: list[dict[str, Any]] = []

        self._supabase_url = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
        self._supabase_service_key = (
            os.getenv("SUPABASE_SERVICE_KEY")
            or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            or ""
        ).strip()
        self._vector_backend = (self._settings.vector_backend or "auto").strip().lower()
        self._supabase_vector_table = self._settings.supabase_vector_table
        self._supabase_vector_rpc = self._settings.supabase_vector_rpc
        self._supabase_vector_scan_limit = max(100, self._settings.supabase_vector_scan_limit)

        self._qdrant_enabled = bool(self._settings.qdrant_url)
        self._supabase_enabled = bool(self._supabase_url and self._supabase_service_key)

        self._backend_order = self._build_backend_order()
        self._active_backend = self._backend_order[0]
        self.client = None

        if self._active_backend == "qdrant":
            self.client = AsyncQdrantClient(
                url=self._settings.qdrant_url,
                api_key=self._settings.qdrant_api_key,
                timeout=20,
            )

    def _build_backend_order(self) -> list[str]:
        # Vector store is pinned to Supabase pgvector only. Qdrant is no longer
        # used and there is no in-memory fallback — if Supabase fails, the
        # request should fail loudly rather than silently serving empty/stale
        # in-memory results.
        return ["supabase"]

    def _activate_backend(self, backend: str) -> None:
        self._active_backend = backend
        if backend == "qdrant" and self.client is None:
            self.client = AsyncQdrantClient(
                url=self._settings.qdrant_url,
                api_key=self._settings.qdrant_api_key,
                timeout=20,
            )

    async def _run_with_failover(self, operation: str, func) -> Any:
        errors: list[str] = []
        last_exc: Exception | None = None

        for backend in self._backend_order:
            self._activate_backend(backend)
            try:
                return await func(backend)
            except Exception as exc:  # pylint: disable=broad-except
                last_exc = exc
                errors.append(f"{backend}: {exc}")
                _logger.warning(
                    "Vector backend '%s' failed for %s: %s",
                    backend,
                    operation,
                    exc,
                )

        message = "All vector backends failed for %s: %s" % (
            operation,
            " | ".join(errors) if errors else "no backends configured",
        )
        raise RuntimeError(message) from last_exc

    @staticmethod
    def _extract_doc(document: Any) -> tuple[str, dict[str, Any]]:
        if hasattr(document, "page_content"):
            content = str(getattr(document, "page_content", ""))
            metadata = dict(getattr(document, "metadata", {}) or {})
            return content, metadata

        if hasattr(document, "content"):
            content = str(getattr(document, "content", ""))
            metadata = dict(getattr(document, "metadata", {}) or {})
            return content, metadata

        if isinstance(document, dict):
            content = str(document.get("page_content", document.get("content", "")))
            metadata = dict(document.get("metadata", {}) or {})
            return content, metadata

        raise ValueError("Unsupported document object passed to store")

    def _supabase_headers(self, *, prefer: str | None = None) -> dict[str, str]:
        headers = {
            "apikey": self._supabase_service_key,
            "Authorization": f"Bearer {self._supabase_service_key}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def _supabase_request_sync(
        self,
        method: str,
        path: str,
        *,
        body: dict | list | None = None,
        params: dict[str, str] | None = None,
        prefer: str | None = None,
    ) -> list[dict] | dict | None:
        url = f"{self._supabase_url}/rest/v1/{path}"
        if params:
            url = f"{url}?{url_parse.urlencode(params)}"

        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")

        req = url_request.Request(
            url,
            data=data,
            headers=self._supabase_headers(prefer=prefer),
            method=method,
        )

        try:
            with url_request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8")
                if not raw:
                    return None
                return json.loads(raw)
        except url_error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Supabase HTTP {method} {path} failed with {exc.code}: {err_body[:400]}"
            ) from exc
        except (url_error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Supabase connection error: {exc}") from exc

    async def _supabase_request(
        self,
        method: str,
        path: str,
        *,
        body: dict | list | None = None,
        params: dict[str, str] | None = None,
        prefer: str | None = None,
    ) -> list[dict] | dict | None:
        return await asyncio.to_thread(
            self._supabase_request_sync,
            method,
            path,
            body=body,
            params=params,
            prefer=prefer,
        )

    @staticmethod
    def _vector_to_pg(vector: list[float]) -> str:
        return "[" + ",".join(f"{float(v):.8f}" for v in vector) + "]"

    @staticmethod
    def _parse_vector(raw: Any) -> list[float]:
        if isinstance(raw, list):
            return [float(v) for v in raw]
        if isinstance(raw, str):
            stripped = raw.strip().strip("[]")
            if not stripped:
                return []
            return [float(part.strip()) for part in stripped.split(",") if part.strip()]
        return []

    @staticmethod
    def _json_filter_from_filters(filters: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(filters, dict):
            return {}
        mapped: dict[str, Any] = {}
        for key, value in filters.items():
            if isinstance(value, dict):
                continue
            mapped[key] = value
        return mapped

    async def _ensure_collection_qdrant(self) -> None:
        assert self.client is not None
        exists = await self.client.collection_exists(self._settings.qdrant_collection)
        if exists:
            return

        await self.client.create_collection(
            collection_name=self._settings.qdrant_collection,
            vectors_config=VectorParams(
                size=self._settings.embedding_dimension,
                distance=Distance.COSINE,
            ),
        )

    async def _ensure_collection_supabase(self) -> None:
        await self._supabase_request(
            "GET",
            self._supabase_vector_table,
            params={"select": "id", "limit": "1"},
        )

    async def _add_documents_qdrant(self, normalized: list[tuple[str, dict[str, Any]]], embeddings: list[list[float]]) -> int:
        assert self.client is not None
        points = []
        for (content, metadata), vector in zip(normalized, embeddings):
            points.append(
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vector,
                    payload={"page_content": content, "metadata": metadata},
                )
            )

        await self.client.upsert(
            collection_name=self._settings.qdrant_collection,
            points=points,
            wait=True,
        )
        return len(points)

    async def _add_documents_supabase(self, normalized: list[tuple[str, dict[str, Any]]], embeddings: list[list[float]]) -> int:
        rows = []
        for (content, metadata), vector in zip(normalized, embeddings):
            rows.append(
                {
                    "id": str(uuid.uuid4()),
                    "collection": self._settings.qdrant_collection,
                    "page_content": content,
                    "metadata": metadata,
                    "embedding": self._vector_to_pg(vector),
                }
            )

        await self._supabase_request(
            "POST",
            self._supabase_vector_table,
            body=rows,
            prefer="return=minimal",
        )
        return len(rows)

    async def _search_qdrant(
        self,
        query_embedding: list[float],
        *,
        k: int,
        filters: dict[str, Any] | None,
    ) -> list[RetrievedDocument]:
        assert self.client is not None

        qdrant_filter = None
        if isinstance(filters, dict) and filters:
            must_conditions: list[FieldCondition] = []
            for key, value in filters.items():
                metadata_key = f"metadata.{key}"
                if isinstance(value, dict) and "$in" in value:
                    must_conditions.append(
                        FieldCondition(
                            key=metadata_key,
                            match=MatchAny(any=value["$in"]),
                        )
                    )
                else:
                    must_conditions.append(
                        FieldCondition(
                            key=metadata_key,
                            match=MatchValue(value=value),
                        )
                    )
            if must_conditions:
                qdrant_filter = Filter(must=must_conditions)

        hits = await self.client.query_points(
            collection_name=self._settings.qdrant_collection,
            query=query_embedding,
            query_filter=qdrant_filter,
            limit=max(1, k),
            with_payload=True,
            score_threshold=self._settings.retrieval_score_threshold,
        )
        raw_hits = hits.points if hasattr(hits, "points") else hits

        threshold = self._settings.retrieval_score_threshold
        results: list[RetrievedDocument] = []
        for hit in raw_hits:
            if hit.score is not None and hit.score < threshold:
                continue
            payload = hit.payload or {}
            results.append(
                RetrievedDocument(
                    page_content=str(payload.get("page_content", "")),
                    metadata=dict(payload.get("metadata", {}) or {}),
                    score=float(hit.score) if hit.score is not None else None,
                )
            )
        return results

    async def _search_supabase_rpc(
        self,
        query_embedding: list[float],
        *,
        k: int,
        filters: dict[str, Any] | None,
    ) -> list[RetrievedDocument]:
        payload = {
            "query_embedding": self._vector_to_pg(query_embedding),
            "match_count": max(1, k),
            "match_threshold": float(self._settings.retrieval_score_threshold),
            "match_collection": self._settings.qdrant_collection,
            "metadata_filter": self._json_filter_from_filters(filters),
        }
        rows = await self._supabase_request(
            "POST",
            f"rpc/{self._supabase_vector_rpc}",
            body=payload,
        )

        if not isinstance(rows, list):
            return []

        results: list[RetrievedDocument] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            score = row.get("score")
            results.append(
                RetrievedDocument(
                    page_content=str(row.get("page_content", "")),
                    metadata=dict(row.get("metadata", {}) or {}),
                    score=float(score) if score is not None else None,
                )
            )
        return results

    async def _search_supabase_manual(
        self,
        query_embedding: list[float],
        *,
        k: int,
        filters: dict[str, Any] | None,
    ) -> list[RetrievedDocument]:
        rows = await self._supabase_request(
            "GET",
            self._supabase_vector_table,
            params={
                "select": "page_content,metadata,embedding,collection",
                "collection": f"eq.{self._settings.qdrant_collection}",
                "limit": str(self._supabase_vector_scan_limit),
            },
        )
        if not isinstance(rows, list):
            return []

        scored: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            metadata = dict(row.get("metadata", {}) or {})
            if not self._passes_filters(metadata, filters):
                continue
            vector = self._parse_vector(row.get("embedding"))
            if not vector:
                continue
            score = self._cosine_similarity(query_embedding, vector)
            scored.append((score, row))

        scored.sort(key=lambda x: x[0], reverse=True)
        threshold = self._settings.retrieval_score_threshold
        scored = [(s, r) for s, r in scored if s >= threshold]
        top = scored[: max(1, k)]
        return [
            RetrievedDocument(
                page_content=str(row.get("page_content", "")),
                metadata=dict(row.get("metadata", {}) or {}),
                score=score,
            )
            for score, row in top
        ]

    async def _collection_info_qdrant(self) -> dict[str, Any]:
        assert self.client is not None
        info = await self.client.get_collection(self._settings.qdrant_collection)
        points_count = getattr(info, "points_count", None)
        return {
            "backend": "qdrant",
            "collection": self._settings.qdrant_collection,
            "count": points_count,
        }

    async def _collection_info_supabase(self) -> dict[str, Any]:
        await self._supabase_request(
            "GET",
            self._supabase_vector_table,
            params={"select": "id", "limit": "1"},
        )
        return {
            "backend": "supabase",
            "table": self._supabase_vector_table,
            "rpc": self._supabase_vector_rpc,
            "collection": self._settings.qdrant_collection,
        }

    async def ensure_collection(self) -> None:
        async def _ensure(backend: str) -> None:
            if backend == "memory":
                return
            if backend == "qdrant":
                await self._ensure_collection_qdrant()
                return
            if backend == "supabase":
                await self._ensure_collection_supabase()
                return
            raise RuntimeError(f"Unsupported backend: {backend}")

        await self._run_with_failover("ensure_collection", _ensure)

    async def add_documents(self, documents: list[Any]) -> int:
        if not documents:
            return 0

        normalized = [self._extract_doc(doc) for doc in documents]
        texts = [content for content, _ in normalized]
        embeddings = await self._embedding.aembed_documents(texts)

        async def _add(backend: str) -> int:
            if backend == "memory":
                for (content, metadata), vector in zip(normalized, embeddings):
                    self._memory_docs.append(
                        {
                            "id": str(uuid.uuid4()),
                            "vector": vector,
                            "content": content,
                            "metadata": metadata,
                        }
                    )
                return len(normalized)
            if backend == "qdrant":
                return await self._add_documents_qdrant(normalized, embeddings)
            if backend == "supabase":
                return await self._add_documents_supabase(normalized, embeddings)
            raise RuntimeError(f"Unsupported backend: {backend}")

        return await self._run_with_failover("add_documents", _add)

    @staticmethod
    def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    @staticmethod
    def _passes_filters(metadata: dict[str, Any], filters: dict[str, Any] | None) -> bool:
        if not filters:
            return True

        if not isinstance(filters, dict):
            return True

        for key, value in filters.items():
            actual = metadata.get(key)
            if isinstance(value, dict) and "$in" in value:
                if actual not in value["$in"]:
                    return False
            else:
                if actual != value:
                    return False

        return True

    async def similarity_search(
        self,
        *,
        query: str,
        k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedDocument]:
        if not query.strip():
            return []

        query_embedding = await self._embedding.aembed_query(query)

        async def _search(backend: str) -> list[RetrievedDocument]:
            if backend == "memory":
                scored: list[tuple[float, dict[str, Any]]] = []
                for item in self._memory_docs:
                    if not self._passes_filters(item.get("metadata", {}), filters):
                        continue
                    score = self._cosine_similarity(query_embedding, item["vector"])
                    scored.append((score, item))

                scored.sort(key=lambda x: x[0], reverse=True)
                threshold = self._settings.retrieval_score_threshold
                scored = [(s, d) for s, d in scored if s >= threshold]
                top = scored[: max(1, k)]
                return [
                    RetrievedDocument(
                        page_content=item["content"],
                        metadata=item["metadata"],
                        score=score,
                    )
                    for score, item in top
                ]

            if backend == "qdrant":
                return await self._search_qdrant(query_embedding, k=k, filters=filters)

            if backend == "supabase":
                try:
                    return await self._search_supabase_rpc(query_embedding, k=k, filters=filters)
                except Exception as exc:  # pylint: disable=broad-except
                    _logger.warning(
                        "Supabase vector RPC failed (%s), falling back to manual scan.",
                        exc,
                    )
                    return await self._search_supabase_manual(query_embedding, k=k, filters=filters)

            raise RuntimeError(f"Unsupported backend: {backend}")

        return await self._run_with_failover("similarity_search", _search)

    async def collection_info(self) -> dict[str, Any]:
        async def _info(backend: str) -> dict[str, Any]:
            if backend == "memory":
                return {
                    "backend": "memory",
                    "collection": self._settings.qdrant_collection,
                    "count": len(self._memory_docs),
                }
            if backend == "qdrant":
                return await self._collection_info_qdrant()
            if backend == "supabase":
                return await self._collection_info_supabase()
            raise RuntimeError(f"Unsupported backend: {backend}")

        return await self._run_with_failover("collection_info", _info)
