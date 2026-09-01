# 출처: AI 글쓰기 검토 서비스 (2025.08) — 서비스는 요청 본문을 풀고 규칙(사용 중인 카테고리는 삭제 불가 등)을 판단한 뒤 저장소를 부른다
import os
from shutil import copyfileobj

from fastapi.responses import JSONResponse

from app.repository.admin import type_repository


async def get_content_type_list(request, db):
    query_params = request.query_params
    company_id = query_params.get("company_id")
    page = query_params.get("page")
    search_term = query_params.get("search_term")
    search_type = query_params.get("search_type")
    size = 12
    return await type_repository.get_content_type_list(db, company_id, page, search_term, search_type, size)


async def get_content_category_list(request, db):
    company_id = request.query_params.get("company_id")
    return await type_repository.get_content_category_list(db, company_id)


async def update_content_type_state(request, db):
    body = await request.json()
    content_type_id = body.get("id")
    state = body.get("state")
    return await type_repository.update_content_type_state(db, content_type_id, state)


async def delete_category(request, db):
    """비즈니스 규칙: 콘텐츠가 쓰고 있는 카테고리는 지우지 않는다."""
    body = await request.json()
    category_id = body.get("category_id")
    if await type_repository.get_content_type_by_category_id(db, category_id):
        return JSONResponse(status_code=403, content={"message": "Content using category"})
    else:
        return await type_repository.delete_category(db, category_id)


async def create_category(request, db):
    body = await request.json()
    categories = body.get("categories")
    company_id = body.get("company_id")
    return await type_repository.create_category(db, categories, company_id)


async def create_content_type(file, fileTitle, title, description, company_id, category_title, id, db):
    """id 가 0 이면 신규, 아니면 수정. 아이콘 파일은 로컬 media 폴더에 저장한다."""
    try:
        if int(id) == 0:
            new_id = await type_repository.create_content_type(
                db, fileTitle, title, description, company_id, category_title
            )
            if new_id == 0:
                return JSONResponse(status_code=403, content={"message": "Duplicate Content Order"})

            save_dir = os.path.join("app", "media")
            os.makedirs(save_dir, exist_ok=True)
            save_path = os.path.join(save_dir, f"{new_id}.png")
            with open(save_path, "wb") as f:
                copyfileobj(file.file, f)

            status = await type_repository.create_content_type_icon(db, new_id)
            if status == 200:
                return JSONResponse(status_code=200, content={"message": "Content Type Saved Successfully"})
            return JSONResponse(status_code=500, content={"message": "Error While Saving Images"})

        # 수정
        if file:
            save_dir = os.path.join("app", "media")
            os.makedirs(save_dir, exist_ok=True)
            with open(os.path.join(save_dir, f"{id}.png"), "wb") as f:
                copyfileobj(file.file, f)
        return await type_repository.update_content_type(db, fileTitle, title, description, id, category_title)

    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e)})


async def update_content_type_order(request, db):
    body = await request.json()
    target_id = body.get("target_id")
    direction = body.get("direction")
    return await type_repository.update_content_type_order(db, target_id, direction)
