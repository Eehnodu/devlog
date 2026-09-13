# 출처: AI 상담 챗봇 서비스 (2025.03~04) — 고객이 위젯에서 언어를 고르고 요청마다 함께 보낸다. 서버는 그 값을 시스템 메시지에 끼운다
# 카테고리 고정 컬럼은 남아 있지만 더는 읽지 않는다. 언어는 요청 파라미터가 결정한다.

import os

from django.http import JsonResponse
from openai import OpenAI

from .models import data_chatbot_v1

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def index(request):
    if request.method == "POST":
        user_message = request.POST.get("user_message")
        chat_history = request.POST.get("chat_history")
        category_name = request.POST.get("categoryName")
        # 요청마다 오는 언어 값 — 프론트 선택 상자의 표시 이름 그대로 ("English", "日本語" ...)
        lang = request.POST.get("lang")

        # 세션 메시지 초기화
        request.session["message_stream"] = ""
        request.session["messages"] = []
        db_data = data_chatbot_v1.objects.get(category_name=category_name)

        if db_data.category_data_order != "":
            request.session["messages"].append({"role": "system", "content": db_data.category_data_order})

        if db_data.category_data_only == "only":
            request.session["messages"].append(
                {"role": "system", "content": f"입력한 데이터인 'Input Data' 를 기반으로 답변해 줘. Input Data : {db_data.category_data_text}"}
            )
            # ... (생략: 자료에 없을 때의 고정 답변 지침)

        # 답변 언어 — 카테고리 컬럼이 아니라 이번 요청의 값을 쓴다
        request.session["messages"].append(
            {"role": "system", "content": f"너는 고객지원 챗봇이야. 주어진 정보를 활용하여 고객 문의에 응답해줘. 내가 어떤 언어로 물어보든지 {lang}로 대답해줘"}
        )
        request.session["messages"].append({"role": "assistant", "content": db_data.category_hi_msg})
        request.session.modified = True

        if chat_history == "":
            # ... (생략: 최초 진입 초기화 — 첫 인사는 언어와 무관하게 카테고리 값 그대로)
            return JsonResponse({"assistant_message": db_data.category_hi_msg, "chat_history": "true"})

        # ... (생략: 어시스턴트 / Chat Completions 분기, 로그 저장)
        assistant_message = gpt(request, user_message, category_name)
        return JsonResponse({"assistant_message": assistant_message, "chat_history": "true"})

    return JsonResponse({"error": "Invalid request method"}, status=400)


def gpt(request, user_message, category_name):
    request.session["messages"].append({"role": "user", "content": user_message})
    stream = client.chat.completions.create(
        model=request.session["gpt_version"],
        messages=request.session["messages"],   # 언어 지침이 시스템 메시지로 들어 있다
        stream=True,
    )
    message_stream = ""
    for chunk in stream:
        if chunk.choices[0].delta.content is not None:
            message_stream += chunk.choices[0].delta.content
            request.session["message_stream"] = message_stream
            request.session.save()
    # ... (생략: 후처리 · 로그)
    return message_stream
