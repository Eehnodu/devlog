# 출처: 공공기관 상담 챗봇 (2025.02~03) — 프로필 이미지를 base64 문자열로 DB 텍스트 컬럼에 그대로 저장
# Django 모델 + 관리자 저장 뷰. 파일 저장소가 따로 없어 이미지가 DB 행 안에 들어간다.
import json

from django.db import models
from django.http import JsonResponse
from django.views.decorators.http import require_POST


class Chatbot(models.Model):
    assistant_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    vector_store_id = models.CharField(max_length=255, null=True, blank=True)
    company_name = models.CharField(max_length=100)
    profile_name = models.CharField(max_length=100, null=True, blank=True)
    greeting_message = models.TextField(null=True, blank=True)  # 인사 메시지 필드
    guidance_data = models.TextField(null=True, blank=True)  # 지침 데이터 필드
    profile_image = models.TextField(null=True, blank=True)  # base64로 저장될 프로필 이미지 필드
    questions = models.JSONField(null=True, blank=True)  # 주요 질문 리스트
    vector_file_ids = models.JSONField(blank=True, null=True)  # 파일 ID 배열
    vector_file_names = models.JSONField(blank=True, null=True)  # 파일 이름 배열
    created_at = models.DateTimeField(auto_now_add=True)


@require_POST
def save_company_chatbot(request):
    try:
        chatbot_id = request.POST.get("chatbot_id")
        company_name = request.POST.get("company_name")
        profile_name = request.POST.get("profile_name")
        greeting_message = request.POST.get("greeting_message")
        guidance_data = request.POST.get("guidance_data")
        # 브라우저가 파일 입력을 FileReader 로 읽어 data URL 문자열로 보낸다
        profile_image_base64 = request.POST.get("profile_image_base64")

        questions = request.POST.get("questions")
        if questions:
            questions = json.loads(questions)  # JSON 문자열을 리스트로 변환

        # 수정 작업
        if chatbot_id and chatbot_id != "null":
            chatbot = Chatbot.objects.get(id=chatbot_id)
            chatbot.company_name = company_name
            chatbot.profile_name = profile_name
            chatbot.greeting_message = greeting_message
            chatbot.guidance_data = guidance_data
            chatbot.questions = questions

            # 프로필 이미지가 전송된 경우에만 업데이트
            if profile_image_base64:
                chatbot.profile_image = profile_image_base64  # base64로 인코딩된 이미지 저장

            # ... (생략) 학습 파일 업로드 · 벡터 스토어 갱신
            chatbot.save()
        else:
            chatbot = Chatbot.objects.create(
                company_name=company_name,
                profile_name=profile_name,
                greeting_message=greeting_message,
                guidance_data=guidance_data,
                questions=questions,
                profile_image=profile_image_base64,  # 새로 만들 때도 문자열째로
            )

        return JsonResponse({"success": True, "chatbot_id": chatbot.id})
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)


def chatbot_detail(request, chatbot_id):
    """위젯 · 관리자 화면이 챗봇 정보를 받는 조회. 이미지가 응답 JSON 에 통째로 실린다."""
    chatbot = Chatbot.objects.get(id=chatbot_id)
    return JsonResponse(
        {
            "id": chatbot.id,
            "profile_name": chatbot.profile_name,
            "greeting_message": chatbot.greeting_message,
            "profile_image": chatbot.profile_image,  # base64로 인코딩된 프로필 이미지
            "questions": chatbot.questions or [],
        }
    )
