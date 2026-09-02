# 출처: AI 아바타 모의 면접 서비스 (2025.05) — 리프레시 토큰을 (사용자, 기기) 한 쌍마다 한 행으로 저장하는 테이블과 CRUD
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Session

from app.database import Base


# ---- models/data.py ----
# 유저의 리프레시 토큰 및 디바이스 정보 저장 테이블
class userToken(Base):
    __tablename__ = "tb_user_token"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(Integer, ForeignKey("tb_user.id"), nullable=False)
    refresh_token = Column(Text)
    device_info = Column(String(255), nullable=True)  # 예: 브라우저 정보 또는 UUID
    created_at = Column(DateTime, default=func.now())


# ---- crud/user_crud.py ----
def save_refresh_token(db: Session, user_id: int, token: str, device_info: str):
    """같은 기기에서 다시 로그인하면 행을 덧쓰고, 새 기기면 행을 추가한다."""
    db_token = (
        db.query(userToken)
        .filter(userToken.user_id == user_id, userToken.device_info == device_info)
        .first()
    )

    if db_token:
        db_token.refresh_token = token
        db_token.created_at = datetime.now(ZoneInfo("Asia/Seoul"))
    else:
        db_token = userToken(
            user_id=user_id,
            refresh_token=token,
            device_info=device_info,
            created_at=datetime.now(ZoneInfo("Asia/Seoul")),
        )
        db.add(db_token)
    db.commit()


def get_refresh_token_by_user(db: Session, user_id: int, device_info: str):
    return (
        db.query(userToken)
        .filter(userToken.user_id == user_id, userToken.device_info == device_info)
        .first()
    )


def delete_refresh_token(db: Session, user_id: int, device_info: str):
    """로그아웃 — 이 기기 행만 지운다. 다른 기기 세션은 그대로 살아 있다."""
    db.query(userToken).filter(
        userToken.user_id == user_id, userToken.device_info == device_info
    ).delete()
    db.commit()
