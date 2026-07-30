import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


class Settings:
    # ---- Upstage Solar -------------------------------------------------
    #: .env 의 UPSTAGE_API_KEY 하나만 채우면 동작한다.
    upstage_api_key: str = os.getenv("UPSTAGE_API_KEY", "")
    #: Upstage는 OpenAI 호환 엔드포인트를 제공한다. 구 문서 기준 주소는 .../v1/solar 였으므로
    #: 401/404가 나면 .env 에서 이 값만 바꿔보면 된다.
    upstage_base_url: str = os.getenv("UPSTAGE_BASE_URL", "https://api.upstage.ai/v1")
    model: str = os.getenv("SOLAR_MODEL", "solar-pro3")

    temperature: float = float(os.getenv("SOLAR_TEMPERATURE", "0.2"))
    max_tool_turns: int = int(os.getenv("MAX_TOOL_TURNS", "4"))
    request_timeout: float = float(os.getenv("REQUEST_TIMEOUT", "45"))

    # ---- 서버 ----------------------------------------------------------
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))
    cors_origins: list[str] = os.getenv("CORS_ORIGINS", "*").split(",")

    #: 세션 히스토리 최대 턴 수(사용자+어시스턴트 메시지 개수)
    history_limit: int = int(os.getenv("HISTORY_LIMIT", "20"))

    #: True면 팀원 engine/ladder.py 가 있어도 스텁을 쓴다 (데모 리스크 헤지용)
    force_stub: bool = os.getenv("TIMECARRY_FORCE_STUB", "0") == "1"

    @property
    def has_key(self) -> bool:
        return bool(self.upstage_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
