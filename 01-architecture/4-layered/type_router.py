# 출처: AI 글쓰기 검토 서비스 (2025.08) — 라우터는 HTTP 만 받고 곧바로 서비스에 넘긴다. 인증은 Depends 로 주입
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.admin import type_service
from app.services.common import auth_service

router = APIRouter()


@router.get("/content_types")
async def get_content_type_list(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(auth_service.verify_access_token),
):
    return await type_service.get_content_type_list(request, db)


@router.get("/category_list")
async def get_content_category_list(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(auth_service.verify_access_token),
):
    return await type_service.get_content_category_list(request, db)


@router.post("/change_state")
async def update_content_type_state(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(auth_service.verify_access_token),
):
    return await type_service.update_content_type_state(request, db)


@router.post("/delete_category")
async def delete_category(request: Request, db: Session = Depends(get_db)):
    return await type_service.delete_category(request, db)


@router.post("/save_category")
async def create_category(request: Request, db: Session = Depends(get_db)):
    return await type_service.create_category(request, db)


@router.post("/save_content_type")
async def create_content_type(
    file: Optional[UploadFile] = File(None),
    fileTitle: str = Form(...),
    title: str = Form(...),
    description: str = Form(...),
    company_id: int = Form(...),
    category_title: str = Form(...),
    id: str = Form(...),
    db: Session = Depends(get_db),
):
    return await type_service.create_content_type(
        file, fileTitle, title, description, company_id, category_title, id, db
    )


@router.post("/change_order")
async def update_content_type_order(request: Request, db: Session = Depends(get_db)):
    return await type_service.update_content_type_order(request, db)
