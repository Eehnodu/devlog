# 출처: 풀스택 베이스 템플릿 (2026.04~) — 로깅 필터가 모든 줄에 요청 ID 를 붙인다. 핸들러는 루트에 하나, Uvicorn 로거는 핸들러를 비우고 루트로 전파
import logging

from app.core.logging.context import get_request_id

LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [req:%(request_id)s] [%(name)s] %(message)s"


class RequestIdFilter(logging.Filter):
    # 포맷에 %(request_id)s 가 있으므로 모든 record 에 값을 채워 넣는다
    def filter(self, record):
        record.request_id = get_request_id()
        return True


def setup_logging() -> None:
    formatter = logging.Formatter(LOG_FORMAT)

    # 앱은 표준 출력으로만 쓴다. 파일로 남기는 일은 systemd 유닛(StandardOutput=append:)이 맡는다
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.addFilter(RequestIdFilter())

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Uvicorn 로거는 자기 핸들러를 버리고 루트로 전파 — 접근 로그 줄에도 같은 요청 ID 가 붙는다
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.propagate = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
