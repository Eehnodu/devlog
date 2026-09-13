# 출처: 전시관 AI 안내 서비스 (2026.03~04) — 30개 언어 사전 번역: 한 호출에 여러 언어를 JSON 스키마(언어 코드 → 필드) 로 구조화 출력, 일시 오류만 재시도, 호출마다 사용량 기록
# 관람객이 언어를 바꿀 때마다 번역하면 지연과 비용이 붙는다. 등록 시점에 전부 만들어 저장하고 조회는 저장분을 준다.

import asyncio
import json

from google import genai
from google.genai import types

from app.core.config.settings import settings
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

# 잠시 후 풀리는 일시적 오류 — 짧게 재시도할 가치가 있는 것들
_TRANSIENT_ERRORS = (
    "503", "UNAVAILABLE",          # 모델 과부하
    "429", "RESOURCE_EXHAUSTED",   # 레이트리밋
    "500", "INTERNAL",             # 일시적 서버 오류
    "504", "DEADLINE_EXCEEDED",    # 타임아웃
)

# 지원 언어 30개 — 코드는 저장 키, 이름은 프롬프트에 쓴다 (코드만 주면 모델이 언어를 헷갈린다)
MODAL_LANG_NAMES: dict[str, str] = {
    "ko": "Korean", "en": "English", "zh": "Chinese", "ja": "Japanese",
    "es": "Spanish", "fr": "French", "de": "German", "ru": "Russian",
    "vi": "Vietnamese", "th": "Thai", "id": "Indonesian", "ms": "Malay",
    "hi": "Hindi", "it": "Italian", "pt": "Portuguese", "nl": "Dutch",
    "pl": "Polish", "tr": "Turkish", "uk": "Ukrainian", "ar": "Arabic",
    "fa": "Persian", "mn": "Mongolian", "sv": "Swedish", "cs": "Czech",
    "hu": "Hungarian", "ro": "Romanian", "el": "Greek", "he": "Hebrew",
    "fil": "Filipino", "bn": "Bengali",
}


class GeminiTransService:
    def __init__(self):
        # HTTP 타임아웃(ms): 한 번역 호출이 비정상적으로 오래 매달려 워커가 시간초과로 죽는 것 방지.
        self.client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(timeout=90_000),
        )
        self.model = "gemini-2.5-flash-lite"

    async def _generate_json(self, label: str, prompt: str, properties: dict) -> dict:
        """번역 배치 공통 호출 — 일시적 오류는 짧게 재시도하고, 끝내 실패하면 예외를 올린다.

        예전에는 예외를 삼키고 {} 를 반환해서, 503 한 번에 그 배치의 언어가 통째로 누락된 채
        태스크가 '성공' 으로 끝났다. Celery 의 재시도(60초 뒤 3회) 도 타지 못했다.
        """
        # 사용량 기록 — 번역 10종이 전부 이 함수를 지나므로 여기 한 곳만 계측하면 된다.
        from app.core.utils.usage import record_usage, usage_from_response

        langs = len(properties)  # 이 배치가 처리하는 언어 수
        attempts = 3
        for i in range(1, attempts + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        # 언어 코드 → {필드: 문자열} 스키마를 강제해 파싱 실패와 누락을 막는다
                        response_schema={"type": "OBJECT", "properties": properties},
                    ),
                )
                t_in, t_out = usage_from_response(response)
                await record_usage("trans", self.model, tokens_in=t_in, tokens_out=t_out, calls=i, langs=langs)
                return json.loads(response.text)
            except Exception as e:
                is_transient = any(t in str(e) for t in _TRANSIENT_ERRORS)
                logger.error(f"{label} Batch Translation Error ({i}/{attempts}, transient={is_transient}): {e}")
                if is_transient and i < attempts:
                    await asyncio.sleep(3 * i)  # 3s, 6s
                    continue
                # 끝내 실패해도 호출은 이미 과금됐으므로 남긴다
                await record_usage("trans", self.model, calls=i, langs=langs)
                raise

    async def artwork_trans_batch(self, title: str, description: str, target_langs: list[str]):
        lang_names = [MODAL_LANG_NAMES.get(code, code) for code in target_langs]

        prompt = f"""
        Translate the following artwork details into these {len(target_langs)} languages: {', '.join(lang_names)}.

        CRITICAL RULES:
        1. NEVER return Korean characters (Hangeul) in any field.
        2. If a word is a proper noun with no direct translation, TRANSLITERATE it using the phonetic script of the target language.
        3. Maintain the professional tone of an art gallery.
        4. Return ONLY a JSON object where each key is the language code provided.

        - Title: {title}
        - Description: {description}
        """

        properties = {
            lang: {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING"},
                    "description": {"type": "STRING"},
                },
                "required": ["title", "description"],
            }
            for lang in target_langs
        }
        return await self._generate_json("Artwork", prompt, properties)

    # ... (생략: exhibition · facility · building · section · intro · quiz · survey · consent · palette 배치 — 필드만 다르고 같은 구조)
