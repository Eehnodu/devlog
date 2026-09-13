# 출처: 팬 플랫폼 서비스 (2026.08) — 참조 유형 컬럼(20자) 길이 초과로 환불 INSERT 가 조용히 실패한 사고 이후: 값 축약, 컬럼 정의에 사고 기록, 환불 실패는 삼키지 않고 ERROR
# MySQL STRICT 모드에서 1406(Data too long) 이 났지만 호출부가 try/except 안이어서 삼켜졌다. 환불 3종이 21~23자였다.

import logging

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from app.core.database.base import Base, now_kst

logger = logging.getLogger(__name__)


# ── 컬럼 정의 — 제약과 사고를 같은 자리에 적어 다음 사람이 값을 지을 때 보게 한다 ──
class CreditLedger(Base):
    __tablename__ = "tb_credit_ledger"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(Integer, ForeignKey("tb_user.id"), nullable=False, index=True)
    type = Column(String(20), nullable=False)
    amount = Column(Integer, nullable=False)
    balance_after = Column(Integer, nullable=False)
    # ref_type 은 20자가 상한이다. 넘기면 MySQL STRICT 모드에서 INSERT 가
    # 1406(Data too long) 으로 터지는데, 호출부가 대개 try/except 안이라
    # 조용히 삼켜진다 — 실제로 환불 3종이 21~23자여서 실패 시 크레딧이
    # 환불되지 않고 실패 알림까지 건너뛰던 사고가 있었다 (…_refund → …_ref 로 단축).
    # 새 값은 반드시 20자 이내로 짓는다. 'content_daily_reward' 가 딱 20자다.
    ref_type = Column(String(20), nullable=True)
    ref_id = Column(Integer, nullable=True)
    description = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=now_kst)


# ── 워커 3종의 환불 값 — 사고 전 'content_generate_refund'(23자) → 'content_generate_ref'(20자) ──
CONTENT_REFUND_REF = "content_generate_ref"
IMAGE_REFUND_REF = "image_generate_ref"
VIDEO_REFUND_REF = "video_generate_ref"


async def refund_after_failure(db, billing_repo, user, charged_amount: int, target_id: int, ref: str, why: str) -> bool:
    """생성 최종 실패 시 크레딧 복구. 성공 True.

    사고 전에는 이 블록이 알림 발송과 같은 try 안에 있어, 환불 INSERT 실패가
    '알림 오류' 한 줄로 묻혔다. 지금은 환불만 따로 감싸고, 실패하면 ERROR 로 남긴다 —
    운영 로그에서 환불 누락을 검색할 수 있어야 한다.
    """
    if not user or charged_amount <= 0:
        return False
    try:
        await billing_repo.grant_credits(
            user=user, amount=charged_amount, ref_type=ref, ref_id=target_id, description=why,
        )
        await db.commit()  # 환불을 먼저 확정 — 이후 알림이 실패해도 환불은 유지
        logger.info("[refund] ok user=%s target=%s amount=%s", user.id, target_id, charged_amount)
        return True
    except Exception as e:
        await db.rollback()
        logger.error("[refund] FAILED user=%s target=%s amount=%s ref=%s: %s", user.id, target_id, charged_amount, ref, e)
        return False
