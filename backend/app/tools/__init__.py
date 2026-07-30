"""LLM 툴콜링 도구 모음.

규약(모든 도구 공통):
    함수는 dict를 반환한다.
      · 일반 키       → 그대로 LLM에게 전달되는 '사실'
      · "_cards"      → 앱에 렌더링할 구조화 카드. LLM에게는 전달하지 않는다(토큰 절약 + 환각 차단)
      · "_notes"      → 사람이 읽는 디버깅/발표용 로그
      · "_suggestions"→ 다음 질문 칩 제안

핵심 원칙: **정책과 하드 제약은 프롬프트가 아니라 이 코드 안에 있다.**
프롬프트는 바뀌기 쉽고 모델마다 다르게 해석되지만, 코드는 그렇지 않다.
"""

from .atm import TOOLS as ATM_TOOLS
from .luggage import TOOLS as LUGGAGE_TOOLS

ALL_TOOLS = {**LUGGAGE_TOOLS, **ATM_TOOLS}

#: Solar(OpenAI 호환)에 넘길 tools 스펙
TOOL_SPECS = [t["spec"] for t in ALL_TOOLS.values()]


def call_tool(name: str, arguments: dict) -> dict:
    tool = ALL_TOOLS.get(name)
    if tool is None:
        return {"error": f"unknown tool: {name}"}
    try:
        return tool["fn"](**arguments)
    except TypeError as e:
        return {"error": f"invalid arguments for {name}: {e}"}
    except Exception as e:  # 도구가 죽어도 대화는 계속되어야 한다
        return {"error": f"{name} failed: {e}"}


__all__ = ["ALL_TOOLS", "TOOL_SPECS", "call_tool"]
