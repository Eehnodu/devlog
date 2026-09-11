# 출처: 전시관 AI 안내 서비스 (2026.08) — 개수 · 열거 질문의 판정을 대화 모델에서 떼어 온도 0 · 사고 모드 끔 · JSON 출력의 별도 호출로 분리
#
# 대화 모델에게 판정까지 맡기면 프롬프트 상황에 따라 결과가 흔들린다
# (같은 질문에 3종 · 4종 · 7종 · 9종 · 10종이 번갈아 나왔다). 그래서 판정은
# 대화와 분리된 짧은 호출로 처리하고, 대화 모델에는 '확정된 목록과 개수' 만 넘긴다.

import asyncio
import json
import logging

from google import genai
from google.genai import types

from app.core.config.settings import settings

logger = logging.getLogger(__name__)

VERIFY_BATCH = 40  # 한 호출에 판정할 후보 수


async def _verify_batch(keyword: str, items: list[dict], qualifier: str = "") -> list[dict] | None:
    """후보 한 묶음을 판정해 '진짜 해당하는 것' 만 돌려준다. 실패하면 None."""
    if not items:
        return []
    numbered = "\n".join(f'{i}. {it["name"]} :: {it["sentence"]}' for i, it in enumerate(items, 1))

    # 사고 모드를 끈 상태에서도 흔들리지 않도록 판정 기준을 예시로 못 박는다.
    # (끄기 전엔 20초가 걸렸고, 그냥 끄면 부분 해당 · 특정 지역 한정까지 통과했다)
    instruction = (
        f'For each numbered entry answer: does the sentence state that THIS entry itself is fully "{keyword}"?\n'
        "Answer NO when it is only partly or nearly so, applies to one region only, "
        "is about a different subject in the sentence, or is a risk / grade / effort.\n"
        "Answer YES only for a plain, unqualified statement about this entry itself.\n"
        + (
            f'\nSECOND CONDITION — the visitor asked only about "{qualifier}". '
            "Answer YES only when BOTH hold. If either fails, or you cannot tell, answer NO.\n"
            if qualifier else ""
        )
        + 'Return JSON only: {"yes": [numbers]}\n\n' + numbered
    )
    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        res = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=instruction,
            config=types.GenerateContentConfig(
                temperature=0,                          # 같은 입력 → 같은 판정
                response_mime_type="application/json",
                # 사고 모드를 켜두면 판정 한 번에 20초 넘게 걸려 대화가 끊긴다.
                # 문장 하나하나 예/아니오를 고르는 단순 판정이라 끄는 게 맞다.
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        picked = json.loads(res.text or "{}").get("yes") or []
        chosen = [items[n - 1] for n in picked if isinstance(n, int) and 1 <= n <= len(items)]
        # 이름만 주면 모델이 전부 같은 전시실에 있는 것처럼 말한다. 출처와 전시실을 항목마다 붙여서 넘긴다.
        return [
            {"name": it["name"], "source": it.get("source"), "exhibition": it.get("exhibition") or None}
            for it in chosen
        ]
    except Exception as e:
        logger.error(f"[mentions] 판정 실패 — 모델 판단으로 넘김: {e}")
        return None


async def _verify_mentions(keyword: str, items: list[dict], qualifier: str = "") -> dict | None:
    """후보 전체를 묶음으로 나눠 동시에 판정하고 확정 목록을 만든다.

    한 묶음이라도 실패하면 None 을 반환해 기존처럼 모델이 직접 판단하게 둔다
    (일부만 판정된 목록을 '확정' 이라고 넘기면 조용히 적게 세게 된다).
    """
    if not items:
        return {"verified": [], "count": 0}
    batches = [items[i:i + VERIFY_BATCH] for i in range(0, len(items), VERIFY_BATCH)]
    results = await asyncio.gather(*(_verify_batch(keyword, b, qualifier) for b in batches))
    if any(r is None for r in results):
        return None
    verified = [v for r in results for v in r]
    logger.info(f"[mentions] keyword={keyword!r} candidates={len(items)} verified={len(verified)}")
    return {"verified": verified, "count": len(verified)}


# 대화(Live) 모델의 도구 실행부에서 이렇게 쓴다 — 개수는 코드가 세고, 모델은 설명과 순서만 맡는다
async def find_mentions_tool(keyword: str, candidates: list[dict], qualifier: str = "") -> dict:
    verified = await _verify_mentions(keyword, candidates, qualifier)
    if verified is None:
        return {"candidates": candidates, "note": "판정 실패 — 문장을 직접 읽고 판단하라"}
    return {
        "count": verified["count"],
        "items": verified["verified"],
        "note": "count 는 서버가 확정한 값이다. 목록을 다시 세거나 줄이지 말라",
    }
