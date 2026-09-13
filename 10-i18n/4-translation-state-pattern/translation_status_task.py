# 출처: 팬 플랫폼 서비스 (2026.06) — 언어별 번역 행에 상태(대기 · 완료 · 실패) 컬럼. 등록 시 전 언어를 대기로 만들고 워커가 언어마다 완료 · 실패로 바꾼다
# 6개 이상 도메인(콘텐츠 · 뉴스 · 배너 · 프로모 · 공지 · 구독 상품)이 같은 패턴을 쓴다. 관리자 화면은 상태로 "번역 중 / 실패 → 재번역" 을 보여 준다.

import asyncio
import logging

from sqlalchemy import Column, ForeignKey, Integer, String, Text

from app.core.database.base import Base
from app.worker.celery import celery_app

logger = logging.getLogger(__name__)

# 자동 번역 대상 19개 언어 (한국어 원문 제외) — 전 도메인이 같은 목록을 쓴다
AUTO_TRANSLATE_LANGUAGES = [
    "en", "ja", "id", "fil", "th", "es", "pt", "zh", "hi", "vi",
    "ms", "fr", "ar", "ru", "tr", "de", "pl", "it", "nl",
]


# ── 모델: 언어별 1행 + 상태 ───────────────────────────────────────────────
class ContentTranslation(Base):
    """콘텐츠 다국어 번역. 본체 표의 title/description 은 한국어 정규본으로 유지하고,
    이 표는 비-한국어 언어의 번역본을 언어별 1행으로 보관한다."""

    __tablename__ = "tb_content_translation"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    content_id = Column(Integer, ForeignKey("tb_content.id", ondelete="CASCADE"), nullable=False, index=True)
    language = Column(String(20), nullable=False, index=True)   # ISO 언어 코드 (ko 는 본체 사용)
    title = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    # pending(번역 생성 중) / done(완료 · 수동 입력) / failed(생성 실패)
    status = Column(String(20), nullable=False, default="done", server_default="done")


# ── 저장소 ───────────────────────────────────────────────────────────────
class ContentRepository:
    def __init__(self, db):
        self.db = db

    async def upsert_translation(self, content_id: int, language: str, data: dict) -> ContentTranslation:
        """번역 행 upsert (없으면 생성, 있으면 갱신). 상태만 바꿀 때도 같은 함수를 쓴다."""
        translation = await self.get_translation(content_id, language)
        if translation:
            for key, value in data.items():
                setattr(translation, key, value)
        else:
            translation = ContentTranslation(content_id=content_id, language=language, **data)
            self.db.add(translation)
        await self.db.commit()
        await self.db.refresh(translation)
        return translation

    async def set_translation_status(self, content_id: int, language: str, status: str) -> ContentTranslation:
        return await self.upsert_translation(content_id, language, {"status": status})

    async def get_translation(self, content_id: int, language: str):
        # ... (생략)
        return None

    async def get_by_id(self, content_id: int):
        # ... (생략)
        return None


# ── 서비스: 등록 시 전 언어를 '대기' 로 만들고 워커에 넘긴다 ─────────────────
class ContentService:
    def __init__(self, content_repo: ContentRepository):
        self.content_repo = content_repo

    async def dispatch_auto_translate(self, content_id: int) -> None:
        # 워커가 돌기 전에 pending 행을 먼저 만든다 — 관리자 화면이 즉시 "번역 중" 을 보여 줄 수 있다
        for lang in AUTO_TRANSLATE_LANGUAGES:
            await self.content_repo.upsert_translation(content_id, lang, {"status": "pending"})
        try:
            translate_content.delay(content_id)
        except Exception as e:
            logger.error(f"[content dispatch_auto_translate] celery dispatch failed content_id={content_id}: {e}")

    async def dispatch_retranslate(self, content_id: int, language: str) -> None:
        """실패한 언어 하나만 다시 — 관리자 화면의 '재번역' 버튼."""
        await self.content_repo.upsert_translation(content_id, language, {"status": "pending"})
        translate_content.delay(content_id, [language])


# ── 워커: 언어마다 완료 · 실패를 따로 기록, 한 언어 실패가 다른 언어를 막지 않는다 ──
@celery_app.task(name="app.worker.translation_task.translate_content", ignore_result=True)
def translate_content(content_id: int, languages: list[str] | None = None):
    """languages=None 이면 전체 언어, 지정 시 해당 언어만(단건 재번역)."""
    asyncio.run(_run_content(content_id, languages))


async def _run_content(content_id: int, languages: list[str] | None = None) -> None:
    from app.core.database.base import task_session
    from app.module.infra.gpt.gpt_service import GPTService
    from app.module.infra.redis.redis_service import RedisService

    target_languages = (
        [l for l in languages if l in AUTO_TRANSLATE_LANGUAGES] if languages else AUTO_TRANSLATE_LANGUAGES
    )

    async with task_session() as db:
        repo = ContentRepository(db)
        gpt = GPTService(redis_service=RedisService())

        content = await repo.get_by_id(content_id)
        if not content:
            logger.error("[translate_content] content not found id=%s", content_id)
            return

        for lang in target_languages:
            try:
                # use_cache=False: 재번역 요청이면 캐시를 건너뛰고 새로 번역
                title_t = await gpt.translate(content.title, lang, use_cache=False) if content.title else None
                desc_t = await gpt.translate(content.description, lang, use_cache=False) if content.description else None
                await repo.upsert_translation(content_id, lang, {"title": title_t, "description": desc_t})
                await repo.set_translation_status(content_id, lang, "done")
            except Exception as e:
                logger.error("[translate_content] lang=%s content_id=%s failed: %s", lang, content_id, e)
                await repo.set_translation_status(content_id, lang, "failed")
                continue   # 다음 언어로 — 실패한 언어는 화면에서 재번역 버튼이 뜬다
