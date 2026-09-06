# 출처: 전시관 AI 안내 서비스 (2026.03~) — 요청 ID 옆에 고객사(전시 주체) · WebSocket 세션 컨텍스트를 덧붙인 확장. 한 파일에 원본 두 곳(컨텍스트 변수 · 실제 세팅 지점)을 모았다
import logging
import uuid
from contextvars import ContextVar

from fastapi import WebSocket
# ...

# ---- app/core/logging/context.py -------------------------------------------
# 요청 ID 하나로는 부족했다. 도슨트 · 통역 WebSocket 은 한 연결에서 수백 줄이 찍히고,
# 여러 고객사가 같은 서버를 쓰므로 "누구의 어느 세션" 인지 줄마다 붙어야 했다.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
agent_id_var: ContextVar[str] = ContextVar("agent_id", default="-")      # 고객사(전시 주체) 식별자
session_id_var: ContextVar[str] = ContextVar("session_id", default="-")  # WebSocket 세션 짧은 ID


def set_request_id(request_id: str) -> None:
    request_id_var.set(request_id)


def get_request_id() -> str:
    return request_id_var.get()


def set_agent_id(agent_id: int | str) -> None:
    agent_id_var.set(str(agent_id))


def get_agent_id() -> str:
    return agent_id_var.get()


def set_session_id(session_id: str) -> None:
    session_id_var.set(session_id)


def get_session_id() -> str:
    return session_id_var.get()


# ---- app/core/logging/config.py (필터만) -----------------------------------
LOG_FORMAT = (
    "[%(asctime)s] [%(levelname)s] [req:%(request_id)s] "
    "[agent:%(agent_id)s] [session:%(session_id)s] [%(name)s] %(message)s"
)


class RequestIdFilter(logging.Filter):
    # 컨텍스트가 늘어나면 필터에 한 줄, 포맷에 한 칸만 더한다. 호출부는 바뀌지 않는다
    def filter(self, record):
        record.request_id = get_request_id()
        record.agent_id = get_agent_id()
        record.session_id = get_session_id()
        return True


# ---- app/module/infra/gemini/gemini_live_service.py (세팅 지점) -------------
logger = logging.getLogger(__name__)


class GeminiLiveService:
    # ... (생략)

    async def translate_ws(self, websocket: WebSocket):
        # 연결 하나가 세션 하나 — 이 코루틴 안에서 찍히는 모든 줄에 같은 세션 ID 가 붙는다
        set_session_id(uuid.uuid4().hex[:8])
        lang = websocket.query_params.get("lang", "en")
        await websocket.accept()
        # ... (생략) 실시간 통역 세션

    async def docent_ws(self, websocket: WebSocket, agent_id: int):
        set_session_id(uuid.uuid4().hex[:8])
        # ... (생략) 전시 · 고객사 조회
        # 고객사가 정해지는 순간 컨텍스트에 넣는다 — 이후 작품 조회 · 모델 호출 로그가 전부 이 값을 단다
        set_agent_id(agent_id)
        logger.info("docent session start lang=%s", websocket.query_params.get("lang", "ko"))
        # ... (생략)
