# 출처: AI 상담 챗봇 서비스 (Django + FastAPI 계열, 2025.04~) — 이미지를 서버 로컬 media 폴더에 저장, 파일명은 내용 해시
# 같은 이미지를 두 번 올리면 해시가 같아 한 번만 저장된다. DB 에는 해시 파일명만 남긴다.
import hashlib
import os

from django.conf import settings

from gpt.models import ChatbotCategory, ChatbotImage, ImageKeyword


def get_file_hash(file):
    hasher = hashlib.md5()
    for chunk in file.chunks():
        hasher.update(chunk)
    return hasher.hexdigest()


def save_category_images(category: ChatbotCategory, image_files, image_metadata):
    """
    image_metadata: [{"image_name": ..., "description": ..., "keyword": "a|b|c"}, ...]
    image_files:    request.FILES.getlist("images") 와 같은 순서
    """
    if not image_files:
        return

    for i, item in enumerate(image_metadata):
        keywords = [k.strip() for k in item["keyword"].split("|") if k.strip()]
        image_name = item["image_name"]
        description = item["description"]
        file = image_files[i]

        # 해시 계산
        image_hash = get_file_hash(file)
        ext = os.path.splitext(file.name)[1].lower()
        relative_path = os.path.join(str(category.id), f"{image_hash}{ext}")  # ex: 12/abc123.png

        absolute_path = os.path.join(settings.MEDIA_ROOT, relative_path)
        os.makedirs(os.path.dirname(absolute_path), exist_ok=True)

        # 파일이 없을 때만 저장 (중복 방지)
        if not os.path.exists(absolute_path):
            with open(absolute_path, "wb") as f:
                for chunk in file.chunks():
                    f.write(chunk)

        image_obj = ChatbotImage.objects.create(
            image_name=image_name,
            image_description=description,
            image_hash=f"{image_hash}{ext}",  # DB 에는 해시 파일명만
            chatbot=category,
        )

        for keyword in keywords:
            ImageKeyword.objects.create(
                chatbot=category,
                keyword=keyword,
                image_id=image_obj.id,
            )


def delete_category_image(category_id: int, old_file_name: str):
    """카테고리 삭제 · 이미지 교체 시 로컬 파일도 함께 지운다."""
    old_file_path = os.path.join(settings.MEDIA_ROOT, str(category_id), old_file_name)
    if os.path.exists(old_file_path):
        os.remove(old_file_path)


# settings.py — 브라우저는 /media/<category_id>/<hash>.png 로 직접 받는다
# MEDIA_URL = "/media/"
# MEDIA_ROOT = os.path.join(BASE_DIR, "media")
