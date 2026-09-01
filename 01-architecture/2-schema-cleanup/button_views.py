# 출처: AI 상담 챗봇 서비스 (2025.04, 초기 Django 계열) — 자기참조 트리를 부모 ID 로 내려가고(next) 올라가는(back) 뷰. 구조는 여전히 뷰 파일에 직접
from django.http import JsonResponse

from .models import ChatbotButton


def first(request):
    """최상위 버튼 — 부모가 없는 행."""
    buttons = ChatbotButton.objects.filter(parent__isnull=True)
    data = [
        {
            "id": b.id,
            "btn_text": b.text,
            "message": b.message,
        }
        for b in buttons
    ]
    return JsonResponse({"buttons": data})


def next(request, id):
    """선택한 버튼의 하위 버튼 — parent_id 한 번 조회로 끝난다."""
    buttons = ChatbotButton.objects.filter(parent_id=id)
    data = [
        {
            "id": b.id,
            "parent_id": b.parent_id,
            "btn_text": b.text,
            "message": b.message,
            "url": b.url,
            "type": b.type,
        }
        for b in buttons
    ]
    return JsonResponse({"buttons": data})


def back(request, id):
    """현재 목록의 부모로 한 단계 올라간다. 두 단계 위 ID 도 함께 돌려줘서 계속 되돌아갈 수 있게 한다."""
    try:
        current_button = ChatbotButton.objects.get(id=id)
        parent_id = current_button.parent_id  # 현재 목록의 parent_id
    except ChatbotButton.DoesNotExist:
        parent_id = None

    buttons = ChatbotButton.objects.filter(parent_id=parent_id)

    # 이 목록의 상위 parent_id
    upper_parent_id = None
    if parent_id:
        parent_button = ChatbotButton.objects.filter(id=parent_id).first()
        if parent_button:
            upper_parent_id = parent_button.parent_id

    data = [
        {
            "id": b.id,
            "btn_text": b.text,
            "message": b.message,
            "url": b.url,
            "type": b.type,
        }
        for b in buttons
    ]

    return JsonResponse({
        "buttons": data,
        "parent_id": upper_parent_id,  # 상위로 돌아갈 수 있도록
    })
