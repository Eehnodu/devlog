# 출처: AI 상담 챗봇 서비스 (2025.04, 초기 Django 계열) — 파일 ID 컬럼 20개를 JSON 배열로 바꾸고, 버튼 메뉴를 자기참조 외래키 트리로 만든 첫 스키마 정리
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.db import models
from django.utils import timezone


class data_chatbot_v1(models.Model):
    """카테고리 설정. 파일 ID · 파일명은 JSON 배열 한 칸씩으로, 어시스턴트 ID는 unique."""
    assistant_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    vector_store_id = models.CharField(max_length=255, null=True, blank=True)
    vector_file_ids = models.JSONField(blank=True, null=True)  # 파일 ID 배열 (컬럼 20개 → 배열 1개)
    vector_file_names = models.JSONField(blank=True, null=True)  # 파일 이름 배열
    category_name = models.CharField(max_length=255, null=True)
    gpt_version = models.CharField(max_length=255, null=True)
    category_data_only = models.CharField(max_length=255, null=True)  # 데이터 only/notonly
    category_data_order = models.TextField(null=True)  # 명령 텍스트
    category_data_text = models.TextField(null=True)  # 데이터 텍스트
    category_nodata_msg = models.TextField(null=True)  # 찾지못할때 메시지
    category_hi_msg = models.CharField(max_length=255, null=True)


class data_chatbot_v1_log(models.Model):
    """로그는 아직 이름 문자열 연결 · 텍스트 누적 방식 그대로다."""
    date_time = models.DateTimeField(null=True)
    category_name = models.CharField(max_length=20, null=True)
    gpt_version = models.CharField(max_length=20, null=True)
    user_message = models.CharField(max_length=1000, null=True)
    assistant_message = models.CharField(max_length=10000, null=True)
    history = models.TextField(null=True)


class CustomUserManager(BaseUserManager):
    def create_user(self, user_id, password=None, **extra_fields):
        if not user_id:
            raise ValueError("The User ID field must be set")
        user = self.model(user_id=user_id, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, user_id, password=None, **extra_fields):
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(user_id, password, **extra_fields)


class data_chatbot_user(AbstractBaseUser):
    """관리자 계정. Django 인증 프레임워크 위에 얹었다."""
    user_id = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=255, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_superuser = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    USERNAME_FIELD = "user_id"
    objects = CustomUserManager()

    class Meta:
        db_table = "chatbot_user"


class ChatbotButton(models.Model):
    """버튼 시나리오. 이전에는 뷰 코드에 JSON 으로 하드코딩했던 것을
    부모 버튼 ID 를 참조하는 자기참조 외래키로 옮겼다 — 이 프로젝트의 첫 외래키."""
    BUTTON = 0  # 버튼형
    TEXT = 1  # 텍스트형

    TYPE_CHOICES = (
        (BUTTON, "버튼"),
        (TEXT, "텍스트"),
    )

    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,  # 상위 버튼이 지워지면 하위 트리도 함께
        related_name="children",
    )
    text = models.CharField(max_length=255)  # 버튼 텍스트
    message = models.TextField(blank=True, null=True)  # 콘텐츠 메시지
    url = models.URLField(max_length=500, blank=True, null=True)  # 외부 링크 (선택 사항)
    type = models.IntegerField(choices=TYPE_CHOICES)  # 0: 버튼 / 1: 텍스트

    class Meta:
        db_table = "chatbot_button"
