# 출처: 풀스택 베이스 템플릿 (2026.04~, 현재 표준) — WebSocket 전용 프로바이더와 데코레이터. HTTP 쪽(core/provider/http)과 같은 모양을 소켓에 맞게 옮겼다
# 원본은 core/provider/web_socket/ 아래 endpoint.py · login.py · service.py 세 파일이다.
from functools import wraps

from fastapi import Depends, HTTPException, WebSocket

from app.core.database.base import get_session
from app.module.auth.auth_token import AuthToken


# ---------------------------------------------------------------
# service.py — 소켓 하나가 쓰는 서비스를 지연 생성한다.
# ---------------------------------------------------------------
class WebSocketProvider:
    def __init__(self, websocket: WebSocket, db):
        self.websocket = websocket
        self.db = db
        self._redis_service = None
        self._gpt_service = None
        self._web_socket_service = None

    @property
    def redis_service(self):
        if not self._redis_service:
            from app.module.infra.redis.redis_service import RedisService
            self._redis_service = RedisService()
        return self._redis_service

    @property
    def gpt_service(self):
        if not self._gpt_service:
            from app.module.infra.gpt.gpt_service import GPTService
            self._gpt_service = GPTService(self.redis_service)
        return self._gpt_service

    @property
    def web_socket_service(self):
        if not self._web_socket_service:
            from app.module.web_socket.web_socket_service import web_socket_service
            self._web_socket_service = web_socket_service
        return self._web_socket_service


async def get_provider_web_socket(websocket: WebSocket, db=Depends(get_session)):
    return WebSocketProvider(websocket, db)


# ---------------------------------------------------------------
# endpoint.py — 라우터 함수가 (p, websocket) 두 인자만 받게 한다.
# ---------------------------------------------------------------
def with_provider_web_socket(func):
    """WebSocket 요청에 Depends(get_provider_web_socket)를 자동 주입하는 데코레이터"""
    async def wrapper(
        websocket: WebSocket,
        p: WebSocketProvider = Depends(get_provider_web_socket),
    ):
        return await func(p, websocket)
    return wrapper


# ---------------------------------------------------------------
# login.py — 핸드셰이크 쿠키로 인증하고 websocket 객체에 사용자 정보를 심는다.
# ---------------------------------------------------------------
def with_login_web_socket(type: str = "user"):
    """
    WebSocket용 로그인 필수 (기본: user)
    admin API에서는 with_login_web_socket("admin") 사용
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(p, websocket: WebSocket, *args, **kwargs):
            token_util = AuthToken()
            try:
                user_id, auth_type = await token_util.get_token_info_ws(websocket, type)
                websocket.user_id = user_id
                websocket.auth_type = auth_type
            except HTTPException as e:
                raise e
            return await func(p, websocket, *args, **kwargs)
        return wrapper
    return decorator


def without_login_web_socket(func):
    """
    로그인이 필요 없는 WebSocket 연결용 데코레이터
    """
    @wraps(func)
    async def wrapper(p, websocket: WebSocket, *args, **kwargs):
        # 인증 없이 기본값 주입
        websocket.user_id = "guest_user"
        websocket.auth_type = "guest"
        return await func(p, websocket, *args, **kwargs)
    return wrapper


# ---------------------------------------------------------------
# 사용 예 (module/web_socket/web_socket_router.py)
# ---------------------------------------------------------------
# router = APIRouter()
#
# @router.websocket("/")
# @with_provider_web_socket
# @without_login_web_socket
# async def chat_ws(p: WebSocketProvider, websocket: WebSocket):
#     await p.web_socket_service.init_state(websocket)
