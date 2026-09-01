# 출처: 풀스택 베이스 템플릿 (2026.04~, 현재 표준) — 도메인 하나 = 모델 · 저장소 · 서비스 · 라우터 4파일 한 폴더(module/user/). 여기서는 네 파일을 순서대로 한 파일에 모았다
from fastapi import APIRouter
from sqlalchemy import Boolean, Column, DateTime, Integer, String, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database.base import Base, now_kst
from app.core.provider.http.endpoint import with_provider
from app.core.provider.http.login import with_login
from app.core.provider.http.service import ServiceProvider
from app.core.utils.response import success


# ---------------------------------------------------------------
# user.py — SQLAlchemy 모델. 테이블 이름은 tb_ 접두사로 통일.
# ---------------------------------------------------------------
class User(Base):
    __tablename__ = "tb_users"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    email = Column(String(100), unique=True, nullable=False)
    password = Column(String(255), nullable=True)
    name = Column(String(20), nullable=False)
    profile_image = Column(String(200), nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now_kst)
    last_login_at = Column(DateTime(timezone=True))


# ---------------------------------------------------------------
# user_repository.py — DB 쿼리만. 비동기 세션(aiomysql)을 주입받는다.
# ---------------------------------------------------------------
class UserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_user_by_id(self, id: int):
        result = await self.db.execute(select(User).where(User.id == id))
        return result.scalar_one_or_none()

    async def get_user_by_email(self, email: str):
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def create_user(self, email, nickname, hashed_password):
        user = User(
            email=email,
            name=nickname,
            password=hashed_password,
            last_login_at=now_kst(),
        )
        self.db.add(user)
        await self.db.commit()

    async def get_or_create_user(self, email: str, name: str, picture: str) -> User | None:
        """소셜 로그인용 — 있으면 마지막 로그인 시각만 갱신, 없으면 생성."""
        result = await self.db.execute(select(User).filter(User.email == email))
        user = result.unique().scalar_one_or_none()

        if user:
            user.last_login_at = now_kst()
        else:
            user = User(
                email=email,
                name=name,
                profile_image=picture,
                created_at=now_kst(),
                last_login_at=now_kst(),
            )
            self.db.add(user)

        await self.db.commit()
        await self.db.refresh(user)
        return user


# ---------------------------------------------------------------
# user_service.py — 비즈니스 로직. 저장소를 생성자로 받는다(의존성 주입).
# ---------------------------------------------------------------
class UserService:
    def __init__(self, user_repo: UserRepository):
        self.user_repo = user_repo

    async def get_user_by_id(self, user_id: int):
        return await self.user_repo.get_user_by_id(user_id)

    async def get_me(self, request):
        user_id = request.user_id  # @with_login 이 심어 준 값
        return await self.user_repo.get_user_by_id(user_id)


# ---------------------------------------------------------------
# user_router.py — HTTP 엔드포인트. 데코레이터 두 개로 주입 · 인증이 끝난다.
# ---------------------------------------------------------------
router = APIRouter()


@router.get("/me")
@with_provider
@with_login()
async def get_me(p: ServiceProvider):
    return success(await p.user_service.get_me(p.request))


# ---------------------------------------------------------------
# module/__init__.py — 새 도메인은 여기서 모델 import + 라우터 등록 두 줄만 추가한다.
# ---------------------------------------------------------------
# from app.module.user.user import User            # 모델 등록 (관계 인식용)
# from app.module.user import user_router          # 라우터 등록
#
# def setup_routers(app):
#     app.include_router(user_router.router, prefix="/api/user")
