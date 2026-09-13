# 출처: 팬 플랫폼 서비스 (2026.07) — 원장 기록 저장소: 지급 · 차감 모두 1행, 차감은 조건부 UPDATE 한 방(잔액 ≥ 금액)으로 직렬화, 세션 정산은 행 잠금
# 검사와 차감이 두 문장이면 그 사이에 다른 요청이 끼어 음수 잔액이 난다. 조건부 UPDATE 의 영향 행 수로 성공 여부를 판정한다.

from sqlalchemy import func, select, update

from app.module.billing.billing import CreditLedger
from app.module.user.user import User


class BillingRepository:
    def __init__(self, db):
        self.db = db

    # ── 지급 ─────────────────────────────────────────────────────────
    async def grant_credits(self, user: User, amount: int, ref_type: str, ref_id: int, description: str) -> int:
        """크레딧 지급 (commit 없음 — 호출자가 commit). 구독 혜택 · 환불 · 보상 등 범용 지급용."""
        user.credit += amount
        self.db.add(CreditLedger(
            user_id=user.id, type="gift", amount=amount, balance_after=user.credit,
            ref_type=ref_type, ref_id=ref_id, description=description,
        ))
        return user.credit

    async def add_credits(self, user: User, amount: int, credit_product_id: int) -> int:
        """구매 지급 + 원장 기록 + commit. 구매 행(flush 상태)과 함께 확정된다."""
        user.credit += amount
        self.db.add(CreditLedger(
            user_id=user.id, type="purchase", amount=amount, balance_after=user.credit,
            ref_type="credit_product", ref_id=credit_product_id, description="크레딧 구매",
        ))
        await self.db.commit()
        return user.credit

    # ── 차감 ─────────────────────────────────────────────────────────
    async def _atomic_deduct(self, user: User, amount: int) -> bool:
        """크레딧을 원자적으로 차감. 성공 True / 잔액 부족 · 경합 패배 False.

        `UPDATE ... WHERE credit >= amount` 한 방으로 처리해, 검사와 차감 사이에
        다른 요청이 끼어들어도 음수 잔액이 생기지 않는다 (TOCTOU 방지).
        """
        result = await self.db.execute(
            update(User)
            .where(User.id == user.id, User.credit >= amount)
            .values(credit=User.credit - amount)
        )
        if result.rowcount == 0:
            return False
        # 동시 차감이 있었을 수 있으므로 DB 실제 잔액을 다시 읽어 ORM · ledger 를 맞춘다
        await self.db.refresh(user)
        return True

    async def spend_credits(self, user: User, amount: int, ref_type: str, ref_id: int, description: str) -> int | None:
        """범용 크레딧 원자 차감 + 원장 기록 (commit 없음). 부족 · 경합 시 None."""
        if not await self._atomic_deduct(user, amount):
            return None
        self.db.add(CreditLedger(
            user_id=user.id, type="spend", amount=amount, balance_after=user.credit,
            ref_type=ref_type, ref_id=ref_id, description=description,
        ))
        return user.credit

    # ── 행 잠금 ──────────────────────────────────────────────────────
    async def lock_user(self, user_id: int) -> None:
        """user 행에 배타적 락 (SELECT ... FOR UPDATE). commit 까지 유지된다.
        같은 유저의 음성 세션 시작 동시 요청을 직렬화해 이중 정산을 막는다 —
        차감 금액이 세션 길이에 따라 정해지는 경로라 조건부 UPDATE 한 방으로는 안 된다."""
        await self.db.execute(select(User.id).where(User.id == user_id).with_for_update())

    # ── 조회 ─────────────────────────────────────────────────────────
    async def get_credit_totals(self, user_id: int) -> dict:
        """유저의 크레딧 누적 사용 · 적립 합계.

        목록 조회는 limit 이 걸려 있어 화면에서 합산하면 실제 총액과 어긋난다.
        전체 원장을 DB 에서 SUM 해 정확한 값을 낸다. type='spend' 는 사용, 그 외(purchase/gift/refund)는 적립.
        """
        result = await self.db.execute(
            select(
                func.coalesce(func.sum(CreditLedger.amount).filter(CreditLedger.type == "spend"), 0),
                func.coalesce(func.sum(CreditLedger.amount).filter(CreditLedger.type != "spend"), 0),
            ).where(CreditLedger.user_id == user_id)
        )
        spent, earned = result.one()
        return {"spent": int(spent), "earned": int(earned)}
