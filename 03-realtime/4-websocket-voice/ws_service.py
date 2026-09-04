# 출처: AI 캐릭터 대화 서비스 (2025.12) — WebSocket 한 세션에서 PCM 바이너리 프레임을 모으고, commit 신호에 STT → 페르소나 GPT → TTS 를 돌려 음성(바이너리)과 텍스트(JSON)를 같은 소켓으로 보낸다
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from fastapi import WebSocket, WebSocketDisconnect

from app.module.infra.gpt_service import GPTService


@dataclass
class ConnState:
    """소켓 연결 하나의 상태. 오디오 버퍼는 commit 마다 비운다."""
    session_id: Optional[str] = None
    character_id: Optional[int] = None
    sample_rate: int = 16000
    audio_buffer: bytearray = field(default_factory=bytearray)

    def reset_audio(self) -> None:
        self.audio_buffer = bytearray()


class WSService:
    def __init__(self, db, gpt_service: GPTService):
        self.db = db
        self.gpt_service = gpt_service

    async def handle_binary_frame(self, binary_data: bytes, state: ConnState) -> None:
        # 브라우저가 마이크 PCM 을 잘라 보낸다. 말이 끝날 때까지 쌓기만 한다.
        state.audio_buffer.extend(binary_data)

    async def handle_frame(self, payload: Dict[str, Any], websocket: WebSocket, state: ConnState) -> bool:
        """텍스트(JSON) 프레임 분기. True 를 돌려주면 루프 종료."""
        if "session_id" in payload:
            state.session_id = payload.get("session_id") or state.session_id
        if "character_id" in payload:
            state.character_id = payload.get("character_id")

        msg_type = payload.get("type")
        language = payload.get("language")

        if msg_type == "config":
            state.sample_rate = int(payload.get("sample_rate", state.sample_rate))
            return False
        if msg_type == "commit":  # 사용자가 말을 마쳤다
            return await self._handle_commit(websocket, state, language)
        if msg_type == "chat":  # 텍스트로 입력한 경우 — STT 만 건너뛴다
            await self._process_user_message(websocket, state, payload.get("text", ""), language)
            return False
        if msg_type == "disconnect":
            return True
        return False

    async def _handle_commit(self, websocket: WebSocket, state: ConnState, language: str | None = None) -> bool:
        pcm_bytes = bytes(state.audio_buffer)

        # 1) STT -> user_message
        user_message = ""
        try:
            user_message = await self.gpt_service.stt_openai(pcm_bytes, sample_rate=state.sample_rate)
        except Exception as e:
            print(f"stt_openai 오류: {e}")

        # 2) 공통 파이프라인 처리 (final도 보내는 쪽)
        await self._process_user_message(websocket, state, user_message, language, send_final=True)

        state.reset_audio()
        return False

    async def _process_user_message(
        self, websocket: WebSocket, state: ConnState, user_message: str,
        language: str | None = None, send_final: bool = False,
    ) -> None:
        user_message = (user_message or "").strip()

        if send_final:  # 인식된 사용자 발화를 먼저 화면에 확정
            await websocket.send_text(json.dumps({"type": "final", "text": user_message}, ensure_ascii=False))
        if not user_message:
            return

        # 3) 페르소나 GPT — 대화 기록은 Redis 세션(해시, TTL)에 있다
        gpt_message = await self.gpt_service.send_to_openai(
            message=user_message, session_id=state.session_id, language=language,
        )
        if not gpt_message:
            return
        # 답변은 {"text": ..., "emotion": ...} JSON — 감정은 캐릭터 표정 제어용 메타
        text, emotion = "", "neutral"
        try:
            parsed = json.loads(gpt_message)
            text = parsed.get("text", "") or ""
            emotion = parsed.get("emotion", "neutral") or "neutral"
        except Exception:
            text = gpt_message

        # 4) TTS 생성 + 바이너리 전송 — 오디오는 바이너리 프레임 하나로
        try:
            tts_bytes = await self.gpt_service.tts_elevenlabs(text, state)
            if tts_bytes:
                await websocket.send_bytes(tts_bytes)
        except Exception as e:
            print(f"TTS 전송 중 오류: {e}")

        # 5) 텍스트 reply 전송 — 같은 소켓에 JSON 프레임으로 (자막 · 감정)
        await websocket.send_text(json.dumps({"type": "reply", "text": text, "emotion": emotion}, ensure_ascii=False))

        if state.session_id:
            await self.gpt_service.append_log(
                session_id=state.session_id, character_id=state.character_id,
                user_message=user_message, gpt_message=text,
            )

    async def handle_stt(self, websocket: WebSocket):
        await websocket.accept()
        state = ConnState()

        try:
            while True:
                msg = await websocket.receive()

                if msg["type"] == "websocket.disconnect":
                    break

                if msg["type"] == "websocket.receive":
                    data = msg.get("text") or msg.get("bytes")

                    # 바이너리면 오디오, 텍스트면 JSON 제어 메시지 — 한 소켓에서 둘을 구분
                    if isinstance(data, (bytes, bytearray)):
                        await self.handle_binary_frame(data, state)
                        continue

                    try:
                        payload = json.loads(data)
                    except Exception:
                        continue

                    if await self.handle_frame(payload, websocket, state):
                        break

        except WebSocketDisconnect:
            pass
        finally:
            if state.session_id:
                await self.gpt_service.clear_session(state.session_id)  # Redis 대화 세션 정리
            try:
                await websocket.close()
            except Exception:
                pass
