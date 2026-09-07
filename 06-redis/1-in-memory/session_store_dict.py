# 출처: AI 아바타 모의 면접 서비스 (2025.05~07) — 대화 세션을 라우터 모듈의 딕셔너리 하나에 담아 두는 인메모리 세션
# 프로세스 메모리에만 있어 재배포하면 사라지고, 워커가 둘이면 요청이 어느 워커에 닿는지에 따라 세션이 보였다 안 보였다 한다.
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from openai import AsyncOpenAI
from sqlalchemy.orm import Session

from app.config import settings
from app.crud import chatbot_crud
from app.database import get_db
from app.services import data_service, user_service

router = APIRouter()
client = AsyncOpenAI(api_key=settings.openai_api_key)

# 세션 ID → {"messages", "chat_history", "thread_id", "log_id", ...}
# 모듈이 import 될 때 한 번 만들어지는 전역 딕셔너리. 이 프로세스 안에서만 유효하다.
session_store = {}


@router.post("/chat")
async def chat(request: Request, user=Depends(user_service.verify_access_token), db: Session = Depends(get_db)):
    try:
        body = await request.json()
        user_message = body.get("message")
        session_id = body.get("sessionId")
        chatbot_id = body.get("chatbotId")
        text_lang = body.get("textLang")

        response_text = await stream_chat(
            client=client,
            chatbot_id=chatbot_id,
            user_message=user_message,
            session_id=session_id,
            session_store=session_store,  # 딕셔너리를 그대로 넘긴다
            db=db,
            text_lang=text_lang,
        )

        return JSONResponse({"message": response_text, "log_id": session_store[session_id]["log_id"]})

    except ValueError as ve:
        return JSONResponse(status_code=404, content={"error": str(ve)})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def stream_chat(
    client: AsyncOpenAI,
    chatbot_id: int,
    user_message: str,
    session_id: str,
    session_store: dict,
    db: Session,
    text_lang: str,
) -> str:
    chatbot = await chatbot_crud.get_chatbot_by_id(db, chatbot_id)
    if not chatbot:
        raise ValueError("Chatbot not found")

    instruction = await data_service.instruction_data(chatbot, text_lang=text_lang)

    # session 초기화 — 처음 보는 세션 ID 면 여기서 빈 대화 기록을 만든다
    if session_id not in session_store:
        session_store[session_id] = {
            "messages": [],
            "chat_history": [{"role": "system", "content": "다음 나오는 내용은 당신과 내가 나눈 이전 대화입니다.\n"}],
            "thread_id": None,
            "text_lang": text_lang,
        }

    chat_history = session_store[session_id]["chat_history"]

    # 이전 대화를 지침 앞에 붙여 이어 말하게 한다
    chat_text = "\n".join(f"{m['role']}: {m['content']}" for m in chat_history if m["role"] != "system")
    instruction = f"[대화 기록]\n{chat_text}\n\n{instruction}"

    result = await client.responses.create(
        model=chatbot.chatbot_version,
        instructions=instruction,
        input=user_message,
        stream=False,
    )
    full_response = result.output_text

    chat_history.append({"role": "user", "content": user_message})
    chat_history.append({"role": "assistant", "content": full_response})
    session_store[session_id]["chat_history"] = chat_history

    # 첫 발화 때만 대화 로그 행을 만들고 그 ID 를 세션에 기억한다
    if "log_id" not in session_store[session_id]:
        log_id = await chatbot_crud.create_chat_log(db, chatbot_id=chatbot_id, session_id=session_id)
        session_store[session_id]["log_id"] = log_id

    # ... (생략) 발화 저장
    return full_response
