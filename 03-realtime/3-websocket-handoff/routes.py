# 출처: AI 상담 챗봇 서비스 (2025.09, Django + FastAPI 계열) — 상담원 핸드오프. 대시보드 · 고객 요청 · 상담원 입장 3종 소켓이 방 ID 로 상태를 공유하고, 다른 상담원이 이미 들어온 방은 4000 코드로 닫는다
from datetime import datetime
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect

from database import SessionLocal
from services import chatbot_log

# 상태 관리 전역 객체 — 프로세스 메모리에 방 상태를 둔다 (단일 워커 전제)
waiting_rooms: Dict[str, Dict[str, str]] = {}  # room_id -> {"uuid": str, "created_at": str}
connected_agents: List[WebSocket] = []  # 대시보드에 붙어 있는 상담사 소켓 목록
room_clients: Dict[str, Dict[str, Optional[WebSocket]]] = {}  # room_id -> {"user": ws, "agent": ws, ...}
active_rooms: Dict[str, str] = {}  # agent_name -> 지금 응대 중인 room_id


def register_websocket_routes(app: FastAPI):

    # ----------------------------
    # 상담사 대기방(대시보드) 소켓 — 대기 중인 방 목록을 실시간으로 받는다
    # ----------------------------
    @app.websocket("/ws/agent/waiting-room/")
    async def agent_socket(websocket: WebSocket, agent_name: str = Query(...)):
        await websocket.accept()
        connected_agents.append(websocket)
        # ... (현재 대기방 목록 전송, "[읽음]" · "[에이전트 입장]" 제어 메시지 처리, 생략)

    # ----------------------------
    # 사용자 소켓 — 챗봇 대화 중 "상담원 연결" 을 누르면 열린다
    # ----------------------------
    @app.websocket("/ws/user/request/")
    async def user_socket(websocket: WebSocket, uuid: str = Query(...), log_id: str = Query(...)):
        await websocket.accept()
        room_id = f"room_{uuid}_{log_id}"  # 방 ID = 사용자 세션 + 챗봇 대화 로그 ID

        if room_id not in waiting_rooms:
            waiting_rooms[room_id] = {
                "uuid": uuid,
                "created_at": datetime.utcnow().replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Asia/Seoul")).isoformat(),
            }

        if room_id not in room_clients:
            room_clients[room_id] = {"user": websocket, "agent": None, "msg_count": 1, "received_first_message": False}
        else:
            room_clients[room_id]["user"] = websocket

        # 상담사들에게 대기방 추가 알림
        for agent_ws in connected_agents[:]:
            try:
                await agent_ws.send_text(f"[대기방 추가] {room_id}|{waiting_rooms[room_id]['created_at']}|0|1")
            except WebSocketDisconnect:
                connected_agents.remove(agent_ws)

        try:
            new_log_id = 0
            while True:
                msg = await websocket.receive_text()

                # 상담사에게 메시지 전달 + DB 저장 (첫 저장에서 받은 로그 행 ID 를 이후 재사용)
                agent_ws = room_clients[room_id]["agent"]
                if agent_ws:
                    with SessionLocal() as db:
                        if new_log_id != 0:
                            chatbot_log.save_user_agent_chat(db, uuid, new_log_id, msg, True)
                        else:
                            new_log_id = chatbot_log.save_user_agent_chat(db, uuid, int(log_id), msg, True)
                    await agent_ws.send_text(msg)
        except WebSocketDisconnect as e:
            print(f"유저 연결 종료: {e.code} {e.reason}")
        finally:
            agent_name = room_clients.get(room_id, {}).get("agent_name", "")
            if room_id in room_clients:
                room_clients[room_id]["user"] = None  # 유저 소켓만 None 처리

            # 대기방 제거 및 알림
            if room_id in waiting_rooms:
                for agent_ws in connected_agents[:]:
                    try:
                        await agent_ws.send_text(f"[대기방 제거] {room_id}")
                    except WebSocketDisconnect:
                        connected_agents.remove(agent_ws)
                active_rooms.pop(agent_name, None)
                waiting_rooms.pop(room_id, None)
                room_clients.pop(room_id, None)

    # ----------------------------
    # 상담사 방 입장 소켓 — 대시보드에서 방을 골라 들어온다
    # ----------------------------
    @app.websocket("/ws/agent/request/")
    async def agent_join_room(websocket: WebSocket, session_id: str = Query(...), agent_name: str = Query(...)):
        await websocket.accept()
        room_id = f"room_{session_id}"

        if room_id not in room_clients:
            room_clients[room_id] = {"user": None, "agent": websocket, "agent_name": agent_name}
        else:
            # 동시 응대 충돌 — 다른 상담사가 이미 들어와 있으면 앱 정의 코드 4000 으로 닫는다
            current_agent = room_clients[room_id].get("agent_name")
            if current_agent and current_agent != agent_name:
                await websocket.close(code=4000, reason="다른 상담사가 이미 입장했습니다.")
                return
            room_clients[room_id]["agent"] = websocket
            room_clients[room_id]["agent_name"] = agent_name

        try:
            new_log_id = 0
            while True:
                msg = await websocket.receive_text()
                user_ws = room_clients[room_id]["user"]

                if msg.startswith("[상담 종료]"):
                    if user_ws:
                        await user_ws.send_text("상담사가 상담을 종료하였습니다.")
                        await user_ws.close()
                    for agent_ws in connected_agents[:]:
                        await agent_ws.send_text(f"[대기방 제거] {room_id}")
                    waiting_rooms.pop(room_id, None)
                    active_rooms.pop(agent_name, None)
                    room_clients.pop(room_id, None)
                    break

                # 일반 상담 메시지 — 사용자에게 전달 + 같은 로그 행에 저장
                if user_ws:
                    uuid = session_id.split("_")[0]
                    log_id = int(session_id.split("_")[-1])
                    with SessionLocal() as db:
                        if new_log_id != 0:
                            chatbot_log.save_user_agent_chat(db, uuid, new_log_id, msg, False, agent_name)
                        else:
                            new_log_id = chatbot_log.save_user_agent_chat(db, uuid, log_id, msg, False, agent_name)
                    await user_ws.send_text(msg)
        except WebSocketDisconnect:
            print("상담사 연결 종료")
        finally:
            room = room_clients.get(room_id)
            if room:
                room["agent"] = None
