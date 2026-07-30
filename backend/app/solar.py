"""Upstage Solar (OpenAI 호환) 클라이언트.

.env 의 UPSTAGE_API_KEY 하나만 채우면 동작한다.
Upstage는 OpenAI 호환 /chat/completions 를 제공하므로 openai SDK를 그대로 쓴다.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from openai import OpenAI

from .config import get_settings

log = logging.getLogger("timecarry.solar")


class SolarUnavailable(RuntimeError):
    """키가 없거나 API 호출이 실패했을 때. 호출부는 이걸 잡아 폴백 응답을 낸다."""


class SolarClient:
    def __init__(self) -> None:
        s = get_settings()
        self.settings = s
        self._client: Optional[OpenAI] = None
        #: tools 파라미터가 거부되면 True로 바뀌고 이후 도구 없이 동작한다(=대화만).
        self.tools_unsupported = False
        if s.has_key:
            self._client = OpenAI(
                api_key=s.upstage_api_key,
                base_url=s.upstage_base_url,
                timeout=s.request_timeout,
            )
        else:
            log.warning("UPSTAGE_API_KEY 가 비어 있습니다 — LLM 없이 도구 폴백 모드로 동작합니다.")

    @property
    def ready(self) -> bool:
        return self._client is not None

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict]] = None,
        tool_choice: str = "auto",
    ):
        if self._client is None:
            raise SolarUnavailable("UPSTAGE_API_KEY is not set")

        kwargs: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": self.settings.temperature,
        }
        if tools and not self.tools_unsupported:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        try:
            return self._client.chat.completions.create(**kwargs)
        except Exception as e:
            msg = str(e)
            # 모델이 tools를 지원하지 않는 경우 한 번만 도구 없이 재시도하고, 이후로는 끈다.
            if tools and not self.tools_unsupported and _looks_like_tool_error(msg):
                log.warning("모델이 tools 를 거부했습니다 — 도구 없이 재시도합니다: %s", msg[:200])
                self.tools_unsupported = True
                kwargs.pop("tools", None)
                kwargs.pop("tool_choice", None)
                try:
                    return self._client.chat.completions.create(**kwargs)
                except Exception as e2:
                    raise SolarUnavailable(str(e2)) from e2
            raise SolarUnavailable(msg) from e


def _looks_like_tool_error(msg: str) -> bool:
    m = msg.lower()
    return ("tool" in m or "function" in m) and any(
        k in m for k in ("not support", "unsupported", "invalid", "unrecognized", "400")
    )


_singleton: Optional[SolarClient] = None


def get_client() -> SolarClient:
    global _singleton
    if _singleton is None:
        _singleton = SolarClient()
    return _singleton
