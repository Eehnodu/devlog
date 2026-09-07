# 출처: 팬 플랫폼 서비스 (2026.05~) — 환경별 버킷 값이 비어 있으면 로컬 디스크로 자동 전환되는 설정 · 저장 함수
# 개발 PC 는 버킷 값을 비워 두고, 배포 환경만 채운다. 저장 코드는 한 줄도 갈리지 않는다.
import re
import uuid
from pathlib import Path

from pydantic_settings import BaseSettings

from app.core.utils import s3
from app.core.utils.response import fail


# ---------------- settings.py ----------------
class RawEnv(BaseSettings):
    # ... (생략) DB · JWT · 외부 API 키

    # AWS S3 / CloudFront
    # {env}_s3_bucket 이 비어 있으면 로컬 디스크(MEDIA_ROOT)에 저장한다.
    aws_region: str = "ap-northeast-2"
    local_s3_bucket: str | None = None
    test_s3_bucket: str | None = None
    prod_s3_bucket: str | None = None
    local_cdn_url: str | None = None
    test_cdn_url: str | None = None
    prod_cdn_url: str | None = None


class Settings:
    def __init__(self, raw: RawEnv, env: str, base_dir: Path):
        self.raw = raw
        self.env = env  # 호스트명으로 정해지는 "local" | "test" | "prod"
        self.MEDIA_ROOT = base_dir / "media"

    @property
    def s3_bucket(self) -> str | None:
        """None 이면 로컬 디스크(MEDIA_ROOT) 사용."""
        return getattr(self.raw, f"{self.env}_s3_bucket", None)

    @property
    def cdn_url(self) -> str | None:
        return getattr(self.raw, f"{self.env}_cdn_url", None)


settings: Settings  # 앱 시작 시 한 번 만들어진다 (생략)


# ---------------- file_handler.py ----------------
ALLOWED_EXT = {"jpg", "jpeg", "png", "webp", "gif"}
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25MB — 폰 원본 사진(10~20MB)이 걸리지 않도록

# DB 에 저장되는 경로 prefix. S3 키에도 동일하게 붙는다.
MEDIA_PREFIX = "media/"

_SEGMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
# JS 템플릿 리터럴에 빈 값이 들어갔을 때 생기는 문자열
_BAD_SEGMENTS = {"null", "undefined", "NaN", "0"}


def _safe_subfolder(subfolder: str) -> str:
    cleaned = (subfolder or "").replace("\\", "/").strip().strip("/")
    parts = cleaned.split("/") if cleaned else []
    if not parts or not all(_SEGMENT_RE.fullmatch(p) for p in parts):
        fail("잘못된 저장 경로입니다.", "INVALID_PATH", 400)
    # 프론트에서 `${id}` 가 비어 있으면 "null"/"undefined" 가 그대로 박힌다.
    if any(p in _BAD_SEGMENTS for p in parts):
        fail("저장 경로에 유효하지 않은 값이 있습니다.", "INVALID_PATH", 400)
    return "/".join(parts)


def _local_path(rel_path: str) -> Path:
    """'media/foo/bar.png' → MEDIA_ROOT/foo/bar.png"""
    return settings.MEDIA_ROOT / rel_path[len(MEDIA_PREFIX):]


def _store(subfolder: str, filename: str, data: bytes) -> str:
    """
    S3 또는 로컬 디스크에 저장하고 DB 에 넣을 상대경로를 반환한다.

    반환 예: "media/news/42/image/<uuid>.png"
    """
    rel_path = f"{MEDIA_PREFIX}{_safe_subfolder(subfolder)}/{filename}"

    if s3.is_enabled():  # settings.s3_bucket 이 채워져 있는가
        s3.put_bytes(rel_path, data)
    else:
        dest = _local_path(rel_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

    return rel_path


async def save_image(file, subfolder: str = "image") -> str:
    """UploadFile 을 받아 <subfolder>/ 에 저장하고 상대 경로를 반환한다."""
    if not file.filename:
        fail("파일명이 없습니다.", "INVALID_FILE", 400)

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXT:
        fail("허용되지 않는 확장자입니다.", "INVALID_FILE_EXT", 400)

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        fail("파일 크기가 25MB를 초과합니다.", "FILE_TOO_LARGE", 400)

    return _store(subfolder, f"{uuid.uuid4()}.{ext}", contents)
