# 출처: 팬 플랫폼 서비스 (2026.05~) — 외부 호출 결과를 Redis 에 캐시하는 두 곳: (1) 유해 발화 판정 (2) 관리자 열람용 번역
# 두 곳 모두 Redis 장애를 "캐시 없음" 으로 취급한다. 캐시가 안 되어도 서비스는 그대로 동작해야 한다.
import hashlib
from dataclasses import dataclass

_CACHE_VERSION = "v2"  # 판정 규칙이 바뀌면 올려서 옛 캐시를 무효화한다
_VERDICT_CACHE_TTL = 60 * 60 * 24 * 7  # 7일
_TRANSLATE_CACHE_TTL = 60 * 60 * 24 * 30  # 30일
_DETAIL_SEP = "\x1f"


@dataclass
class Verdict:
    reason: str
    detail: str | None
    user_message: str | None


def _digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


# =====================================================
# (1) 판정 캐시 — 같은 문장을 같은 맥락에서 이미 막았다면 분류기를 다시 부르지 않는다
# =====================================================
def _allow_key(normalized: str) -> str:
    return f"mod:{_CACHE_VERSION}:allow:{_digest(normalized)}"


# 차단 안내 문구는 언어별이다. 언어를 키에 넣지 않으면 남의 언어로 된 안내가 뜬다.
def _block_key(normalized: str, context_digest: str, lang: str) -> str:
    return f"mod:{_CACHE_VERSION}:block:{lang}:{_digest(normalized)}:{context_digest}"


async def _cached_allow(redis_service, normalized: str) -> bool:
    """이 문장이 맥락 없이 통과된 적 있으면 True."""
    if not redis_service:
        return False
    try:
        return await redis_service.get(_allow_key(normalized)) == "1"
    except Exception:
        return False


async def _cached_block(redis_service, normalized: str, context_digest: str, lang: str) -> Verdict | None:
    """같은 문장을 같은 맥락에서 이미 막았다면 그 판정을 그대로 재사용한다.

    차단된 입력은 대화에 저장되지 않아 재시도해도 맥락이 그대로다 — 유저가
    같은 말을 여러 번 눌러도 분류기를 다시 부르지 않고, 같은 안내가 다시 뜬다.
    """
    if not redis_service:
        return None
    try:
        value = await redis_service.get(_block_key(normalized, context_digest, lang))
    except Exception:
        return None
    if not value:
        return None
    reason, detail, user_message = (value.split(_DETAIL_SEP) + ["", ""])[:3]
    return Verdict(reason, detail or None, user_message or None)


async def _store_verdict(redis_service, normalized: str, context_digest: str, lang: str, verdict: Verdict | None) -> None:
    if not redis_service:
        return
    try:
        if verdict is None:
            await redis_service.set(_allow_key(normalized), "1", expire=_VERDICT_CACHE_TTL)
        else:
            await redis_service.set(
                _block_key(normalized, context_digest, lang),
                _DETAIL_SEP.join((verdict.reason, verdict.detail or "", verdict.user_message or "")),
                expire=_VERDICT_CACHE_TTL,
            )
    except Exception:
        pass  # 캐시 저장 실패는 판정 결과에 영향을 주지 않는다


# =====================================================
# (2) 번역 캐시 — 관리자가 외국어 대화 기록을 열 때마다 번역기를 부르지 않는다
# =====================================================
def _translate_cache_key(text: str, namespace: str) -> str:
    return f"tr:{namespace}:ko:{_digest(text)}"


class LogService:
    def __init__(self, log_repo, redis_service=None):
        self.log_repo = log_repo
        self.redis_service = redis_service

    async def _cached_translation(self, text: str, namespace: str = "chatlog") -> str | None:
        if not self.redis_service:
            return None
        try:
            return await self.redis_service.get(_translate_cache_key(text, namespace))
        except Exception:
            return None  # 캐시 조회 실패는 무시하고 재번역

    async def _store_translation(self, text: str, translated: str, namespace: str = "chatlog") -> None:
        if not self.redis_service:
            return
        try:
            await self.redis_service.set(
                _translate_cache_key(text, namespace),
                translated,
                expire=_TRANSLATE_CACHE_TTL,
            )
        except Exception:
            pass  # 캐시 저장 실패는 무시

    async def translate_for_admin(self, texts: list[str]) -> list[str]:
        out: list[str] = []
        for text in texts:
            hit = await self._cached_translation(text)
            if hit is not None:
                out.append(hit)
                continue
            translated = await self._call_translator(text)  # ... (생략) 1차 번역기, 실패 시 GPT 폴백
            await self._store_translation(text, translated)
            out.append(translated)
        return out

    async def _call_translator(self, text: str) -> str:
        return text
