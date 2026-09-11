# 출처: AI 상담 챗봇 서비스 (2025.05) — Responses API + file_search 를 SSE 로 스트리밍, 파일 없는 카테고리는 도구 없이 같은 호출, 끝나면 2차 정제 호출
# 관리자 화면은 Django 에 두고 대화 응답만 FastAPI(ASGI) 로 분리한 뒤 처음으로 진짜 스트리밍이 가능해졌다.

import json
import os
import re

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from openai import AsyncOpenAI

from database import get_db
from services import get_category_by_name, create_log, append_log_history
from schemas import ChatRequest

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
router = APIRouter()
session_store = {}  # 프로세스 메모리 세션 — 워커 1개 전제 (Redis 로 옮기는 것은 이후 프로젝트)
version = "v1"

CITATION = re.compile(r"【.*?†.*?】")


async def init_system_messages(sess: dict, db_data, reset=False) -> None:
    if reset or not sess.get("messages"):
        sess["messages"] = []
    sess["gpt_version"] = db_data.gpt_version
    sess["log_id"] = None

    if db_data.category_data_order:
        sess["messages"].append({"role": "system", "content": db_data.category_data_order})
    if db_data.category_data_only == "only":
        # 텍스트 자료 카테고리 — 자료와 출력 형식 규칙을 시스템 메시지로 (고객사 문구는 한 줄로 축약)
        sess["messages"].append({"role": "system", "content": f"다음 자료를 기준으로 답해줘: {db_data.category_data_text} 링크는 답변 맨 끝에만 모아줘."})
    if db_data.category_nodata_msg:
        sess["messages"].append({"role": "system", "content": f"정보 없으면 이렇게 말해줘: {db_data.category_nodata_msg}"})
    sess["messages"].append({"role": "assistant", "content": db_data.category_hi_msg})


@router.post("/gpt_stream")
async def gpt_stream(request: ChatRequest = Body(...), db=Depends(get_db)):
    user_message = request.user_message or ""
    category_name = request.category_name
    session_id = request.session_id or "temp-session"

    sess = session_store.setdefault(session_id, {"messages": [], "gpt_version": "gpt-4o", "log_id": None})

    db_data = get_category_by_name(db, category_name, version=version)
    if not db_data:
        return JSONResponse(status_code=404, content={"error": "해당 카테고리 없음"})

    if request.dict().get("reset", False) or not sess.get("messages"):
        await init_system_messages(sess, db_data, reset=True)

    system_prompt = "\n".join(m["content"] for m in sess["messages"] if m["role"] == "system")

    # 파일 카테고리만 file_search 도구를 붙인다. 파일 없는 카테고리는 tools=None 으로 같은 Responses 호출
    tools = None
    if db_data.category_data_only == "only_file":
        tools = [{
            "type": "file_search",
            "vector_store_ids": [db_data.vector_store_id],
            "max_num_results": 5,
        }]

    async def event_stream():
        full_text = ""
        try:
            # 이전 문답을 한 덩어리 입력으로 묶는다 (Responses API 의 대화 상태 기능은 아직 쓰지 않던 시기)
            history = "\n".join(
                f"{m['role'].upper()}: {m['content']}" for m in sess["messages"] if m["role"] in ("user", "assistant")
            )
            stream = await client.responses.create(
                model=sess["gpt_version"],
                instructions=system_prompt,
                input=history + f"\nUSER: {user_message}",
                tools=tools,
                stream=True,
            )
            async for chunk in stream:
                if chunk.type == "response.output_text.delta":
                    full_text += chunk.delta
                    yield f"data: {json.dumps({'type': 'text', 'data': chunk.delta})}\n\n"

            # 1차 정리 — 출처 각주 제거, 굵게 표기를 HTML 로
            clean_text = CITATION.sub("", full_text)
            clean_text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", clean_text)

            # 2차 정제 — 본문은 그대로 두고 링크만 끝으로 모으는 후처리 호출 (Chat Completions)
            refine_prompt = (
                "요약하지 말고 본문 표현은 그대로 유지한 채, 설명 중간의 링크는 모두 지우고 "
                "맨 마지막 [링크] 절에 '항목명 URL' 한 줄씩 정리해줘. (예: 상품A https://example.com)"
            )
            try:
                refine_response = await client.chat.completions.create(
                    model=sess["gpt_version"],
                    messages=[
                        {"role": "system", "content": refine_prompt},
                        {"role": "user", "content": clean_text},
                    ],
                )
                refined_text = refine_response.choices[0].message.content.strip()
            except Exception as refine_error:
                print("정제 실패, 1차 정리 결과 그대로 사용:", refine_error)
                refined_text = clean_text

            # 로그 · 세션 저장 — 스트리밍이 끝난 뒤 정제된 최종 문장을 기록
            history_log = f"[user_message]: {user_message}\n[assistant_message]: {refined_text}\n"
            if not sess.get("log_id"):
                log = create_log(db, category_name, sess["gpt_version"], history_log, version)
                sess["log_id"] = log.id
            else:
                append_log_history(db, sess["log_id"], history_log, version)

            sess["messages"].append({"role": "user", "content": user_message})
            sess["messages"].append({"role": "assistant", "content": refined_text})

            yield f'data: {json.dumps({"type": "end"})}\n\n'
        except Exception as e:
            print("스트리밍 오류:", e)
            yield f'data: {json.dumps({"type": "error", "data": "응답 생성 오류"})}\n\n'

    return StreamingResponse(event_stream(), media_type="text/event-stream")
