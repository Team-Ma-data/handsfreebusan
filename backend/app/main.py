import logging

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from .agent import SESSIONS, run_chat
from .config import get_settings
from .engine_adapter import engine_status
from .faq import chips, greeting
from .schemas import (
    ChatRequest,
    ChatResponse,
    FaqResponse,
    HealthResponse,
    SessionListResponse,
)
from .solar import get_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")

settings = get_settings()

app = FastAPI(
    title="TimeCarry API",
    version="1.0.0",
    description=(
        "부산 관광객 AI 어시스턴트 백엔드.\n\n"
        "· `POST /chat` 하나가 대화의 전부다. 프론트는 message 를 보내고 reply·cards·suggestions 를 그린다.\n"
        "· `GET /faq` 는 01 Empty state 화면(인사말 + Try asking 칩)을 통째로 준다.\n"
        "· `GET /sessions` 는 Recent chats 목록.\n\n"
        "카드 내용은 전부 도구가 계산한 사실이고, reply 만 LLM 문장이다."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    st = engine_status()
    return HealthResponse(
        status="ok", model=settings.model, llm_configured=get_client().ready,
        engine=st["source"], engine_error=st["error"],
    )


@app.get("/faq", response_model=FaqResponse, tags=["screen"],
         summary="01 Empty state 화면 데이터")
def faq(lang: str = Query("en", pattern="^(ko|en|ja|zh)$")) -> FaqResponse:
    return FaqResponse(lang=lang, chips=chips(lang), **greeting(lang))  # type: ignore[arg-type]


@app.get("/sessions", response_model=SessionListResponse, tags=["screen"],
         summary="Recent chats 목록")
def sessions(limit: int = Query(20, ge=1, le=50)) -> SessionListResponse:
    return SessionListResponse(sessions=SESSIONS.recent(limit))


@app.post("/chat", response_model=ChatResponse, tags=["chat"],
          summary="02 In conversation — 대화 한 턴")
def chat(req: ChatRequest) -> ChatResponse:
    return run_chat(req)


@app.delete("/chat/{session_id}", tags=["chat"], summary="대화 초기화")
def reset(session_id: str) -> dict:
    SESSIONS.reset(session_id)
    return {"ok": True}
