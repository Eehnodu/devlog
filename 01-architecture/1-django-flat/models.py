# 출처: AI 상담 챗봇 서비스 (2025.02, 초기 Django 계열) — 외래키 없이 이름 문자열로 연결하고, 파일 ID를 컬럼 20개로 나열한 단일 모델 파일
from django.db import models


class data_chatbot_v1(models.Model):
    """카테고리(=챗봇 한 개) 설정. 학습 파일 ID를 컬럼으로 나열했다."""
    category_name = models.CharField(max_length=255, null=True)
    gpt_version = models.CharField(max_length=255, null=True)  # GPT 버전 체크
    category_sound = models.CharField(max_length=255, null=True)  # 사운드 on/off
    category_data_only = models.CharField(max_length=255, null=True)  # 데이터 only/notonly

    category_data_order = models.TextField(null=True)  # 명령 텍스트
    category_data_text = models.TextField(null=True)  # 데이터 텍스트
    category_msg_nodata = models.TextField(null=True)  # 찾지못할때 메시지

    category_assistant_id = models.CharField(max_length=255, null=True)  # 생성된 어시스턴트 id
    category_assistant_vector_id = models.CharField(max_length=255, null=True)  # 벡터 스토어 id

    # 파일이 몇 개 올라올지 몰라서 컬럼을 20개 만들어 두었다.
    category_assistant_file_id1 = models.CharField(max_length=255, null=True)
    category_assistant_file_id2 = models.CharField(max_length=255, null=True)
    category_assistant_file_id3 = models.CharField(max_length=255, null=True)
    category_assistant_file_id4 = models.CharField(max_length=255, null=True)
    category_assistant_file_id5 = models.CharField(max_length=255, null=True)
    # ... (file_id6 ~ file_id19 같은 형태로 나열, 생략)
    category_assistant_file_id20 = models.CharField(max_length=255, null=True)

    msg_ai_1 = models.CharField(max_length=255, null=True)


class data_chatbot_v1_log(models.Model):
    """대화 로그. 카테고리와는 외래키가 아니라 category_name 문자열로만 연결된다."""
    date_time = models.DateTimeField(null=True)
    category_name = models.CharField(max_length=20, null=True)  # ← FK 아님, 이름 문자열
    gpt_version = models.CharField(max_length=20, null=True)
    user_message = models.CharField(max_length=1000, null=True)
    assistant_message = models.CharField(max_length=10000, null=True)
    history = models.TextField(null=True)  # 대화 전체를 텍스트 한 칸에 계속 이어 붙인다
    evaluate = models.CharField(max_length=20, null=True)


# 같은 구조의 테이블이 "_pt" 접미사로 한 벌 더 있었다(고객사 요청으로 복제).
class data_chatbot_v1_pt(models.Model):
    category_name = models.CharField(max_length=255, null=True)
    gpt_version = models.CharField(max_length=255, null=True)
    category_assistant_id = models.CharField(max_length=255, null=True)
    category_assistant_vector_id = models.CharField(max_length=255, null=True)
    category_assistant_file_id1 = models.CharField(max_length=255, null=True)
    # ... (file_id2 ~ file_id20, 생략)


class data_chatbot_v1_log_pt(models.Model):
    date_time = models.DateTimeField(null=True)
    category_name = models.CharField(max_length=20, null=True)
    history = models.TextField(null=True)
    phone = models.CharField(max_length=20, null=True)
