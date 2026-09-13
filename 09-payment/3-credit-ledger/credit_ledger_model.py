# 출처: 팬 플랫폼 서비스 (2026.07) — 크레딧 원장: 모든 증감을 1행씩, 행마다 변동 후 잔액 · 참조 유형 · 참조 ID. 구매 행은 지급 시점의 수량 · 금액 · 통화를 스냅샷
# 유저 행의 잔액 컬럼은 캐시이고, 원장 합산과 항상 일치해야 한다.

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, Text

from app.core.database.base import Base, now_kst


class CreditLedger(Base):
    """크레딧 거래 내역 원장. 모든 변동을 1행씩 기록.

    tb_user.credit 은 잔액 캐시이며 이 원장 합산과 일치해야 한다.
    """

    __tablename__ = "tb_credit_ledger"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(Integer, ForeignKey("tb_user.id"), nullable=False, index=True)
    type = Column(String(20), nullable=False)            # purchase | spend | gift | refund
    amount = Column(Integer, nullable=False)             # 항상 양수. 방향은 type 이 말한다
    balance_after = Column(Integer, nullable=False)      # 이 행 직후 잔액 — 집계 없이 시점 잔액을 읽는다
    # ref_type 은 20자가 상한이다. 넘기면 MySQL STRICT 모드에서 INSERT 가
    # 1406(Data too long) 으로 터지는데, 호출부가 대개 try/except 안이라
    # 조용히 삼켜진다 — 실제로 환불 3종이 21~23자여서 실패 시 크레딧이
    # 환불되지 않고 실패 알림까지 건너뛰던 사고가 있었다 (…_refund → …_ref 로 단축).
    # 새 값은 반드시 20자 이내로 짓는다.
    ref_type = Column(String(20), nullable=True)         # credit_product | voice_minutes | content_generate | ...
    ref_id = Column(Integer, nullable=True)
    description = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=now_kst)


class CreditPurchase(Base):
    """크레딧 구매 내역. 스토어 소모성 상품으로 크레딧 충전 시 1행 기록."""

    __tablename__ = "tb_credit_purchase"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(Integer, ForeignKey("tb_user.id"), nullable=False, index=True)
    credit_product_id = Column(Integer, ForeignKey("tb_credit.id"), nullable=False, index=True)
    provider = Column(String(20), nullable=False)               # 'google_play' | 'apple_appstore'
    product_id = Column(String(100), nullable=False)            # 스토어 SKU
    order_id = Column(String(200), nullable=False, unique=True) # 스토어 주문 ID — 중복 지급 방지 키
    purchase_token = Column(Text, nullable=False)               # 스토어 검증 토큰 (애플은 transaction_id)
    credit_amount = Column(Integer, nullable=False)             # 지급 시점 크레딧 수량 (상품 설정이 바뀌어도 이 행은 그대로)
    amount = Column(Numeric(12, 2), nullable=True)              # 결제 금액 — 유저 지역 통화 기준 정가 스냅샷
    currency = Column(String(3), nullable=True)                 # ISO 4217
    status = Column(String(20), nullable=False, default="completed")  # 'completed' | 'refunded'
    consumed = Column(Boolean, nullable=False, default=False)   # 구글 consume 성공 여부. 애플은 클라이언트가 finish → True
    purchased_at = Column(DateTime, nullable=False)             # 스토어 측 구매 시각
    created_at = Column(DateTime, default=now_kst)


class SubscriptionRenewal(Base):
    """구독 시작 · 갱신 이력. 검증 및 서버 알림 갱신 때마다 1행 INSERT. 같은 (유저, 상품, 만료일) 이 있으면 재전송으로 본다."""

    __tablename__ = "tb_subscription_renewal"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(Integer, ForeignKey("tb_user.id"), nullable=False, index=True)
    user_subs_id = Column(Integer, ForeignKey("tb_user_subs.id"), nullable=True, index=True)
    subscription_id = Column(Integer, ForeignKey("tb_subscription.id"), nullable=True, index=True)
    purchase_token = Column(Text, nullable=True)
    provider = Column(String(50), nullable=True)
    end_date = Column(DateTime, nullable=True)
    amount = Column(Numeric(12, 2), nullable=True)   # 갱신 시점 정가 스냅샷
    currency = Column(String(3), nullable=True)
    created_at = Column(DateTime, default=now_kst)
