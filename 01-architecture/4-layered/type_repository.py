# 출처: AI 글쓰기 검토 서비스 (2025.08) — 저장소는 DB 쿼리만 담당한다. 함수 이름 규칙(get_/create_/update_/delete_)을 파일 머리에 적어 두었다
from fastapi.responses import JSONResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import data, enums
from app.services.common import utils

# -----------------------------------------------
# CRUD 함수 네이밍 규칙
# - get_*: 데이터 조회
# - create_*: 새 데이터 생성
# - update_*: 기존 데이터 수정
# - delete_*: 데이터 삭제
# - get_*_list : 목록 조회
# - *_*_by_{조건명}: 조건별 필터 조회
# 예: get_user_by_id, create_user, update_user_name, delete_user_by_id
# -----------------------------------------------


async def get_content_type_list(db: Session, company_id: int, page: int, search_term: str, search_type: str, size: int):
    offset = (int(page) - 1) * size

    # content_type 과 category 를 JOIN — 전 테이블에 외래키가 있어 조인이 자연스럽다
    query = (
        db.query(
            data.content_type,
            data.category.title.label("category_title"),
        )
        .outerjoin(data.category, data.content_type.category_id == data.category.id)
        .filter(data.content_type.company_id == company_id)
        .order_by(data.content_type.content_order.desc())
    )

    if search_term != "null":
        like_query = f"%{search_term}%"
        query = query.filter(
            or_(
                data.content_type.title.ilike(like_query),
                data.content_type.description.ilike(like_query),
                data.category.title.ilike(like_query),
            )
        )

    # 상태 컬럼은 Enum 이다 (COMING / INACTIVE / ACTIVE / BEFORE)
    if search_type in ("coming", "inactive", "active", "before"):
        query = query.filter(data.content_type.state == search_type.upper())
    elif search_type == "new":
        query = query.order_by(data.content_type.created_at.desc())
    elif search_type == "old":
        query = query.order_by(data.content_type.created_at.asc())

    total_count = query.count()
    content_type_list = query.offset(offset).limit(size).all()

    contents = []
    for content, category_title in content_type_list:
        content_dict = utils.model_to_dict(content)
        content_dict["category_title"] = category_title
        content_dict["is_method"] = len(content.generation_methods) > 0  # ORM 관계로 자식 개수 확인
        contents.append(content_dict)
    return {"total": total_count, "contents": contents}


async def update_content_type_state(db, id, state):
    target = db.query(data.content_type).filter(data.content_type.id == id).first()
    target.state = enums.ContentTypeStateEnum(state)
    db.commit()


async def get_content_category_list(db, company_id):
    result = db.query(data.category).filter(data.category.company_id == company_id).all()
    contents = [{"id": r.id, "title": r.title} for r in result]
    return {"contents": contents}


async def get_content_type_by_category_id(db, category_id):
    return db.query(data.content_type).filter(data.content_type.category_id == category_id).all()


async def delete_category(db, category_id):
    target = db.query(data.category).filter(data.category.id == category_id).first()
    db.delete(target)
    db.commit()
    return JSONResponse(status_code=200, content={"message": "Delete Category Successful"})


async def create_content_type(db, fileTitle, title, description, company_id, category_title):
    category = db.query(data.category).filter(data.category.title == category_title).first()
    last_row = (
        db.query(data.content_type.content_order)
        .filter(data.content_type.company_id == company_id)
        .order_by(data.content_type.content_order.desc())
        .first()
    )
    last = last_row[0] if last_row else 0
    if db.query(data.content_type).filter(data.content_type.content_order == last + 1).first():
        return 0

    new_content_type = data.content_type(
        icon_title=fileTitle,
        title=title,
        description=description,
        company_id=company_id,
        category_id=category.id,
        content_order=last + 1,
    )
    db.add(new_content_type)
    db.commit()
    return new_content_type.id

# ... (create_content_type_icon, update_content_type, update_content_type_order 생략)
