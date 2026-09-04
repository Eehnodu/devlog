# 출처: AI 상담 챗봇 서비스 (2025.06, Django + FastAPI 계열) — FastAPI StreamingResponse 로 진짜 스트리밍. Responses API 델타를 받는 즉시 text/event-stream 으로 흘려보낸다
import json
import os
import re

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from openai import AsyncOpenAI
from sqlalchemy.orm import Session

from database import get_db
from schemas import ChatRequest
from services import append_log_history, create_log, get_category_by_name

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
router = APIRouter()

# 대화 상태는 아직 프로세스 메모리(단일 워커 전제). 뒤에 Redis 로 옮겨진다.
session_store = {}


@router.post("/chat_stream/")
async def chat_stream(request: ChatRequest, db: Session = Depends(get_db)):
    session_id = request.session_id
    user_message = request.user_message
    category_name = request.categoryName
    version = "v1"

    sess = session_store.setdefault(session_id, {"messages": [], "log_id": None})

    db_data = get_category_by_name(db, category_name, version=version)
    if not db_data:
        return JSONResponse(status_code=404, content={"error": "해당 카테고리 없음"})

    if request.reset or not sess.get("messages"):
        await init_system_messages(sess, db_data, reset=True)  # 카테고리 프롬프트 · 인사말 세팅

    system_prompt = "\n".join(msg["content"] for msg in sess["messages"] if msg["role"] == "system")

    # 학습 파일이 있는 카테고리는 file_search 도구를 붙인다
    tools = None
    if db_data.category_data_only == "only_file":
        tools = [{
            "type": "file_search",
            "vector_store_ids": [db_data.vector_store_id],
            "max_num_results": 5,
        }]

    async def event_stream():
        fullText = ""
        try:
            input_messages = "\n".join(
                f"{m['role'].upper()}: {m['content']}"
                for m in sess["messages"] if m["role"] in ["user", "assistant"]
            )
            full_input = input_messages + f"\nUSER: {user_message}"

            stream = await client.responses.create(
                model=sess["gpt_version"],
                instructions=system_prompt,
                input=full_input,
                tools=tools,
                stream=True,
            )

            # 델타가 오는 즉시 SSE 한 줄로 내보낸다 — 세션 저장도, 폴링도 없다
            async for chunk in stream:
                if chunk.type == "response.output_text.delta":
                    delta = chunk.delta
                    fullText += delta
                    yield f"data: {json.dumps({'type': 'text', 'data': delta})}\n\n"

            # 1차 클린업 — 출처 각주(전각 괄호) 제거, 굵게 표기 변환
            clean_text = re.sub(r"【.*?†.*?】", "", fullText)
            clean_text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", clean_text)

            # 2차 GPT 기반 정제 — 본문 안 링크를 맨 아래 목록으로 모아 달라는 후처리 호출
            refine_prompt = "본문은 그대로 두고, 설명 중간의 링크는 모두 지운 뒤 맨 마지막에 [제품 링크] 목록으로 한 줄씩 정리해줘."
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
                print("GPT 정제 실패, clean_text 그대로 사용:", refine_error)
                refined_text = clean_text

            # 로그 및 세션 저장
            history_log = f"[user_message]: {user_message}\n[assistant_message]: {refined_text}\n"
            if not sess.get("log_id"):
                log = create_log(db, category_name, sess["gpt_version"], history_log, version)
                sess["log_id"] = log.id
            else:
                append_log_history(db, sess["log_id"], history_log, version)

            sess["messages"].append({"role": "user", "content": user_message})
            sess["messages"].append({"role": "assistant", "content": refined_text})

            # 스트림 종료 이벤트 — 프론트는 이걸 받고 최종 문장으로 말풍선을 갈아 끼운다
            yield f'data: {json.dumps({"type": "end"})}\n\n'

        except Exception as e:
            print("GPT 스트리밍 오류:", e)
            yield f'data: {json.dumps({"type": "error", "data": "GPT 오류"})}\n\n'

    return StreamingResponse(event_stream(), media_type="text/event-stream")
