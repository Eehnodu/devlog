# 출처: AI 글쓰기 검토 서비스 (2025.09) — 요청 한 건마다 한 줄, 상태코드로 레벨을 정하는 요청/응답 로깅 미들웨어
# 당시 파일이 남아 있지 않아 운영 규칙(5xx ERROR · 4xx WARNING · 3xx INFO REDIRECT)대로 다시 적었다.
import logging
import time

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("app.request")


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # 예외로 끝난 요청은 스택까지 남기고 다시 던진다 — 응답은 전역 예외 핸들러가 만든다
            elapsed = (time.perf_counter() - started) * 1000
            logger.exception("%s %s -> 500 (%.0fms)", request.method, request.url.path, elapsed)
            raise

        elapsed = (time.perf_counter() - started) * 1000
        status = response.status_code
        line = "%s %s -> %s (%.0fms)"
        args = (request.method, request.url.path, status, elapsed)

        # 상태코드가 곧 레벨이다 — 파일에서 ERROR 만 걸러도 서버 오류만 남는다
        if status >= 500:
            logger.error(line, *args)
        elif status >= 400:
            logger.warning(line, *args)
        elif status >= 300:
            logger.info(line + " REDIRECT", *args)
        else:
            logger.info(line, *args)
        return response


def setup_request_log(app: FastAPI) -> None:
    app.add_middleware(RequestLogMiddleware)
