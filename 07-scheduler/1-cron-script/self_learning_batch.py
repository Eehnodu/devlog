# 출처: AI 상담 챗봇 서비스 (Django + FastAPI 계열, 2025.05) — 서버 크론이 3일마다 실행하는 독립 스크립트. 웹 서버와 무관하게 Django 를 직접 초기화한다
# 로컬 · 서버 경로가 달라 sys.path 줄을 주석으로 토글했다. 실행 기록은 크론이 텍스트 파일에 이어 붙인다.
import itertools
import json
import os
import sys

import django
from dotenv import load_dotenv
from openai import OpenAI

# 프로젝트 루트 경로 — 서버 · 로컬이 달라 배포할 때마다 한 줄을 주석 처리한다
sys.path.append("/home/ubuntu/app")
# sys.path.append("/home/dev/app")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "chatbotProject.settings")
load_dotenv()
django.setup()  # 웹 서버 없이 ORM 만 쓰기 위한 초기화
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

from django.db import transaction  # noqa: E402
from gpt.models import Chatbot, ChatbotLog  # noqa: E402

# crontab — 3일마다 자정. 표준 출력을 파일에 이어 붙여 실행 기록으로 삼았다
# 0 0 */3 * * /home/ubuntu/venv/bin/python /home/ubuntu/app/gpt/self_learning_batch.py >> /home/ubuntu/app/gpt/self_learning_batch.txt 2>&1


def compare_gpt():
    """카테고리 챗봇 둘씩 짝지어 대화를 시뮬레이션하고, 결과를 누적 학습 데이터에 보탠다."""
    gpt_models = list(Chatbot.objects.all())
    turns = 4

    for model_a, model_b in itertools.combinations(gpt_models, 2):
        # 누적 텍스트 길이 기준으로 main/sub 결정
        text_a = (model_a.category_data_text or "") + (model_a.category_data_accumulated_text or "")
        text_b = (model_b.category_data_text or "") + (model_b.category_data_accumulated_text or "")
        main_model, sub_model = (model_a, model_b) if len(text_a) >= len(text_b) else (model_b, model_a)

        # gpt → 대화 시뮬레이션
        log_id = gpt_to_gpt(main_model, sub_model, turns)

        if log_id:
            finalize_log(main_model, log_id)
            check_accumulated_length_and_finalize(main_model)

            with transaction.atomic():
                model_a.riq = (model_a.riq or 0) + 10
                model_b.riq = (model_b.riq or 0) + 10
                model_a.save()
                model_b.save()


def gpt_to_gpt(main_model, sub_model, turns: int) -> int | None:
    """메인(챗봇 역할) · 서브(사용자 역할) 가 turns 만큼 주고받은 기록을 로그 행에 쌓는다."""
    log = ChatbotLog.objects.create(chatbot=main_model, history="")
    current_question = "안녕하세요, 서비스에 대해 알려주세요."  # 첫 발화 예시

    for i in range(turns * 2):
        is_question_from_main = i % 2 == 1
        responder = main_model if not is_question_from_main else sub_model

        response = client.responses.create(
            model=responder.gpt_version or "gpt-4o",
            input=[
                {"role": "developer", "content": responder.category_data_text or ""},
                {"role": "user", "content": current_question},
            ],
        )
        answer = (response.output_text or "").strip()

        if is_question_from_main:
            log.history += f"[user_message] : {answer}\n"
        else:
            log.history += f"[assistant_message] : {answer}\n"

        current_question = answer  # 다음 질문의 context로 사용
        log.save()

    return log.id


def finalize_log(main_model, log_id):
    """채팅 내역 기반으로 누적 학습 데이터 추가."""
    log = ChatbotLog.objects.get(id=log_id)
    # ... (생략) 대화 기록에서 새로 알게 된 사실만 뽑아 달라는 프롬프트
    response = client.responses.create(model="gpt-4o-mini", instructions="...", input=log.history)
    main_model.category_data_accumulated_text = (
        (main_model.category_data_accumulated_text or "") + "\n---\n" + response.output_text
    )
    main_model.save()


def check_accumulated_length_and_finalize(main_model):
    """누적본이 너무 길어지면 GPT 로 병합 · 압축한다."""
    knowledge_text = main_model.category_data_accumulated_text or ""
    if len(knowledge_text) > 100000:
        call_knowledge_merge_gpt(main_model)


def call_knowledge_merge_gpt(main_model):
    # ... (생략) 중복 항목 통합 · JSON 형식 출력 요구 프롬프트
    try:
        response = client.responses.create(model="gpt-4o-mini", instructions="...", input=" ")
        parsed = json.loads(response.output_text)
        main_model.category_data_accumulated_text = "\n".join(parsed.get("merged_knowledge", []))
        main_model.save()
    except Exception as e:
        print("knowledge 병합 실패:", e)


if __name__ == "__main__":
    from datetime import datetime

    print(f"[run] self_learning_batch.py - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    compare_gpt()
