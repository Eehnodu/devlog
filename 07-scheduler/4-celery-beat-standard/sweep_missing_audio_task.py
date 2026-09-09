# 출처: 전시관 AI 안내 서비스 (2026.03~) — 매일 자정 Beat 가 부르는 "누락분 보충" 태스크. 스캔 태스크는 가볍게, 실제 작업은 건별 태스크로 다시 큐에 넣는다
# 비동기 코드는 asyncio.run 으로 감싸고, DB 는 태스크마다 엔진을 새로 만들어 쓰고 닫는다.
import asyncio
import logging
from contextlib import asynccontextmanager

from app.worker.celery import celery_app

logger = logging.getLogger(__name__)


# ---------------- worker/db.py ----------------
@asynccontextmanager
async def task_session():
    """Celery 태스크 전용: 매 호출마다 엔진을 새로 생성하고 종료 시 dispose.

    웹 서버의 엔진은 그 프로세스의 이벤트 루프에 묶여 있다. asyncio.run 으로 루프를 새로 만드는
    태스크에서 공유하면 두 번째 실행부터 죽은 루프의 커넥션을 잡는다.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.config.settings import settings

    engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
    session_factory = sessionmaker(
        bind=engine, class_=AsyncSession,
        autocommit=False, autoflush=False, expire_on_commit=False,
    )
    try:
        async with session_factory() as db:
            yield db
    finally:
        await engine.dispose()


# ---------------- worker/tts_tasks.py ----------------
@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, soft_time_limit=600, time_limit=660)
def process_artwork_tts_single(self, artwork_id: int, lang_code: str, description: str, s3_prefix: str):
    """작품 한 건 · 언어 한 개의 음성 합성. 등록 직후에도, 자정 보충 때도 같은 태스크를 쓴다."""
    try:
        return asyncio.run(_run_single(artwork_id, lang_code, description, s3_prefix))
    except Exception as exc:
        raise self.retry(exc=exc)


async def _run_single(artwork_id: int, lang_code: str, description: str, s3_prefix: str) -> dict | None:
    from app.module.artwork.artwork_repository import ArtworkRepository
    from app.module.infra.tts.tts_service import TTSService

    tts_service = TTSService()
    max_attempts = 3
    backoff_sec = 5
    result = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = await tts_service.synthesize_with_timestamps(description, lang_code, s3_prefix)
            break
        except Exception as e:
            logger.warning(f"TTS attempt {attempt}/{max_attempts} failed [{lang_code}] artwork_id={artwork_id}: {e}")
            # 같은 입력이 실행할 때마다 성공/실패가 갈리는 확률적 실패라 재시도가 유효하다.
            if attempt < max_attempts:
                await asyncio.sleep(backoff_sec * attempt)  # 5s, 10s 지수 백오프
                continue
            logger.error(f"TTS giving up [{lang_code}] artwork_id={artwork_id} after {max_attempts} attempts")
            return None  # 여기서 포기한 건이 자정 보충 배치의 대상이 된다

    async with task_session() as db:
        repo = ArtworkRepository(db)
        await repo.update_artworklang_audio(
            artwork_id, lang_code,
            audio_path=result["audio_path"],
            audio_duration=result["audio_duration"],
            audio_timepoints=result["audio_timepoints"],
        )
        await db.commit()
    return {"lang_code": lang_code, "audio_path": result["audio_path"]}


@celery_app.task(bind=True, soft_time_limit=120, time_limit=180)
def sweep_missing_artwork_audio(self, limit: int = 20, exhibition_id: int | None = None):
    """audio_path 누락된 ArtworkLang을 스캔해서 process_artwork_tts_single을 디스패치.
    Celery Beat에서 주기적으로 호출되거나, 관리자가 수동 트리거.
    """
    try:
        return asyncio.run(_sweep_missing_artwork_audio(limit, exhibition_id))
    except Exception as exc:
        logger.error(f"Sweep missing audio failed: {exc}")
        raise


async def _sweep_missing_artwork_audio(limit: int, exhibition_id: int | None) -> dict:
    from app.module.artwork.artwork_repository import ArtworkRepository

    # DB 세션은 조회가 끝나면 바로 닫는다 — 큐에 넣는 동안 커넥션을 붙들지 않는다
    async with task_session() as db:
        repo = ArtworkRepository(db)
        rows = await repo.get_artwork_langs_missing_audio(limit=limit, exhibition_id=exhibition_id)

    queued = 0
    for r in rows:
        s3_prefix = f"{r['agent_id']}/exhibition/{r['exhibition_id']}/artwork/{r['artwork_id']}/audio"
        process_artwork_tts_single.delay(r["artwork_id"], r["lang_code"], r["description"], s3_prefix)
        queued += 1
    logger.info(f"Sweep queued {queued} missing-audio TTS tasks (limit={limit}, exhibition_id={exhibition_id})")
    return {"queued": queued}
