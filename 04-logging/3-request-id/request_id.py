# 출처: 풀스택 베이스 템플릿 (2026.04~) — HTTP · WebSocket 요청마다 UUID 를 만들어 컨텍스트에 넣고, HTTP 응답 헤더 x-request-id 로 돌려주는 ASGI 미들웨어
import uuid
from fastapi import FastAPI

from app.core.logging.context import set_request_id, get_request_id


class RequestIdMiddleware:
    # BaseHTTPMiddleware 가 아니라 순수 ASGI 로 쓴다 — WebSocket scope 도 지나가야 하기 때문
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            set_request_id(str(uuid.uuid4()))

        if scope["type"] == "http":
            async def send_with_header(message):
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers", []))
                    headers.append((b"x-request-id", get_request_id().encode()))
                    message = {**message, "headers": headers}
                await send(message)

            await self.app(scope, receive, send_with_header)
        else:
            await self.app(scope, receive, send)


def setup_request_id(app: FastAPI):
    app.add_middleware(RequestIdMiddleware)
