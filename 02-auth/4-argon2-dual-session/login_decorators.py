# 출처: AI 캐릭터 대화 서비스 (2025.11) — 로그인 종류를 인자로 받는 데코레이터. HTTP 용과 WebSocket 용이 같은 토큰 클래스를 쓴다. Argon2 해시는 passlib 로
from functools import wraps

from fastapi import HTTPException, WebSocket
from passlib.context import CryptContext

from app.module.auth.auth_token import AuthToken

# ---- auth_service.py ---- 비밀번호 해시는 Argon2. HMAC-SHA256 에서 바뀐 지점.
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# ---- core/provider/login.py ----
def with_login(type: str = "user"):
    """
    로그인 필수 (기본: user)
    admin API에서는 with_login("admin") 사용
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(p, *args, **kwargs):
            token_util = AuthToken()
            try:
                user_id, auth_type = await token_util.get_token_info(p.request, type)
                p.request.user_id = user_id
                p.request.auth_type = auth_type
            except HTTPException as e:
                raise e
            return await func(p, *args, **kwargs)
        return wrapper
    return decorator


def with_login_ws(type: str = "user"):
    """
    WebSocket용 로그인 필수 (기본: user)
    핸드셰이크 쿠키를 검증하고 websocket 객체에 사용자 정보를 심는다.
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


# ---- 사용 예 ----
# @router.get("/me")
# @with_provider
# @with_login()            # 사용자 세션(user_ 쿠키)만 통과
# async def get_me(p): ...
#
# @router.get("/admin/users")
# @with_provider
# @with_login("admin")     # 관리자 세션(admin_ 쿠키)만 통과
# async def list_users(p): ...
