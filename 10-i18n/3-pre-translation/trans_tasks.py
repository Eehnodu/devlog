# 출처: 전시관 AI 안내 서비스 (2026.03~04) — 등록 시 Celery 태스크가 언어를 묶음으로 나눠 번역 · 저장, 빈 결과만 재시도, 끝나면 Redis 캐시 무효화. 누락분은 매일 자정 배치가 보충
# 관리자 화면은 등록 즉시 응답하고, 번역은 워커가 뒤에서 채운다. 진행은 관리자 알림으로 알린다.

import asyncio
import logging

from celery.schedules import crontab

from app.worker.celery import celery_app

logger = logging.getLogger(__name__)

CHUNK_SIZE = 10     # 한 호출에 넣는 언어 수 — 응답이 길어지면 스키마 위반이 늘어 10개씩 끊는다
CHUNK_DELAY = 2     # 묶음 사이 대기(초) — 레이트리밋 완화
POST_DELAY = 1


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_artwork_trans(self, artwork_id: int, title: str, description: str, admin_id: int, only_langs: list[str] | None = None):
    """등록 · 수정 시 호출. only_langs 가 있으면 그 언어만(누락분 보충 · 단건 재번역)."""
    try:
        return asyncio.run(_artwork_trans(artwork_id, title, description, admin_id, only_langs))
    except Exception as exc:
        # 태스크 단위 재시도 — _generate_json 이 예외를 올려야 여기까지 온다
        raise self.retry(exc=exc)


async def _artwork_trans(artwork_id: int, title: str, description: str, admin_id: int, only_langs: list[str] | None = None) -> list[dict]:
    from app.core.database.base import task_session
    from app.core.utils.cache import invalidate_agent_content
    from app.module.artwork.artwork_repository import ArtworkRepository
    from app.module.infra.gemini.gemini_trans_service import GeminiTransService, MODAL_LANG_NAMES
    from app.module.infra.redis.redis_service import RedisService

    async with task_session() as db:
        await _mark_usage(db, "artwork", artwork_id)   # 사용량 귀속 대상 지정 (contextvar)
        repo = ArtworkRepository(db)
        trans = GeminiTransService()

        if not await repo.get_artwork_by_id(artwork_id):
            logger.warning(f"[artwork_trans] artwork_id={artwork_id} not found, skipping")
            return []

        # 한국어는 원문. 나머지 29개 언어가 대상 — only_langs 가 있으면 교집합만
        target_langs = [l for l in MODAL_LANG_NAMES if l != "ko"]
        if only_langs:
            target_langs = [l for l in target_langs if l in set(only_langs)]
            if not target_langs:
                return [{"lang_code": "ko", "description": description}]

        lang_tasks = [{"lang_code": "ko", "description": description}]

        for i in range(0, len(target_langs), CHUNK_SIZE):
            if i > 0:
                await asyncio.sleep(CHUNK_DELAY)
            batch = target_langs[i: i + CHUNK_SIZE]

            result = await trans.artwork_trans_batch(title, description, batch)

            # 스키마는 지켰지만 빈 문자열로 온 언어만 골라 한 번 더
            failed_langs = [code for code, t in result.items() if not (t.get("title") or "").strip()]
            if failed_langs:
                logger.warning(f"Retrying Artwork failed: {failed_langs}")
                result.update(await trans.artwork_trans_batch(title, description, failed_langs))

            success_batch_langs = []
            for lang_code, t in result.items():
                if lang_code != "ko" and not (t.get("title") or "").strip():
                    continue
                # 언어별 1행 upsert — 조회는 이 표에서 언어 코드로 바로 읽는다
                await repo.upsert_artwork_lang(artwork_id, t.get("title", ""), t.get("description", ""), lang_code)
                lang_tasks.append({"lang_code": lang_code, "description": t.get("description", "")})
                success_batch_langs.append(lang_code)

            if success_batch_langs:
                await _notify_admin(db, admin_id, f"{title}의 {', '.join(success_batch_langs)} 완료")
            await db.commit()   # 묶음마다 커밋 — 중간에 죽어도 된 언어는 남는다

        await asyncio.sleep(POST_DELAY)
        # 관람객 화면 캐시(전시 목록 · 작품 목록 · 키오스크 가이드) 무효화 — 워커가 DB 를 바꾼 경로도 빠뜨리지 않는다.
        # 싱글턴 redis 를 쓰면 이전 태스크의 (이미 닫힌) 이벤트 루프에 묶여 터지므로 이 루프용 클라이언트를 새로 만든다
        agent_id = await _resolve_agent_id(db, "artwork", artwork_id)
        rs = RedisService()
        try:
            await invalidate_agent_content(agent_id, redis=rs)
        finally:
            await rs.close()
    return lang_tasks   # 이어지는 음성 합성 태스크의 입력


# ── 주기 배치: 누락분 보충 ───────────────────────────────────────────────
@celery_app.task
def sweep_missing_artwork_trans():
    """번역이 비어 있는 (작품, 언어) 쌍을 찾아 only_langs 로 다시 태운다."""
    # ... (생략: 언어별 행이 없는 작품을 조회해 process_artwork_trans.delay(..., only_langs=[...]))


celery_app.conf.beat_schedule = {
    "sweep-missing-artwork-trans": {
        "task": "app.worker.trans_tasks.sweep_missing_artwork_trans",
        "schedule": crontab(hour=0, minute=0),  # 매일 KST 자정
    },
}


async def _mark_usage(db, kind: str, entity_id: int) -> None:
    from app.core.utils.usage import set_usage_target
    agent_id = await _resolve_agent_id(db, kind, entity_id)
    set_usage_target(agent_id, kind, entity_id)


async def _resolve_agent_id(db, kind: str, entity_id: int) -> int | None:
    # ... (생략: 작품 → 전시 → 고객사 ID)
    return None


async def _notify_admin(db, admin_id: int, description: str) -> None:
    # ... (생략: 관리자 알림 행 추가)
    return None
