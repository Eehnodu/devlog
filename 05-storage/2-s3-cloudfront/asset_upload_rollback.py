# 출처: AI 캐릭터 대화 서비스 (2025.11~2026.01) — 파일 여러 개를 올리는 요청에서 하나라도 실패하면 이미 올라간 S3 객체를 지우는 롤백
# DB 는 트랜잭션이 되돌려 주지만 S3 는 그렇지 않으므로, 올린 키를 리스트에 모아 두고 except 에서 직접 지운다.
import json
import uuid
from pathlib import Path

from fastapi.responses import JSONResponse

from app.module.asset.asset import AssetCategoryEnum, EmotionEnum, PartColorEnum
from app.module.asset.asset_repository import AssetRepository
from app.module.infra.s3_service import S3Service


class AssetService:
    def __init__(self, repo: AssetRepository, s3_service: S3Service):
        self.repo = repo
        self.s3_service = s3_service

    async def _upload_and_save_part(
        self,
        user_id: int,
        asset_id: int,
        category: AssetCategoryEnum,
        sub_key: str,
        file,
        save_kwargs: dict,
        uploaded_s3_keys: list[str],
    ):
        original_file_name = Path(file.filename).name
        ext = Path(original_file_name).suffix
        file_name = f"{uuid.uuid4().hex}{ext}"  # 원본 파일명은 DB 에만 따로 보관

        s3_key = (
            f"assets/{user_id}/"
            f"{asset_id}/"
            f"{category.value}/"
            f"{sub_key}/"
            f"{file_name}"
        )

        file_bytes = await file.read()
        if not file_bytes:
            return

        self.s3_service.upload_file(
            key=s3_key,
            body=file_bytes,
            content_type=file.content_type,
        )

        uploaded_s3_keys.append(s3_key)  # 성공한 키만 기록 → 실패 시 이만큼만 되돌린다

        await self.repo.save_part(
            asset_id=asset_id,
            category=category,
            file_name=file_name,
            original_file_name=original_file_name,
            **save_kwargs,
        )

    async def save_asset(self, request):
        form = await request.form()
        user_id = request.user_id

        asset_name = form.get("asset_name")
        asset_id = int(form.get("asset_pack_id")) if form.get("asset_pack_id") else None
        asset_parts = json.loads(form.get("asset_parts") or "{}")
        deleted_ids = json.loads(form.get("deleted_part_image_ids") or "[]")

        uploaded_s3_keys: list[str] = []

        try:
            async with self.repo.db.begin():
                # Asset 생성 / 수정
                if asset_id:
                    asset = await self.repo.get_asset_by_id(asset_id)
                    if not asset:
                        return JSONResponse({"ok": False, "message": "Asset not found"}, status_code=404)
                    if asset_name and asset.name != asset_name:
                        await self.repo.update_asset_name(asset_id, asset_name)
                else:
                    asset = await self.repo.save_asset(user_id=user_id, name=asset_name)
                    asset_id = asset.id

                # 삭제 처리 (S3 + DB)
                for part_id in deleted_ids:
                    part = await self.repo.get_part_by_id(part_id)
                    if not part:
                        continue
                    sub_key = part.emotion.value if part.emotion else part.color.value
                    s3_key = f"assets/{user_id}/{asset_id}/{part.category.value}/{sub_key}/{part.file_name}"
                    self.s3_service.delete_file(s3_key)
                    await self.repo.delete_part(part_id)

                # 신규 업로드 — 표정별 파츠
                for part_key, meta in asset_parts.items():
                    if part_key == AssetCategoryEnum.emotion.value:
                        for emotion in meta.get("emotions", []):
                            for file in form.getlist(f"{part_key}_{emotion}"):
                                await self._upload_and_save_part(
                                    user_id=user_id,
                                    asset_id=asset_id,
                                    category=AssetCategoryEnum.emotion,
                                    sub_key=emotion,
                                    file=file,
                                    save_kwargs={"emotion": EmotionEnum(emotion)},
                                    uploaded_s3_keys=uploaded_s3_keys,
                                )
                        continue

                    # 색상별 파츠
                    for color in meta.get("colors", []):
                        for file in form.getlist(f"{part_key}_{color}"):
                            await self._upload_and_save_part(
                                user_id=user_id,
                                asset_id=asset_id,
                                category=AssetCategoryEnum(part_key),
                                sub_key=color,
                                file=file,
                                save_kwargs={"color": PartColorEnum(color)},
                                uploaded_s3_keys=uploaded_s3_keys,
                            )

            return JSONResponse({"ok": True, "asset_id": asset_id})

        except Exception as e:
            # DB 는 begin() 블록이 롤백한다. S3 에 올라간 것은 여기서 직접 지운다.
            for key in uploaded_s3_keys:
                self.s3_service.delete_file(key)
            raise e
