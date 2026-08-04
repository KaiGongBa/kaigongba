from __future__ import annotations

from fastapi import HTTPException
from sqlmodel import Session, select

from app.db.models import ServiceCategoryCatalog, User, utc_now
from app.security.permissions import require_platform_permission
from app.service_categories.schemas import (
    ServiceCategoryCreate,
    ServiceCategoryRead,
    ServiceCategoryReorder,
    ServiceCategoryStatusUpdate,
    ServiceCategoryUpdate,
)


CATEGORY_MANAGE_PERMISSION = "platform.categories.manage"


def list_categories(
    db: Session,
    current_user: User,
    *,
    include_inactive: bool = False,
    parent_id: str | None = None,
) -> list[ServiceCategoryRead]:
    if include_inactive:
        require_platform_permission(current_user, CATEGORY_MANAGE_PERMISSION)
    statement = select(ServiceCategoryCatalog)
    if not include_inactive:
        statement = statement.where(ServiceCategoryCatalog.status == "active")
    if parent_id == "root":
        statement = statement.where(ServiceCategoryCatalog.parent_id.is_(None))
    elif parent_id is not None:
        statement = statement.where(ServiceCategoryCatalog.parent_id == parent_id)
    rows = db.exec(
        statement.order_by(
            ServiceCategoryCatalog.sort_order,
            ServiceCategoryCatalog.name,
        )
    ).all()
    return [_read(item) for item in rows]


def get_category(
    db: Session,
    current_user: User,
    category_id: str,
) -> ServiceCategoryRead:
    category = db.get(ServiceCategoryCatalog, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="服务分类不存在")
    if category.status != "active":
        require_platform_permission(current_user, CATEGORY_MANAGE_PERMISSION)
    return _read(category)


def create_category(
    db: Session,
    current_user: User,
    request: ServiceCategoryCreate,
) -> ServiceCategoryRead:
    require_platform_permission(current_user, CATEGORY_MANAGE_PERMISSION)
    if db.get(ServiceCategoryCatalog, request.id):
        raise HTTPException(status_code=409, detail="服务分类 ID 已存在")
    _validate_parent(db, request.parent_id, request.id)
    aliases = _normalize_strings(request.aliases, field="aliases")
    _ensure_labels_available(db, request.name, aliases)
    category = ServiceCategoryCatalog(
        id=request.id,
        name=request.name.strip(),
        parent_id=request.parent_id,
        description=request.description.strip(),
        aliases_json=aliases,
        example_tasks_json=_normalize_strings(request.example_tasks, field="exampleTasks"),
        required_facets_json=_normalize_strings(
            request.required_facets, field="requiredFacets"
        ),
        status=request.status,
        version=1,
        sort_order=request.sort_order,
        created_by_user_id=current_user.id,
        updated_by_user_id=current_user.id,
    )
    db.add(category)
    db.commit()
    db.refresh(category)
    return _read(category)


def update_category(
    db: Session,
    current_user: User,
    category_id: str,
    request: ServiceCategoryUpdate,
) -> ServiceCategoryRead:
    require_platform_permission(current_user, CATEGORY_MANAGE_PERMISSION)
    category = _required(db, category_id)
    if request.clear_parent:
        parent_id = None
    elif "parent_id" in request.model_fields_set:
        parent_id = request.parent_id
    else:
        parent_id = category.parent_id
    _validate_parent(db, parent_id, category.id)
    _ensure_no_cycle(db, category.id, parent_id)

    name = request.name.strip() if request.name is not None else category.name
    aliases = (
        _normalize_strings(request.aliases, field="aliases")
        if request.aliases is not None
        else list(category.aliases_json)
    )
    _ensure_labels_available(db, name, aliases, exclude_id=category.id)
    category.name = name
    category.parent_id = parent_id
    if request.description is not None:
        category.description = request.description.strip()
    category.aliases_json = aliases
    if request.example_tasks is not None:
        category.example_tasks_json = _normalize_strings(
            request.example_tasks, field="exampleTasks"
        )
    if request.required_facets is not None:
        category.required_facets_json = _normalize_strings(
            request.required_facets, field="requiredFacets"
        )
    if request.sort_order is not None:
        category.sort_order = request.sort_order
    _touch(category, current_user)
    db.add(category)
    db.commit()
    db.refresh(category)
    return _read(category)


def set_category_status(
    db: Session,
    current_user: User,
    category_id: str,
    request: ServiceCategoryStatusUpdate,
) -> ServiceCategoryRead:
    require_platform_permission(current_user, CATEGORY_MANAGE_PERMISSION)
    category = _required(db, category_id)
    if request.status == "inactive":
        active_child = db.exec(
            select(ServiceCategoryCatalog).where(
                ServiceCategoryCatalog.parent_id == category.id,
                ServiceCategoryCatalog.status == "active",
            )
        ).first()
        if active_child:
            raise HTTPException(status_code=409, detail="请先停用该分类下的活跃子分类")
    if request.status != category.status:
        category.status = request.status
        _touch(category, current_user)
        db.add(category)
        db.commit()
        db.refresh(category)
    return _read(category)


def reorder_categories(
    db: Session,
    current_user: User,
    request: ServiceCategoryReorder,
) -> list[ServiceCategoryRead]:
    require_platform_permission(current_user, CATEGORY_MANAGE_PERMISSION)
    rows = [_required(db, item.id) for item in request.items]
    for row, item in zip(rows, request.items, strict=True):
        if row.sort_order == item.sort_order:
            continue
        row.sort_order = item.sort_order
        _touch(row, current_user)
        db.add(row)
    db.commit()
    for row in rows:
        db.refresh(row)
    return [_read(row) for row in sorted(rows, key=lambda item: (item.sort_order, item.name))]


def resolve_category_for_requirement(
    db: Session,
    *,
    category_id: str | None,
    legacy_category: str,
) -> tuple[str | None, str]:
    """Resolve a new catalog ID while preserving legacy free-text requests."""

    if category_id:
        category = db.get(ServiceCategoryCatalog, category_id)
        if not category or category.status != "active":
            raise HTTPException(status_code=422, detail="请选择有效的服务分类")
        return category.id, category.name

    needle = _label_key(legacy_category)
    if needle:
        matches = [
            row
            for row in db.exec(
                select(ServiceCategoryCatalog).where(ServiceCategoryCatalog.status == "active")
            ).all()
            if needle in {_label_key(row.name), *(_label_key(item) for item in row.aliases_json)}
        ]
        if len(matches) == 1:
            return matches[0].id, matches[0].name
    return None, legacy_category.strip()


def _required(db: Session, category_id: str) -> ServiceCategoryCatalog:
    category = db.get(ServiceCategoryCatalog, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="服务分类不存在")
    return category


def _validate_parent(db: Session, parent_id: str | None, category_id: str) -> None:
    if parent_id is None:
        return
    if parent_id == category_id:
        raise HTTPException(status_code=422, detail="分类不能作为自己的父分类")
    if not db.get(ServiceCategoryCatalog, parent_id):
        raise HTTPException(status_code=422, detail="父分类不存在")


def _ensure_no_cycle(db: Session, category_id: str, parent_id: str | None) -> None:
    seen = {category_id}
    cursor = parent_id
    while cursor:
        if cursor in seen:
            raise HTTPException(status_code=422, detail="分类层级不能形成循环")
        seen.add(cursor)
        parent = db.get(ServiceCategoryCatalog, cursor)
        cursor = parent.parent_id if parent else None


def _ensure_labels_available(
    db: Session,
    name: str,
    aliases: list[str],
    *,
    exclude_id: str | None = None,
) -> None:
    proposed = {_label_key(name), *(_label_key(item) for item in aliases)}
    if "" in proposed or len(proposed) != len(aliases) + 1:
        raise HTTPException(status_code=422, detail="分类名与别名不能为空或重复")
    rows = db.exec(select(ServiceCategoryCatalog)).all()
    for row in rows:
        if row.id == exclude_id:
            continue
        occupied = {_label_key(row.name), *(_label_key(item) for item in row.aliases_json)}
        if proposed.intersection(occupied):
            raise HTTPException(status_code=409, detail="分类名或别名已被使用")


def _normalize_strings(values: list[str], *, field: str) -> list[str]:
    result = list(dict.fromkeys(item.strip() for item in values if item.strip()))
    if len(result) != len(values):
        raise HTTPException(status_code=422, detail=f"{field} 不能包含空值或重复项")
    if any(len(item) > 160 for item in result):
        raise HTTPException(status_code=422, detail=f"{field} 单项过长")
    return result


def _touch(category: ServiceCategoryCatalog, current_user: User) -> None:
    category.version += 1
    category.updated_by_user_id = current_user.id
    category.updated_at = utc_now()


def _label_key(value: str) -> str:
    return "".join(value.casefold().split())


def _read(category: ServiceCategoryCatalog) -> ServiceCategoryRead:
    return ServiceCategoryRead(
        id=category.id,
        name=category.name,
        parent_id=category.parent_id,
        description=category.description,
        aliases=list(category.aliases_json),
        example_tasks=list(category.example_tasks_json),
        required_facets=list(category.required_facets_json),
        status=category.status,
        version=category.version,
        sort_order=category.sort_order,
        created_at=category.created_at,
        updated_at=category.updated_at,
    )
