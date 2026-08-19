from __future__ import annotations

import logging
from typing import Any

from core.settings import get_settings

_logger = logging.getLogger("ofstride.langfuse")


class LangfuseTracer:
    def __init__(self) -> None:
        self.enabled = False
        self._client: Any = None
        self._initialized = False
        self._configured = False
        self._host = "https://cloud.langfuse.com"
        self._reason = "not_initialized"

    @staticmethod
    def _is_configured_secret(value: str | None) -> bool:
        if not value:
            return False
        normalized = value.strip().lower()
        if not normalized:
            return False
        placeholder_markers = (
            "pk-lf-your",
            "sk-lf-your",
            "your-",
            "replace-",
            "example",
            "placeholder",
            "changeme",
        )
        return not any(marker in normalized for marker in placeholder_markers)

    def _ensure_init(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        settings = get_settings()
        self._host = (settings.langfuse_host or "https://cloud.langfuse.com").strip()

        if not settings.langfuse_enabled:
            self._reason = "disabled_via_env"
            return

        pk = settings.langfuse_public_key
        sk = settings.langfuse_secret_key
        if not self._is_configured_secret(pk) or not self._is_configured_secret(sk):
            self._reason = "missing_or_placeholder_keys"
            return

        self._configured = True
        try:
            from langfuse import Langfuse  # type: ignore[import]
            self._client = Langfuse(public_key=pk, secret_key=sk, host=self._host)
            self.enabled = True
            self._reason = "enabled"
            _logger.info("Langfuse tracing enabled host=%s", self._host)
        except ImportError:
            self._reason = "langfuse_package_missing"
            _logger.warning("langfuse package not installed; tracing disabled")
        except Exception as exc:
            self._reason = f"init_failed:{str(exc)[:160]}"
            _logger.warning("Langfuse init failed: %s", exc)

    def status(self) -> dict[str, Any]:
        self._ensure_init()
        return {
            "enabled": self.enabled,
            "configured": self._configured,
            "host": self._host,
            "reason": self._reason,
        }

    def trace_turn(
        self,
        *,
        conversation_id: str,
        trace_id: str,
        user_message: str,
        rewritten_query: str | None,
        retrieved_chunks: list[dict],
        model_used: str,
        fallback_triggered: bool,
        system_prompt: str,
        user_prompt: str,
        response: str,
        latency_ms: float,
        input_tokens: int | None,
        output_tokens: int | None,
        route_decision: str,
    ) -> None:
        self._ensure_init()
        if not self.enabled or self._client is None:
            return
        try:
            trace = self._client.trace(
                id=trace_id,
                name="chat_turn",
                session_id=conversation_id,
                metadata={
                    "route_decision": route_decision,
                    "fallback_triggered": fallback_triggered,
                    "chunk_count": len(retrieved_chunks),
                    "rewritten_query": rewritten_query,
                    "model_used": model_used,
                },
                input={"user_message": user_message},
                output={"response": response},
            )

            try:
                trace.span(
                    name="retrieval",
                    input={"query": rewritten_query or user_message},
                    output={
                        "chunks": [
                            {"score": c.get("score"), "metadata": c.get("metadata", {})}
                            for c in retrieved_chunks
                        ]
                    },
                    metadata={"chunk_count": len(retrieved_chunks)},
                )
            except Exception as exc:
                _logger.debug("Langfuse retrieval span failed: %s", exc)

            usage: dict[str, int] = {}
            if isinstance(input_tokens, int):
                usage["input"] = input_tokens
            if isinstance(output_tokens, int):
                usage["output"] = output_tokens

            generation_payload: dict[str, Any] = {
                "name": "llm_generation",
                "model": model_used,
                "completion": response,
                "latency": max(0.0, latency_ms / 1000),
            }
            if system_prompt or user_prompt:
                generation_payload["prompt"] = [
                    {"role": "system", "content": system_prompt[:500]},
                    {"role": "user", "content": user_prompt[:500]},
                ]
            if usage:
                generation_payload["usage"] = usage

            try:
                trace.generation(**generation_payload)
            except Exception as exc:
                _logger.debug("Langfuse generation span failed: %s", exc)

            self._client.flush()
        except Exception as exc:
            _logger.warning("Langfuse trace_turn failed: %s", exc)


_tracer = LangfuseTracer()


def get_tracer() -> LangfuseTracer:
    return _tracer
