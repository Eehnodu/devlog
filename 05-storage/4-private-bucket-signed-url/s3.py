# 출처: 복지관 ERP (2026.08) — 비공개 버킷. 열람할 때마다 6시간짜리 서명 URL 을 만들어 준다
# 자격증명은 코드 · .env 에 두지 않고 EC2 인스턴스 역할에서 boto3 가 가져간다.
"""
S3 저장소 래퍼.

`settings.s3_bucket` 이 채워진 환경에서만 쓰인다.
로컬은 버킷이 비어 있어 storage.py 가 디스크로 분기하므로 여기까지 오지 않는다.
"""

import mimetypes
from functools import lru_cache
from urllib.parse import quote

from app.core.config.settings import settings

# 파일명이 uuid라 내용이 바뀌면 키도 바뀐다 → 무한 캐시가 안전하다
CACHE_CONTROL = "public, max-age=31536000, immutable"

# 서명 URL 유효 시간 (초). 목록을 띄워 두고 한참 뒤에 눌러도 되도록 6시간을 준다
URL_TTL_SECONDS = 6 * 3600

# 표준 mimetypes 가 못 맞히거나 틀리게 주는 것만 못박는다.
# 잘못 들어가면 브라우저가 파일을 열지 못하고 다운로드해 버린다.
CONTENT_TYPES = {
    "pdf": "application/pdf",
    "hwp": "application/x-hwp",
    "hwpx": "application/haansofthwpx",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "m4a": "audio/mp4",
    "mp3": "audio/mpeg",
}


def guess_content_type(key: str) -> str:
    ext = key.rsplit(".", 1)[-1].lower() if "." in key else ""
    return (
        CONTENT_TYPES.get(ext)
        or mimetypes.guess_type(key)[0]
        or "application/octet-stream"
    )


@lru_cache(maxsize=1)
def _client():
    # boto3 는 S3 를 실제로 쓸 때만 필요하다.
    # 로컬(디스크 모드)에서 미설치여도 앱이 뜨도록 지연 import 한다.
    import boto3

    return boto3.client("s3", region_name=settings.aws_region)


def is_enabled() -> bool:
    """S3 저장소 사용 여부. False 면 로컬 디스크."""
    return bool(settings.s3_bucket)


def put_bytes(key: str, data: bytes, content_type: str | None = None) -> None:
    """
    ContentType 을 반드시 넣는다. 빠지면 S3 가 application/octet-stream 으로
    내려보내서 브라우저가 파일을 열지 못하고 다운로드만 한다.
    """
    _client().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=data,
        ContentType=content_type or guess_content_type(key),
        CacheControl=CACHE_CONTROL,
    )


def get_bytes(key: str) -> bytes:
    resp = _client().get_object(Bucket=settings.s3_bucket, Key=key)
    return resp["Body"].read()


def delete_key(key: str) -> None:
    _client().delete_object(Bucket=settings.s3_bucket, Key=key)


def object_url(key: str, download_name: str | None = None) -> str:
    """
    브라우저가 파일을 받을 URL.

    버킷은 비공개로 둔다 — 여기 올라가는 건 상담일지 첨부·이용자 서류처럼
    개인정보가 담긴 파일이라, 공개 버킷이면 주소를 아는 사람은 누구나 열 수 있다.
    대신 서명이 붙은 시간제한 URL을 그때그때 만들어 준다.

    만료 시간은 화면을 열어 두고 나중에 눌러도 되도록 넉넉히 잡았다.
    링크를 복사해 밖으로 돌려도 이 시간이 지나면 열리지 않는다.

    download_name을 주면 그 이름으로 내려받게 한다. 저장된 키는 uuid라
    이걸 주지 않으면 '3efe0b66….mp3' 같은 이름으로 저장된다.
    """
    params = {"Bucket": settings.s3_bucket, "Key": key}
    if download_name:
        params["ResponseContentDisposition"] = (
            f"attachment; filename*=UTF-8''{quote(download_name)}"
        )

    return _client().generate_presigned_url(
        "get_object", Params=params, ExpiresIn=URL_TTL_SECONDS
    )


def is_not_found(exc: Exception) -> bool:
    """get_object 예외가 '객체 없음'인지 판별. 권한·네트워크 오류와 구분한다."""
    code = getattr(exc, "response", {}).get("Error", {}).get("Code")
    return code in ("NoSuchKey", "404", "NotFound")
