# 출처: AI 상담 챗봇 서비스 (2025.06, Django + FastAPI 계열) — 관리자 화면(Django)이 소유한 테이블 정의. 같은 테이블을 FastAPI 쪽 SQLAlchemy 가 다시 정의한다(fastapi_models.py)
from django.db import models


class data_chatbot_v3(models.Model):
    vector_store_id = models.CharField(max_length=255, null=True, blank=True)
    vector_file_ids = models.JSONField(blank=True, null=True)  # 파일 ID 배열
    vector_file_names = models.JSONField(blank=True, null=True)  # 파일 이름 배열
    category_name = models.CharField(max_length=255, null=True)
    gpt_version = models.CharField(max_length=255, null=True)
    category_data_only = models.CharField(max_length=255, null=True)  # 데이터 only/notonly
    category_data_order = models.TextField(null=True)  # 명령 텍스트
    category_data_text = models.TextField(null=True)  # 데이터 텍스트
    category_nodata_msg = models.TextField(null=True)  # 찾지못할때 메시지
    category_hi_msg = models.CharField(max_length=3000, null=True)
    use_gpt_data = models.BooleanField(default=True)  # ← Django 는 불리언


class data_chatbot_v3_log(models.Model):
    date_time = models.DateTimeField(null=True)
    category_name = models.CharField(max_length=20, null=True)
    gpt_version = models.CharField(max_length=20, null=True)
    user_message = models.CharField(max_length=1000, null=True)
    assistant_message = models.CharField(max_length=10000, null=True)
    history = models.TextField(null=True)


class data_chatbot_v3_image(models.Model):
    image_name = models.CharField(max_length=100, blank=True, null=True)
    image_description = models.TextField(max_length=200, null=True, blank=True)
    image_hash = models.CharField(max_length=64, null=True, blank=True)
    chatbot = models.ForeignKey(data_chatbot_v3, on_delete=models.CASCADE, related_name="images")


class data_chatbot_v3_btn(models.Model):
    button_name = models.CharField(max_length=100, null=True)
    product_url = models.URLField(max_length=1000, null=True, blank=True)
    button_keywords = models.JSONField(default=list)
    chatbot = models.ForeignKey(data_chatbot_v3, on_delete=models.CASCADE, related_name="buttons")


class data_chatbot_v3_keyword(models.Model):
    chatbot = models.ForeignKey(data_chatbot_v3, on_delete=models.CASCADE, related_name="keywords")
    keyword = models.CharField(max_length=50)
    # Django 쪽은 이미지가 지워지면 키워드도 함께 지운다(CASCADE).
    # FastAPI 쪽 정의는 같은 컬럼을 SET NULL 로 선언했다 — 두 정의가 어긋난 지점.
    image = models.ForeignKey(data_chatbot_v3_image, on_delete=models.CASCADE, related_name="keywords")
    button = models.CharField(max_length=50, null=True, blank=True)
