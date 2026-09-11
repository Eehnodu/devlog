# 출처: AI 글쓰기 검토 서비스 (2025.08) — 관점별로 분리한 프롬프트를 한 단계씩 순차 실행, 결과는 항목별 전체 수정본(JSON) 으로 받아 원문과 diff
# 프롬프트는 관리자가 DB 에 등록하고 순서를 정한다. 프론트가 현재 단계 번호와 프롬프트 ID 를 들고 한 단계씩 호출한다.

import json
import re

from fastapi.responses import JSONResponse
from openai import AsyncOpenAI

from app.config import settings
from app.repository.client import writing_repository

client = AsyncOpenAI(api_key=settings.settings.openai_api_key)


async def get_review_progress(request, db, user):
    """한 단계(프롬프트 하나)를 실행한다. 프론트는 응답의 current_step+1 로 다음 단계를 다시 부른다."""
    body = await request.json()
    content_id = body.get("content_id")
    current_step = body.get("current_step", 0)
    prompt_id = body.get("prompt_id")
    category = body.get("category")

    if not user:
        return JSONResponse(status_code=401, content={"status": 401, "message": "token not found"})

    # 이번에 실행할 프롬프트 (관점 하나: 필수 정보 · 관련성 · 문법 · 어조 ...)
    current_prompt = await writing_repository.get_single_ai_prompt(db, user, prompt_id)
    if not current_prompt:
        return JSONResponse(status_code=404, content={"status": 404, "message": "AI prompt not found"})

    # 글은 항목(제목 · 본문 · 안내 ...)별로 저장돼 있다. 이전 단계가 고친 결과(content_diff)가 있으면 그것을 입력으로
    data = await writing_repository.get_review_progress(db, user, content_id)
    content_text = ""
    fields_info = []
    for item in data:
        item_content = item.get("content_diff") or item.get("content_text") or ""
        content_text += f"{item.get('field_name', '')}\n{item_content}\n\n"
        fields_info.append({"id": item.get("generation_method_id"), "title": item.get("field_name", "")})

    return await execute_single_prompt(db, user, current_prompt, content_text, content_id, current_step, fields_info, category)


async def execute_single_prompt(db, user, current_prompt, content_text, content_id, current_step, fields_info, category):
    try:
        prompt_text = current_prompt.get("prompt", "")

        # 관점 프롬프트(관리자 등록) 뒤에 출력 형식 규칙을 고정으로 붙인다.
        # 항목 순서와 개수를 그대로 돌려받아야 원문과 짝을 맞춰 diff 를 낼 수 있다.
        instructions = (
            prompt_text
            + "\n\n다음 규칙에 따라 반드시 JSON 형식으로 응답하세요.\n"
            "- 인사말 · 마무리 멘트는 쓰지 마세요.\n"
            "- 원문에 없는 마크다운은 쓰지 말고, 있는 것은 유지하세요.\n"
            "- `content_diff` 에는 원문 전체를 담되 수정한 부분만 반영하세요. 나머지는 원문과 완전히 같아야 합니다.\n"
            "- 항목들을 입력 순서 그대로 JSON 배열로, 각 항목은 {title, content_diff} 로 작성하세요.\n"
            "[반드시 출력할 항목 목록 및 순서]\n"
            + "\n".join(f"{i + 1}. {f['title']}" for i, f in enumerate(fields_info))
            + "\n[응답 예시]\n```json\n[\n"
            + ",\n".join(f'  {{\n    "title": "{f["title"]}",\n    "content_diff": "변경된 전체 내용"\n  }}' for f in fields_info)
            + "\n]\n```\n"
        )

        response = await client.responses.create(
            model="gpt-4o-mini",
            instructions=instructions,
            input=content_text,
            stream=False,
        )

        try:
            raw = response.output[0].content[0].text
            json_str = re.sub(r"^```json\s*|\s*```$", "", raw.strip())
            ai_response = json.loads(json_str)

            # 모델이 순서를 바꿔 보내도 입력 순서로 되돌린다
            order_map = {(f.get("title") or "").strip(): idx for idx, f in enumerate(fields_info)}
            ai_response = sorted(ai_response, key=lambda it: order_map.get((it.get("title") or "").strip(), 10**9))
        except Exception as e:
            db.rollback()
            return JSONResponse(status_code=500, content={"status": 500, "message": f"AI 응답 파싱 실패: {str(e)}"})

        # 항목별 수정본을 이 단계 결과로 저장 (원문 대비 diff 는 조회 시 diff-match-patch 로 계산)
        review_result = []
        for item in ai_response:
            review_result.append({
                "title": item.get("title"),
                "content_diff": item.get("content_diff", ""),
                "prompt_id": current_prompt.get("id"),
                "prompt_title": current_prompt.get("title"),
            })
        await writing_repository.save_review_step(db, user, content_id, current_step, review_result, commit=False)
        # ... (생략: 수정 사유 생성 호출 — 같은 트랜잭션, 커밋은 아래 한 번)

        # 마지막 프롬프트면 진행 상태를 완료로 — 같은 트랜잭션에 포함
        ai_prompts = await writing_repository.get_ai_prompt(db, user, int(content_id))
        prompt_ids = [p.get("id") for p in (ai_prompts or [])]
        is_last_step = bool(prompt_ids) and current_prompt.get("id") == prompt_ids[-1]
        if is_last_step:
            await writing_repository.update_content_progress(db, user, content_id, commit=False)

        db.commit()
        return JSONResponse(status_code=200, content={
            "status": 200,
            "data": {
                "content_id": content_id,
                "current_step": current_step + 1,
                "prompt_id": current_prompt.get("id"),
                "review_result": review_result,
            },
        })
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"status": 500, "message": str(e)})
