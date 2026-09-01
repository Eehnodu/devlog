# 출처: 풀스택 베이스 템플릿 (2026.04~, 현재 표준) — 요청마다 만들어지는 ServiceProvider(지연 생성)와 라우터에 그것을 주입하는 @with_provider / @with_login 데코레이터
# 원본은 core/provider/http/ 아래 endpoint.py · login.py · service.py 세 파일이다. 여기서는 한 파일에 모았다.
from functools import wraps

from fastapi import Depends, HTTPException, Request

from app.core.database.base import get_session
from app.module.auth.auth_token import AuthToken


# ---------------------------------------------------------------
# service.py — 요청 하나가 쓰는 저장소 · 서비스를 한 객체에 모아 둔다.
# 프로퍼티에 처음 접근할 때만 만들기 때문에(lazy) 안 쓰는 서비스는 비용이 없다.
# ---------------------------------------------------------------
class ServiceProvider:
    def __init__(self, request: Request, db):
        self.request = request
        self.db = db
        self._redis_service = None
        self._user_repo = None
        self._admin_repo = None
        self._user_service = None
        self._auth_service = None
        self._gpt_service = None

    @property
    def user_repo(self):
        if not self._user_repo:
            from app.module.user.user_repository import UserRepository
            self._user_repo = UserRepository(self.db)
        return self._user_repo

    @property
    def admin_repo(self):
        if not self._admin_repo:
            from app.module.admin.admin_repository import AdminRepository
            self._admin_repo = AdminRepository(self.db)
        return self._admin_repo

    @property
    def user_service(self):
        if not self._user_service:
            from app.module.user.user_service import UserService
            self._user_service = UserService(self.user_repo)
        return self._user_service

    @property
    def auth_service(self):
        if not self._auth_service:
            from app.module.auth.auth_service import AuthService
            self._auth_service = AuthService(self.user_repo, self.admin_repo)
        return self._auth_service

    @property
    def redis_service(self):
        if not self._redis_service:
            from app.module.infra.redis.redis_service import RedisService
            self._redis_service = RedisService()
        return self._redis_service

    @property
    def gpt_service(self):
        # infra 서비스도 같은 방식으로 등록한다. 외부 API 래퍼라 DB 대신 다른 서비스를 받는다.
        if not self._gpt_service:
            from app.module.infra.gpt.gpt_service import GPTService
            self._gpt_service = GPTService(self.redis_service)
        return self._gpt_service


async def get_provider(request: Request, db=Depends(get_session)):
    return ServiceProvider(request, db)


# ---------------------------------------------------------------
# endpoint.py — 라우터 함수가 p: ServiceProvider 하나만 받게 한다.
# ---------------------------------------------------------------
def with_provider(func):
    """라우터에 Depends(get_provider)를 자동 주입하는 데코레이터"""
    async def wrapper(p: ServiceProvider = Depends(get_provider)):
        return await func(p)
    return wrapper


# ---------------------------------------------------------------
# login.py — 로그인 종류(user / admin)를 확인하고 요청 객체에 사용자 ID 를 심는다.
# ---------------------------------------------------------------
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


def without_login(func):
    """
    로그인이 필요 없는 API용 데코레이터
    (기본 user_id, auth_type 세팅)
    """
    @wraps(func)
    async def wrapper(p, *args, **kwargs):
        request = p.request
        request.user_id = getattr(request, "user_id", "guest_user")
        request.auth_type = getattr(request, "auth_type", "guest")
        return await func(p, *args, **kwargs)
    return wrapper
