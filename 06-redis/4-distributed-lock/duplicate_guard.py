# 출처: 팬 플랫폼 서비스 (2026.05~) — 다중 워커에서 같은 일이 두 번 돌지 않게 막는 Redis 키 잠금 두 가지
# (1) 1분마다 도는 Celery 배치: SET NX + TTL 로 한 회차에 워커 하나만 진입  (2) 앱 폴링이 부르는 이미지 렌더: 같은 조합이 굽는 중이면 큐에 넣지 않음
import asyncio
import logging

from app.core.database.redis import redis_conn
from app.worker.celery import celery_app

logger = logging.getLogger(__name__)

_CHAT_KO_LOCK_KEY = "lock:sweep_chat_ko"
_CHAT_KO_LOCK_TTL = 600          # 한 회차가 이보다 오래 걸리면 다음 회차가 이어받는다
_CHAT_KO_BATCH = 200             # 한 회차에 처리할 메시지 수 (과거분도 이 속도로 소급된다)


# =====================================================
# (1) Celery Beat 배치 — 회차 겹침 방지
# =====================================================
@celery_app.task(name="app.worker.translation_task.sweep_chat_ko", ignore_result=True)
def sweep_chat_ko():
    """미번역 대화 메시지를 주워 한국어로 채운다. beat 가 1분마다 호출."""
    asyncio.run(_sweep_chat_ko())


async def _sweep_chat_ko() -> None:
    from sqlalchemy import desc, select

    from app.core.database.base import task_session
    from app.module.mate.mate import MateMessage, MateMessageKo

    # 회차가 겹치면 같은 메시지를 두 번 번역하게 된다(비용 낭비). 유니크 제약이 최종 방어선이지만
    # 호출 자체를 막는 게 낫다.
    # 전역 redis_client 는 이벤트 루프에 묶여 두 번째 태스크부터 실패한다 → redis_conn() 사용.
    async with redis_conn() as rc:
        try:
            # NX: 키가 없을 때만 성공. 이미 있으면 None → 다른 워커가 돌고 있다는 뜻
            acquired = await rc.set(_CHAT_KO_LOCK_KEY, "1", ex=_CHAT_KO_LOCK_TTL, nx=True)
        except Exception as e:
            logger.warning("[sweep_chat_ko] 락 획득 실패, 이번 회차 건너뜀: %s", e)
            return
        if not acquired:
            return

    try:
        async with task_session() as db:
            # 번역 행이 없는 메시지를 최신순으로 — 최근 대화가 먼저 보이고 과거분은 뒤로 밀려 소급된다
            rows = (
                await db.execute(
                    select(MateMessage.id, MateMessage.thread_id, MateMessage.role, MateMessage.content)
                    .outerjoin(MateMessageKo, MateMessageKo.message_id == MateMessage.id)
                    .where(MateMessageKo.id.is_(None))
                    .order_by(desc(MateMessage.id))
                    .limit(_CHAT_KO_BATCH)
                )
            ).all()
            if not rows:
                return

            # ... (생략) 번역 호출 → MateMessageKo 행 저장
    finally:
        # 락은 명시적으로 풀지 않는다 — TTL 로 자동 해제. 워커가 죽어도 10분 뒤 다음 회차가 이어받는다.
        pass


# =====================================================
# (2) 요청 경로 — 같은 렌더가 큐에 쌓이는 것 방지
# =====================================================
class PromoService:
    def __init__(self, promo_repo):
        self.promo_repo = promo_repo

    async def render_once_guard(
        self,
        promo_id: int,
        language: str,
        soulmate_id: int,
        user_id: int | None = None,
    ) -> None:
        """유저 조회에서 부르는 경로 — **같은 조합이 이미 굽는 중이면 넣지 않는다.**

        앱은 이미지가 null 인 동안 몇 초마다 목록을 다시 묻는다. 잠금이 없으면
        폴링 한 번마다 같은 렌더가 큐에 쌓여, 굽는 동안 같은 그림을 수십 번 굽는다.
        Redis 키 하나로 막고 TTL 로 자동 해제한다 (렌더가 죽어도 다시 시도된다).
        """
        key = f"promo:render:{promo_id}:{language}:{soulmate_id}:{user_id or 0}"
        try:
            from app.module.infra.redis.redis_service import RedisService

            redis_service = RedisService()
            if await redis_service.exists(key):
                return
            # 렌더 한 장은 보통 1~3초다. 넉넉히 3분 — 실패해도 그 뒤엔 다시 시도된다.
            await redis_service.set(key, "1", expire=180)
        except Exception as e:
            # Redis 가 죽어 있으면 잠금 없이 진행한다 (중복 렌더 < 자료가 안 뜨는 것)
            logger.warning("[promo] 렌더 잠금 실패 — 잠금 없이 진행 %s: %s", key, e)

        self.dispatch_render(promo_id, [language], user_id, [soulmate_id])

    def dispatch_render(self, promo_id: int, languages: list[str], user_id: int | None, target_ids: list[int]):
        # ... (생략) Celery 렌더 태스크 delay
        pass
