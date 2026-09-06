# 출처: 팬 플랫폼 서비스 (2026.05~) — 연동 · 워커 · WebSocket 별 전용 로그 파일. 로거 이름으로 라우팅하고 루트로 전파하지 않는다. 파일을 못 열면 콘솔로 폴백
import logging
import os

from app.core.logging.context import get_request_id, get_user_id

LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [req:%(request_id)s] [user:%(user_id)s] [%(name)s] %(message)s"

# 운영 서버 경로 (없거나 권한 없으면 콘솔 fallback)
FCM_LOG_PATH = "/var/log/fcm/fcm.log"
#: OpenAI 일반 호출 — 채팅 · 웹검색 · 번역 · STT. infra 패키지 전체가 여기로 온다
OPENAI_CHAT_LOG_PATH = "/var/log/openai/openai_chat.log"
#: Gemini 일반 호출. 전용 모듈이 없어 이름으로 잡는다 — 호출부에서 getLogger("app.gemini") 로 찍으면 이 파일로 간다
GEMINI_CHAT_LOG_PATH = "/var/log/gemini/gemini_chat.log"
CELERY_IMAGE_LOG_PATH = "/var/log/celery/celery_image.log"
#: 제작툴 그림 · 영상 · 음원 생성. 한 번에 수십 장을 걸어 두는 작업이라 콘솔에 섞이면 못 쫓아간다 — 따로 뺀다
CELERY_SCEN_MEDIA_LOG_PATH = "/var/log/celery/celery_scen_media.log"
BROADCAST_LOG_PATH = "/var/log/ws/ws_broadcast.log"
# ... (생략) 같은 방식으로 13종


class ContextFilter(logging.Filter):
    """모든 로그 record 에 request_id, user_id 를 주입."""

    def filter(self, record):
        record.request_id = get_request_id()
        record.user_id = get_user_id()
        return True


def _make_file_handler(path: str, formatter: logging.Formatter) -> logging.Handler | None:
    """파일 핸들러 생성. 디렉토리 없거나 권한 없으면 None 반환 (콘솔로 fallback)."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(formatter)
        handler.addFilter(ContextFilter())
        return handler
    except (OSError, PermissionError) as e:
        print(f"[setup_logging] {path} 핸들러 생성 실패 — 콘솔 fallback: {e}")
        return None


def _attach_dedicated_logger(name: str, handler: logging.Handler | None) -> None:
    """지정 logger를 dedicated 파일로만 보내고 root로 전파하지 않음.

    handler 가 None 이면 아무것도 안 함 → root 로 전파되어 콘솔에 출력 (fallback).
    """
    if handler is None:
        return
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def setup_logging() -> None:
    formatter = logging.Formatter(LOG_FORMAT)

    # 루트: 콘솔 하나. 전용 파일에 걸리지 않는 모든 로그가 여기로 온다
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.addFilter(ContextFilter())

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.propagate = True

    # 모듈별 dedicated 파일 로거 — 모듈 경로가 그대로 로거 이름
    fcm_handler = _make_file_handler(FCM_LOG_PATH, formatter)
    _attach_dedicated_logger("app.module.infra.fcm.fcm_service", fcm_handler)

    # 패키지 이름에 붙인다 — 하위 로거가 여기로 전파돼 걸리므로
    # 모듈을 하나씩 나열하지 않아도 되고, 파일이 늘어도 자동으로 따라온다.
    openai_chat_handler = _make_file_handler(OPENAI_CHAT_LOG_PATH, formatter)
    _attach_dedicated_logger("app.module.infra.gpt", openai_chat_handler)

    # 모듈이 흩어져 있으면 임의 이름으로 잡는다 — 호출부가 그 이름으로 로거를 받는다
    gemini_chat_handler = _make_file_handler(GEMINI_CHAT_LOG_PATH, formatter)
    _attach_dedicated_logger("app.gemini", gemini_chat_handler)

    # Celery 태스크별 dedicated 파일 로거
    celery_image_handler = _make_file_handler(CELERY_IMAGE_LOG_PATH, formatter)
    _attach_dedicated_logger("app.worker.image_task", celery_image_handler)

    celery_scen_media_handler = _make_file_handler(CELERY_SCEN_MEDIA_LOG_PATH, formatter)
    _attach_dedicated_logger("app.worker.scen_media_task", celery_scen_media_handler)

    # WebSocket 방송 — 프레임 단위 로그가 많아 웹 로그와 섞이지 않게
    broadcast_handler = _make_file_handler(BROADCAST_LOG_PATH, formatter)
    _attach_dedicated_logger("app.broadcast", broadcast_handler)

    # ... (생략) 나머지 전용 로거도 같은 두 줄 반복
