"""앱 ↔ 백엔드 계약.

피그마 화면 기준으로 필드를 잡았다.
  · 01 Empty state  : GET /faq (Try asking 칩) + GET /sessions (Recent chats)
  · 02 In conversation: POST /chat → reply(말풍선) + cards(말풍선 안 카드) + suggestions(하단 칩)
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Lang = Literal["ko", "en", "ja", "zh"]
CardType = Literal["place", "route", "option", "app_promo", "info", "warning"]


# --------------------------------------------------------------- 요청

class ChatRequest(BaseModel):
    message: str = Field(..., description="사용자 발화", examples=["Store my luggage"])
    session_id: Optional[str] = Field(None, description="없으면 서버가 새로 발급해 응답에 담아 준다")
    lang: Lang = "en"
    lat: Optional[float] = Field(None, description="GPS를 잡았을 때만. 없으면 챗봇이 역을 되묻는다")
    lng: Optional[float] = None


# --------------------------------------------------------------- 응답 조각

class Card(BaseModel):
    """말풍선 안에 들어가는 회색 카드 한 장.

    피그마의 `🧳 Hongdae Stn. Exit 3 Lockers / 4 min walk · Open 24h · Small ₩4,000` 이
    각각 icon + title / meta 다.

    ★ 이 카드의 내용은 전부 **도구가 계산한 사실**이다. LLM이 쓴 문장이 아니다.
      그래서 reply(말풍선 문장)에 환각이 섞여도 카드 수치는 항상 옳다.
    """

    type: CardType
    icon: str = Field("", description="이모지 1자. 그대로 카드 앞에 붙이면 된다", examples=["🧳"])
    title: str = Field(..., examples=["부산역점 (KTX 5번 출구 안쪽)"])
    meta: str = Field("", description="가운뎃점(·)으로 이어 붙인 한 줄 요약. 그대로 렌더",
                      examples=["도보 4분 · 09:00–21:50 · 15,000원"])
    badges: list[str] = Field(default_factory=list, description="칩 형태로 표시할 짧은 라벨")
    lines: list[str] = Field(default_factory=list, description="카드 본문 추가 설명 줄(0~3줄)")
    action_label: Optional[str] = Field(None, description="있으면 카드 하단에 버튼")
    action_url: Optional[str] = None
    data: dict[str, Any] = Field(default_factory=dict, description="좌표·코드 등 앱이 쓸 원자료")


class Suggestion(BaseModel):
    """응답 아래 가로 스크롤 칩."""

    icon: str = ""
    label: str
    prompt: str = Field(..., description="칩을 누르면 이 문자열을 그대로 POST /chat 의 message 로 보낸다")


class ToolTrace(BaseModel):
    """디버깅·발표용. 프론트는 무시해도 된다(개발 중 콘솔 출력 권장)."""

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    ok: bool = True
    notes: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    session_id: str
    reply: str = Field(..., description="어시스턴트 말풍선 본문")
    cards: list[Card] = Field(default_factory=list)
    suggestions: list[Suggestion] = Field(default_factory=list)
    tools: list[ToolTrace] = Field(default_factory=list)
    engine: str = Field("engine", description="engine=실엔진 / fallback=데이터 미탑재 축소모드")


# --------------------------------------------------------------- 기타 엔드포인트

class FaqChip(BaseModel):
    id: str
    icon: str
    label: str = Field(..., description="칩에 보이는 짧은 문구")
    prompt: str = Field(..., description="누르면 그대로 message 로 전송")


class FaqResponse(BaseModel):
    lang: Lang
    greeting_title: str = Field(..., examples=["Hi there 👋"])
    greeting_subtitle: str = Field(..., examples=["How can I help?"])
    greeting_caption: str = Field(..., examples=["From luggage storage to directions — just ask."])
    section_label: str = Field(..., examples=["Try asking"])
    chips: list[FaqChip]


class SessionSummary(BaseModel):
    """Recent chats 한 줄."""

    session_id: str
    icon: str = "💬"
    title: str = Field(..., description="첫 사용자 발화에서 뽑은 제목")
    relative_time: str = Field(..., examples=["Yesterday", "3 days ago"])
    updated_at: str = Field(..., description="ISO8601")


class SessionListResponse(BaseModel):
    sessions: list[SessionSummary]


class HealthResponse(BaseModel):
    status: str
    model: str
    llm_configured: bool
    engine: str
    engine_error: Optional[str] = None
