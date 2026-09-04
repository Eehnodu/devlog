# 출처: 전시관 AI 안내 서비스 (2026.06) — 용도별 WebSocket 엔드포인트. 프로바이더 주입 · 로그인 데코레이터가 HTTP 와 같은 방식으로 붙는다
from fastapi import APIRouter, WebSocket

from app.core.provider.web_socket.endpoint import with_provider_web_socket
from app.core.provider.web_socket.login import with_login_web_socket, without_login_web_socket
from app.core.provider.web_socket.service import WebSocketProvider

router = APIRouter()


# 키오스크, 모바일 동시통역 — 로그인 없음
@router.websocket("/trans")
@with_provider_web_socket
async def translate_ws(p: WebSocketProvider, websocket: WebSocket):
    await p.gemini_live_service.translate_ws(websocket)


# AI 도슨트 — 작품 설명 Q&A (도구 호출 포함)
@router.websocket("/guide")
@with_provider_web_socket
async def guide_ws(p: WebSocketProvider, websocket: WebSocket):
    await p.gemini_live_service.guide_ws(websocket, p.db)


# 캐릭터 투어 — 전시 전체 순차 안내
@router.websocket("/character")
@with_provider_web_socket
async def character_tour_ws(p: WebSocketProvider, websocket: WebSocket):
    await p.gemini_live_character_service.character_tour_ws(websocket, p.db, p.redis_service)


# 키오스크 가이드 — 시설/전시/기본정보 Q&A (작품 제외)
@router.websocket("/kiosk_guide")
@with_provider_web_socket
async def kiosk_guide_ws(p: WebSocketProvider, websocket: WebSocket):
    await p.gemini_live_kiosk_service.kiosk_guide_ws(websocket, p.db, p.redis_service)


# 1대다 도슨트 채팅 — 도슨트(안내원). 로그인 종류 "docent" 만 통과
@router.websocket("/group_guide_room")
@with_provider_web_socket
@with_login_web_socket("docent")
async def group_guide_room_ws(p: WebSocketProvider, websocket: WebSocket):
    await p.docent_live_service.docent_connect(websocket, p.redis_service, p.gemini_docent_service)


# 1대다 도슨트 채팅 — 방문객. 로그인 없이 방 코드로 입장
@router.websocket("/group_guide_visitor")
@with_provider_web_socket
@without_login_web_socket
async def group_guide_visitor_ws(p: WebSocketProvider, websocket: WebSocket):
    await p.docent_live_service.visitor_connect(websocket, p.redis_service, p.gemini_docent_service)
