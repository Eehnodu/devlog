# 출처: AI 상담 챗봇 서비스 (2025.03) — 카테고리 한 행에 어시스턴트 · 벡터 스토어 · 파일 ID 배열을 함께 보관하는 Django 모델
# 이전 버전은 파일 ID 컬럼을 1~20번까지 나열했다. 이 시기에 JSON 배열 두 개(ID · 파일명)로 정리됐다.

from django.db import models


class data_chatbot_v1(models.Model):
    # 외부 자원 ID — 삭제 시 이 값으로 어시스턴트 → 벡터 스토어 → 파일을 차례로 정리한다
    assistant_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    vector_store_id = models.CharField(max_length=255, null=True, blank=True)
    vector_file_ids = models.JSONField(blank=True, null=True)    # 파일 ID 배열
    vector_file_names = models.JSONField(blank=True, null=True)  # 원본 파일명 배열 (화면 표시용)

    category_name = models.CharField(max_length=255, null=True)
    gpt_version = models.CharField(max_length=255, null=True)          # 모델 이름
    category_data_only = models.CharField(max_length=255, null=True)   # only / notonly / only_file
    category_data_order = models.TextField(null=True)                  # 추가 지침
    category_data_text = models.TextField(null=True)                   # 텍스트 자료 (파일 없는 카테고리)
    category_nodata_msg = models.TextField(null=True)                  # 자료에 없을 때 고정 답변
    category_hi_msg = models.CharField(max_length=255, null=True)      # 첫 인사


class data_chatbot_v1_log(models.Model):
    # 이 시기 대화 로그는 한 세션의 문답을 텍스트 한 칸에 누적했다 (세션 · 발화 2계층은 이후 프로젝트에서)
    date_time = models.DateTimeField(null=True)
    category_name = models.CharField(max_length=20, null=True)
    gpt_version = models.CharField(max_length=20, null=True)
    history = models.TextField(null=True)
