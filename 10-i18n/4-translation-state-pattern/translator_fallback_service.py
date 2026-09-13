# 출처: 팬 플랫폼 서비스 (2026.06) — 1차 번역기가 비거나 미지원 언어면 GPT 로 재번역하는 폴백. 결과는 Redis 에 (텍스트, 언어) 키로 캐시
# 폴백 판정은 언어 코드가 아니라 결과로 한다 — 결과가 비었거나 글자가 있는 원문이 그대로 돌아오면 폴백.

import hashlib

from app.module.infra.translator.translator_service import translator_service

# GPT 폴백 번역 캐시 TTL — 1차 번역기 캐시와 동일(30일)
_GPT_TRANSLATE_CACHE_TTL = 60 * 60 * 24 * 30


def _has_letters(s: str | None) -> bool:
    return any(ch.isalpha() for ch in (s or ""))


class GPTService:
    def __init__(self, redis_service):
        self.redis_service = redis_service

    async def translate(self, text: str, target_language: str, use_cache: bool = True) -> str:
        """텍스트를 target_language(앱 언어코드, 예: 'ko','en','ja') 로 번역.

        1순위 번역 특화 서비스(빠르고 저렴), 미지원 언어 · 실패 시 GPT 폴백.
        use_cache=False: 캐시를 건너뛰고 항상 새로 번역(배치 재번역용).
        """
        first = await translator_service.translate(text, target_language, use_cache=use_cache)
        if first:
            return first

        # 폴백: GPT. 1차 번역기 미지원 언어(fil/th/vi/hi/ms 등)나 실패 시.
        # 1차와 동일하게 결과를 Redis 에 캐싱 → 같은 (텍스트, 언어) 재요청은 GPT 재호출 없이 반환.
        cache_key = self._translate_cache_key(text, target_language)
        if use_cache:
            try:
                cached = await self.redis_service.get(cache_key)
                if cached:
                    return cached
            except Exception:
                pass  # 캐시 조회 실패는 무시하고 재번역

        result = await self.summarize(
            text=text,
            instruction=(
                f"Translate the following text into the language with code '{target_language}'. "
                "Output only the translated text with no explanations or additional content."
            ),
        )

        if result:
            try:
                await self.redis_service.set(cache_key, result, expire=_GPT_TRANSLATE_CACHE_TTL)
            except Exception:
                pass  # 캐시 저장 실패는 무시
        return result

    async def translate_map(self, source: dict[str, str], target_language: str, instruction: str | None = None) -> dict[str, str]:
        """{키: 원문} → {키: 번역문}. 1차 번역기 우선, 번역이 안 된 항목만 GPT 폴백.

        폴백 판정은 언어 코드가 아니라 결과로 한다 — 결과가 비었거나, 글자가 있는 원문이
        그대로 돌아온 항목만. 숫자 · 기호만 있는 텍스트는 원문과 같아도 폴백하지 않는다(불필요한 호출 방지).
        """
        out: dict[str, str] = {}
        for key, text in source.items():
            out[key] = await translator_service.translate(text, target_language) or ""

        missing = {
            k: source[k] for k, v in out.items()
            if not v or (_has_letters(source[k]) and v.strip() == (source[k] or "").strip())
        }
        if missing:
            # ... (생략: 누락 항목만 JSON 으로 묶어 GPT 한 번 호출, 결과를 out 에 덮어쓴다)
            for k, v in missing.items():
                out[k] = await self.translate(v, target_language)
        return out

    @staticmethod
    def _translate_cache_key(text: str, target_language: str) -> str:
        digest = hashlib.sha256((text or "").encode("utf-8")).hexdigest()
        return f"translate:gpt:{target_language}:{digest}"

    async def summarize(self, text: str, instruction: str) -> str:
        # ... (생략: Responses API 호출 — instructions=instruction, input=text)
        raise NotImplementedError
