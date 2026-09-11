# 출처: 전시관 AI 안내 서비스 (2026.08) — AI 호출 1건 = 사용량 1행(모델 · 토큰 · 음성 초 · 호출 수), 대상은 contextvar 로 귀속, 단가는 조회 시점에 곱한다
#
# 번역 · TTS · STT 호출 함수는 자기가 "무엇을" 처리 중인지 모른다 (공용 함수라서).
# 그래서 태스크 진입점에서 contextvar 로 대상을 한 번 세팅해 두고, 호출 지점이 그것을 읽는다.
# 기록 실패가 본 작업(번역 · 음성 생성)을 막아서는 안 된다 — 전부 삼키고 로그만 남긴다.

import logging
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String

from app.core.database.base import Base, now_kst

logger = logging.getLogger(__name__)


# ── 모델 ────────────────────────────────────────────────────────────────
# 기존 테이블에 토큰 컬럼을 붙이지 않는 이유:
#  · 한 행에 번역 · TTS · STT 세 종류를 담을 수 없다
#  · 재생성하면 덮어써져 이력이 사라진다
#  · 전시실 · 시설 · 퀴즈… 테이블마다 컬럼을 다 붙여야 한다
# append-only 로 쌓기만 하고 수정하지 않는다 — 쌓인 행 자체가 재생성 이력이 된다.
class AiUsage(Base):
    __tablename__ = "tb_ai_usage"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    agent_id = Column(Integer, ForeignKey("tb_agents.id", ondelete="SET NULL"), nullable=True, index=True)  # 고객사

    kind = Column(String(10), nullable=False, index=True)         # trans | tts | stt | embed
    target_type = Column(String(20), nullable=True, index=True)   # artwork | exhibition | facility | quiz ...
    target_id = Column(Integer, nullable=True, index=True)

    # TTS · STT 는 언어별 1행. 번역은 한 번에 여러 언어를 처리해 NULL 이고 langs 로 개수만 남긴다.
    language = Column(String(10), nullable=True)
    langs = Column(Integer, nullable=False, default=1)

    # 폴백 TTS 모델은 단가가 2배라 모델명을 남기지 않으면 계산이 틀어진다
    model = Column(String(60), nullable=False, default="")

    tokens_in = Column(Integer, nullable=False, default=0)
    tokens_out = Column(Integer, nullable=False, default=0)
    # TTS · STT 오디오 길이(초). STT 는 시간 과금이라 토큰이 아니라 이 값으로 계산한다.
    audio_sec = Column(Float, nullable=False, default=0)

    # 실제 API 호출 수 — 조각 · 청크 · 재시도를 합친 값. 실패한 호출도 과금되므로 함께 센다.
    calls = Column(Integer, nullable=False, default=1)

    created_at = Column(DateTime, default=now_kst, index=True)


# 금액을 행에 저장하지 않는 이유: 단가가 바뀌면 과거 데이터가 전부 틀어진다.
# 토큰 · 초만 쌓아두고 계산은 항상 지금 단가로 한다 (USD / 1M tokens).
PRICING: dict[str, dict[str, float]] = {
    "gemini-2.5-flash-lite": {"in": 0.10, "out": 0.40},
    "gemini-2.5-flash-preview-tts": {"in": 0.50, "out": 10.00},
    # ... (생략)
}


# ── 대상 귀속 ───────────────────────────────────────────────────────────
# (agent_id, target_type, target_id)
_target: ContextVar[tuple[int | None, str | None, int | None]] = ContextVar(
    "usage_target", default=(None, None, None)
)


@contextmanager
def usage_target(agent_id: int | None, target_type: str | None, target_id: int | None = None):
    """이 블록 안에서 일어나는 AI 호출을 지정한 대상에 귀속시킨다."""
    token = _target.set((agent_id, target_type, target_id))
    try:
        yield
    finally:
        _target.reset(token)


def set_usage_target(agent_id: int | None, target_type: str | None, target_id: int | None = None):
    """with 문을 쓰기 어려운 곳(태스크 본문 등)에서 직접 세팅."""
    _target.set((agent_id, target_type, target_id))


# ── 기록 ────────────────────────────────────────────────────────────────
async def record_usage(
    kind: str,
    model: str,
    *,
    tokens_in: int = 0,
    tokens_out: int = 0,
    audio_sec: float = 0.0,
    calls: int = 1,
    language: str | None = None,
    langs: int = 1,
) -> None:
    """사용량 1행 기록. 대상은 contextvar 에서 가져온다.

    전용 세션을 열고 닫는다 — 워커(셀러리)와 웹(FastAPI) 양쪽에서 호출되고,
    본 작업의 트랜잭션에 얹으면 롤백 시 기록까지 사라지기 때문이다.
    """
    agent_id, target_type, target_id = _target.get()
    try:
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import NullPool

        from app.core.config.settings import DATABASE_URL

        # 전역 엔진을 쓰면 안 된다 — 셀러리는 태스크마다 새 이벤트 루프를 만드는데,
        # 전역 엔진의 커넥션 풀은 처음 만들어진 루프에 묶여 있어 'attached to a different loop' 로 터진다.
        engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
        Session = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with Session() as db:
                db.add(AiUsage(
                    agent_id=agent_id, kind=kind, target_type=target_type, target_id=target_id,
                    language=language, langs=max(1, langs), model=model or "",
                    tokens_in=int(tokens_in or 0), tokens_out=int(tokens_out or 0),
                    audio_sec=float(audio_sec or 0), calls=max(1, calls),
                ))
                await db.commit()
        finally:
            await engine.dispose()
    except Exception as e:  # 기록 실패가 본 작업을 막지 않는다
        logger.warning(f"[usage] 기록 실패 ({kind}/{model}): {e}")


def usage_from_response(response) -> tuple[int, int]:
    """Gemini 응답에서 (입력 토큰, 출력 토큰). 없으면 0."""
    um = getattr(response, "usage_metadata", None)
    if not um:
        return 0, 0
    return (
        int(getattr(um, "prompt_token_count", 0) or 0),
        int(getattr(um, "candidates_token_count", 0) or 0),
    )
