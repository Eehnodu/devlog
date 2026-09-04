# 출처: AI 캐릭터 대화 서비스 (2025.12) — 음성 양끝. PCM 을 WAV 로 감싸 STT 에 넘기고, TTS SDK 의 조각 제너레이터는 별도 실행기에서 모아 단일 바이너리로 만든다
import asyncio
import os
import tempfile
from typing import Optional

from elevenlabs.client import ElevenLabs
from openai import AsyncOpenAI

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
elevenlabs = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))


class GPTService:
    def __init__(self, repo, redis_repo):
        self.repo = repo
        self.redis_repo = redis_repo

    # ... (send_to_openai — 페르소나 프롬프트 + Redis 대화 기록으로 Chat Completions 호출, 생략)

    async def stt_openai(self, pcm_bytes: bytes, sample_rate: int = 16000) -> str:
        """브라우저가 보낸 원시 PCM 을 WAV 헤더로 감싸 임시 파일로 만든 뒤 전사한다."""
        if not pcm_bytes:
            return ""

        tmp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name

            await self._convert_to_wav(tmp_path, pcm_bytes, sample_rate)

            with open(tmp_path, "rb") as f:
                resp = await client.audio.transcriptions.create(
                    model="gpt-4o-mini-transcribe",
                    file=f,
                )

            return (getattr(resp, "text", "") or "").strip()

        except Exception as e:
            print(f"STT 호출 중 오류: {e}")
            return ""

        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    async def tts_elevenlabs(self, text: str, state) -> bytes:
        """캐릭터마다 목소리 ID 가 다르다. SDK 는 동기 제너레이터를 돌려주므로
        이벤트 루프를 막지 않도록 스레드 실행기에서 조각을 모아 bytes 하나로 만든다."""
        text = (text or "").strip()
        if not text:
            return b""

        voice_id = await self.repo.get_character_voice_id(state.character_id)
        try:
            loop = asyncio.get_running_loop()

            def _call_eleven():
                stream = elevenlabs.text_to_speech.convert(
                    voice_id=voice_id,
                    model_id="eleven_multilingual_v2",
                    text=text,
                    output_format="mp3_44100_128",
                    voice_settings={
                        "stability": 0.0,
                        "similarity_boost": 0.85,
                        "style": 0.95,
                        "use_speaker_boost": True,
                    },
                )
                # 조각 제너레이터를 모아 단일 바이너리 프레임으로 — 프론트는 한 번에 재생
                return b"".join(chunk for chunk in stream if chunk)

            tts_bytes: bytes = await loop.run_in_executor(None, _call_eleven)
            return tts_bytes

        except Exception as e:
            print(f"ElevenLabs TTS 호출 중 오류: {e}")
            return b""

    async def _convert_to_wav(self, path: str, pcm_bytes: bytes, sample_rate: int) -> None:
        # ... (ffmpeg 로 s16le PCM → WAV, 생략)
        pass
