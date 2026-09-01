# 출처: AI 상담 챗봇 서비스 (2025.02, 초기 Django 계열) — 뷰 함수 하나가 요청 파싱 · OpenAI 호출 · 세션 조작 · 로그 저장을 전부 한다
import os

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from dotenv import load_dotenv
from openai import OpenAI

from .models import data_chatbot_v1, data_chatbot_v1_log

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


@csrf_exempt
def index(request):
    """POST 하나로 카테고리 초기화 · 사용자 발화 · 답변 생성을 모두 처리한다."""
    if request.method == "POST":
        user_message = request.POST.get("user_message")
        chat_history = request.POST.get("chat_history")
        category_name = request.POST.get("categoryName")

        # 세션 스트림 메시지 초기화 (폴링용)
        request.session["message_stream"] = ""
        request.session.modified = True
        request.session.save()

        # 초기 챗 히스토리 없는경우 (최초 카테고리 선택) 세션 초기화
        if chat_history == "":
            db_data = data_chatbot_v1.objects.get(category_name=category_name)
            request.session["gpt_version"] = db_data.gpt_version
            request.session["messages"] = [
                {"role": "system", "content": db_data.category_data_order},
                {"role": "system", "content": db_data.category_data_text},
            ]
            request.session["log_id"] = ""
            # ... (인사말 반환, 생략)

        assistant_message = gpt(request, user_message, category_name)
        return JsonResponse({"assistant_message": assistant_message})

    # ... (GET 이면 템플릿 렌더링, 생략)


@csrf_exempt
def gpt(request, user_message, category_name):
    """OpenAI 호출과 DB 로그 저장이 한 함수에 있다. 서비스 · 저장소 계층이 없다."""
    request.session["messages"].append({"role": "user", "content": user_message})
    request.session.modified = True

    stream = client.chat.completions.create(
        model=request.session["gpt_version"],
        messages=request.session["messages"],
        stream=True,
    )

    message_stream = ""
    for chunk in stream:
        if chunk.choices[0].delta.content is not None:
            message_stream += chunk.choices[0].delta.content
            request.session["message_stream"] = message_stream
            request.session.modified = True
            request.session.save()  # 청크마다 세션 강제 저장

    request.session["messages"].append({"role": "assistant", "content": message_stream})
    request.session.modified = True
    assistant_message = message_stream

    # 로그 id가 없는경우(최초 로그) — 새 행을 만들고 세션에 id 보관
    if request.session["log_id"] == "":
        history = (
            f"[user_message] : {user_message}\n"
            f"[assistant_message] : {assistant_message}\n"
        )
        log = data_chatbot_v1_log(
            date_time=timezone.now(),
            category_name=category_name,  # FK 없이 이름 문자열로 연결
            gpt_version=request.session["gpt_version"],
            history=history,
        )
        log.save()
        request.session["log_id"] = log.id

    # 두번째 이상 로그 — 기존 history 텍스트 뒤에 이어 붙인다
    else:
        db_data_log = data_chatbot_v1_log.objects.get(id=request.session["log_id"])
        db_data_log.history = (
            db_data_log.history
            + f"[user_message] : {user_message}\n"
            + f"[assistant_message] : {assistant_message}\n"
        )
        db_data_log.save()

    return assistant_message
