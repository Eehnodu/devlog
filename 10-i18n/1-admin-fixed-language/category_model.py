# 출처: AI 상담 챗봇 서비스 (2025.03) — 답변 언어를 관리자가 카테고리에 고정하던 시기: 카테고리 행에 언어 컬럼 하나를 추가
# 위젯은 iframe 으로 고객사 페이지에 박혔고, 그 페이지 방문자의 언어를 관리자가 미리 정해 두는 발상이었다.

from django.db import migrations, models


class data_chatbot_v1(models.Model):
    assistant_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    vector_store_id = models.CharField(max_length=255, null=True, blank=True)
    category_name = models.CharField(max_length=255, null=True)
    gpt_version = models.CharField(max_length=255, null=True)
    category_data_only = models.CharField(max_length=255, null=True)
    category_data_order = models.TextField(null=True)     # 추가 지침
    category_hi_msg = models.CharField(max_length=255, null=True)
    # 카테고리 단위 답변 언어 — 관리자 편집 화면의 선택 상자 값이 여기 저장됐다
    lang = models.CharField(max_length=255, null=True)


# 같은 시기의 마이그레이션 — 언어 컬럼은 첫 스키마에 없었고 며칠 뒤 추가됐다
class Migration(migrations.Migration):

    dependencies = [
        ("gpt", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="data_chatbot_v1",
            name="lang",
            field=models.CharField(max_length=255, null=True),
        ),
    ]


# 답변 언어를 지침에 끼워 넣던 자리 (카테고리 값 기준)
def build_language_instruction(db_data) -> dict:
    lang = db_data.lang or "한국어"
    return {
        "role": "system",
        "content": f"너는 고객지원 챗봇이야. 내가 어떤 언어로 물어보든지 {lang}로 대답해줘",
    }
