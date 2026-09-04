# 출처: 전시관 AI 안내 서비스 (2026.04) — 실시간 통역. 클라이언트 PCM 을 큐에 넣어 Gemini Live 로 흘리고, 돌아오는 번역 음성(바이너리) · 원문 전사 · 번역 전사(JSON)를 한 소켓에 멀티플렉싱
import asyncio
import uuid

from fastapi import WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types as genai_types

from app.core.config.settings import settings
from app.core.logging.context import set_session_id
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

MODAL_LANG_NAMES = {"en": "English", "ja": "Japanese", "zh": "Chinese"}  # ... (생략)


class GeminiLiveService:
    def __init__(self):
        self.client = genai.Client(api_key=settings.gemini_api_key)

    async def translate_ws(self, websocket: WebSocket):
        set_session_id(uuid.uuid4().hex[:8])  # 이 소켓의 모든 로그 줄에 붙는 세션 ID
        lang = websocket.query_params.get("lang", "en")
        await websocket.accept()

        lang_name = MODAL_LANG_NAMES.get(lang, "English")

        # 언어 감지를 따로 하지 않는다 — "한국어면 대상 언어로, 아니면 한국어로" 규칙만 주고 모델에 맡긴다
        system_text = (
            f"You are a real-time interpreter. Rules:\n"
            f"- Korean speech → say the {lang_name} translation\n"
            f"- Any non-Korean speech → say the Korean translation\n"
            f"Ignore filler words and translate only the meaningful content naturally.\n"
            f"Output ONLY the translated words. No explanations."
        )

        config = genai_types.LiveConnectConfig(
            response_modalities=[genai_types.Modality.AUDIO],
            speech_config=genai_types.SpeechConfig(
                voice_config=genai_types.VoiceConfig(
                    prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(voice_name="Kore")
                )
            ),
            system_instruction=genai_types.Content(parts=[genai_types.Part(text=system_text)]),
            # 입력 · 출력 전사를 함께 요청 — 자막 두 줄의 재료
            input_audio_transcription=genai_types.AudioTranscriptionConfig(),
            output_audio_transcription=genai_types.AudioTranscriptionConfig(),
            realtime_input_config=genai_types.RealtimeInputConfig(turn_coverage="TURN_INCLUDES_ONLY_ACTIVITY"),
        )

        # 수신 태스크와 송신 태스크 사이의 완충 — 소켓 수신이 모델 전송 속도에 묶이지 않게
        audio_input_queue: asyncio.Queue = asyncio.Queue()

        async def receive_from_client():
            try:
                while True:
                    msg = await websocket.receive()
                    if "bytes" in msg and msg["bytes"]:
                        await audio_input_queue.put(msg["bytes"])
            except (WebSocketDisconnect, Exception):
                pass

        receive_task = asyncio.create_task(receive_from_client())

        try:
            async with self.client.aio.live.connect(model=settings.gemini_live_model, config=config) as session:

                async def send_audio_loop():
                    try:
                        while True:
                            chunk = await audio_input_queue.get()
                            await session.send_realtime_input(
                                audio=genai_types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
                            )
                    except asyncio.CancelledError:
                        pass

                send_task = asyncio.create_task(send_audio_loop())
                log_buf = {"user": "", "ai": ""}

                try:
                    while True:
                        async for response in session.receive():
                            sc = response.server_content
                            if not sc:
                                continue

                            # (1) 번역 음성 — 바이너리 프레임
                            if sc.model_turn:
                                for part in sc.model_turn.parts:
                                    if part.inline_data:
                                        await websocket.send_bytes(part.inline_data.data)

                            # (2) 원문 전사 — JSON 프레임
                            if sc.input_transcription and sc.input_transcription.text:
                                log_buf["user"] += sc.input_transcription.text
                                await websocket.send_json({"type": "input_text", "text": sc.input_transcription.text})

                            # (3) 번역 전사 — JSON 프레임
                            if sc.output_transcription and sc.output_transcription.text:
                                log_buf["ai"] += sc.output_transcription.text
                                await websocket.send_json({"type": "output_text", "text": sc.output_transcription.text})

                            # (4) 턴 종료 — 토큰 사용량을 함께 보내 원가 집계에 쓴다
                            if sc.turn_complete:
                                if log_buf["user"].strip():
                                    logger.info(f"[USER] {log_buf['user'].strip()}")
                                if log_buf["ai"].strip():
                                    logger.info(f"[AI]   {log_buf['ai'].strip()}")
                                log_buf["user"] = log_buf["ai"] = ""

                                usage = None
                                um = getattr(response, "usage_metadata", None)
                                if um:
                                    usage = {
                                        "input_tokens": getattr(um, "prompt_token_count", 0),
                                        "output_tokens": getattr(um, "candidates_token_count", 0),
                                        "total_tokens": getattr(um, "total_token_count", 0),
                                    }
                                await websocket.send_json({"type": "turn_complete", "usage": usage})

                            # (5) 사용자가 말을 끊음 — 프론트는 재생 중인 음성을 멈춘다
                            if sc.interrupted:
                                log_buf["user"] = log_buf["ai"] = ""
                                await websocket.send_json({"type": "interrupted"})
                finally:
                    send_task.cancel()

        except WebSocketDisconnect:
            pass
        except Exception as e:
            # Live API는 유휴 세션을 1008(policy violation)로 끊는다 — 통역 화면을 켜두고
            # 아무도 말하지 않으면 5~10분 뒤 여기로 온다. 정상 동작이므로 관람객에게
            # 내부 예외 문자열을 그대로 보이면 안 된다.
            code = getattr(e, "code", None)
            recoverable = code in (1006, 1008, 1011, 1012, 1013)
            logger.info(f"[translate_ws] 세션 종료 (code={code}, recoverable={recoverable}): {e}")
            try:
                await websocket.send_json({"type": "error", "message": "연결이 끊어졌습니다. 다시 시도해 주세요.", "recoverable": recoverable})
            except Exception:
                pass
        finally:
            receive_task.cancel()
