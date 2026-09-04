# 출처: AI 상담 챗봇 서비스 (2025.09, Django + FastAPI 계열) — 사용자 소켓과 상담원 소켓이 같은 대화 기록 행에 동시에 이어 붙이므로 SELECT ... FOR UPDATE 로 행을 잠근다
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models.chatbot_data import create_chatbot_log_model


def save_user_agent_chat(db: Session, uuid: str, log_id: int, message: str, user: bool, name: str = None) -> int:
    """
    user=True  : 사용자 소켓에서 온 메시지
    user=False : 상담원 소켓에서 온 메시지 (name = 상담원 이름)
    같은 log 행의 history 텍스트에 번갈아 이어 붙인다.
    """
    LogModel = create_chatbot_log_model("gpt_data_chatbot_v1_log")

    if log_id == 0:
        # 상담원이 먼저 인사말을 보낸 경우 — 세션 ID 로 행을 찾고, 없으면 새로 만든다
        if not user and message.startswith("안녕하세요,"):
            log = LogModel(
                date_time=datetime.now(timezone.utc),
                history=f"[notice_message]: 상담사로 전환되었습니다.\n[counselor_message]: {message}\n",
                agent_name=name,
                gpt_version="-",
                session_id=uuid,
            )
            db.add(log)
            db.commit()
            db.refresh(log)
            return log.id

        # 두 소켓이 같은 행을 고칠 수 있으므로 읽는 순간 행 잠금 — 트랜잭션이 끝날 때까지 다른 쪽은 대기
        log = db.query(LogModel).filter(LogModel.session_id == uuid).with_for_update().first()
        if log:
            if message == "[대기방 제거]":
                log.history += "[notice_message]: 사용자가 상담을 종료하였습니다.\n[notice_message]: 챗봇으로 전환됩니다.\n"
            else:
                log.history += f"[user_message]: {message}\n"
            db.commit()
            return log.id
        return 0

    # 챗봇 대화 도중 상담원으로 넘어온 경우 — 기존 챗봇 로그 행을 잠그고 이어 쓴다
    log = db.query(LogModel).filter(LogModel.id == log_id).with_for_update().first()
    if name is not None:
        log.agent_name = name

    if user:
        if message == "[대기방 제거]":
            log.history += "[notice_message]: 사용자가 상담을 종료하였습니다.\n[notice_message]: 챗봇으로 전환됩니다.\n"
        else:
            log.history += f"[user_message]: {message}\n"
    else:
        if message == "[대기방 제거]":
            log.history += "[notice_message]: 상담원이 상담을 종료하였습니다.\n[notice_message]: 챗봇으로 전환됩니다.\n"
        elif message.startswith("안녕하세요,"):
            log.history += f"[notice_message]: 상담사로 전환되었습니다.\n[counselor_message]: {message}\n"
        else:
            log.history += f"[counselor_message]: {message}\n"

    db.commit()
    return log.id
