# 출처: AI 상담 챗봇 서비스 (2025.06, Django + FastAPI 계열) — 챗봇 응답 서버(FastAPI)가 Django 가 만든 테이블을 테이블 이름을 받아 런타임에 SQLAlchemy 모델로 생성 · 캐싱하는 방식
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

# 버전별(v1, v3 ...) 테이블이 여러 벌 있어서 이름을 받아 모델을 만들고 캐시한다.
_model_cache = {}
_log_model_cache = {}
_keyword_model_cache = {}


def create_chatbot_data_model(tablename: str):
    if tablename in _model_cache:
        return _model_cache[tablename]

    class ChatbotData(Base):
        __tablename__ = tablename
        __table_args__ = {"extend_existing": True}  # 같은 이름으로 다시 선언돼도 오류 없이

        id = Column(Integer, primary_key=True, index=True)
        vector_store_id = Column(String(255), nullable=True)
        vector_file_ids = Column(JSON, nullable=True)
        vector_file_names = Column(JSON, nullable=True)
        category_name = Column(String(255), nullable=True, index=True)
        gpt_version = Column(String(255), nullable=True)
        category_data_only = Column(String(255), nullable=True)
        category_data_order = Column(Text, nullable=True)
        category_data_text = Column(Text, nullable=True)
        category_nodata_msg = Column(Text, nullable=True)
        category_hi_msg = Column(String(255), nullable=True)  # Django 쪽은 3000, 여기는 255
        use_gpt_data = Column(Boolean, nullable=False, default=True)

    _model_cache[tablename] = ChatbotData
    return ChatbotData


def create_chatbot_log_model(tablename: str):
    if tablename in _log_model_cache:
        return _log_model_cache[tablename]

    class ChatbotLog(Base):
        __tablename__ = tablename
        __table_args__ = {"extend_existing": True}

        id = Column(Integer, primary_key=True, index=True)
        date_time = Column(DateTime, default=datetime.utcnow)
        category_name = Column(String(20), nullable=True)
        gpt_version = Column(String(20), nullable=True)
        user_message = Column(String(1000), nullable=True)
        assistant_message = Column(String(10000), nullable=True)
        history = Column(Text, nullable=True)

    _log_model_cache[tablename] = ChatbotLog
    return ChatbotLog


def create_chatbot_keyword_model(
    tablename: str, chatbot_table_name: str, image_table_name: str, button_table_name: str
):
    if tablename in _keyword_model_cache:
        return _keyword_model_cache[tablename]

    class ChatbotKeyword(Base):
        __tablename__ = tablename
        __table_args__ = {"extend_existing": True}

        id = Column(Integer, primary_key=True, index=True)
        chatbot_id = Column(Integer, ForeignKey(f"{chatbot_table_name}.id", ondelete="CASCADE"), nullable=True)
        keyword = Column(String(50), nullable=False)
        # 여기서 CASCADE 와 SET NULL 을 처음 구분해 쓰기 시작했다.
        # 다만 Django 쪽 정의(django_models.py)는 같은 컬럼을 CASCADE 로 두어 서로 어긋난다.
        image_id = Column(Integer, ForeignKey(f"{image_table_name}.id", ondelete="SET NULL"), nullable=True)
        button = Column(String(50), nullable=True)

    _keyword_model_cache[tablename] = ChatbotKeyword
    return ChatbotKeyword


# ---- 서비스 쪽 사용 예 (services/chatbot_data.py) ----
# 조회할 때마다 테이블 이름을 조립해 모델을 꺼내 쓴다.

def get_category_by_name(db, category_name: str, version: str = "v3"):
    tablename = f"gpt_data_chatbot_{version}"  # 예: gpt_data_chatbot_v1, gpt_data_chatbot_v3
    Model = create_chatbot_data_model(tablename)
    return db.query(Model).filter(Model.category_name == category_name).first()


def get_keyword_data(db, category_id: int):
    Model = create_chatbot_keyword_model(
        "gpt_data_chatbot_v3_keyword",
        chatbot_table_name="gpt_data_chatbot_v3",
        image_table_name="gpt_data_chatbot_v3_image",
        button_table_name="gpt_data_chatbot_v3_btn",
    )
    return db.query(Model).filter(Model.chatbot_id == category_id).all()
