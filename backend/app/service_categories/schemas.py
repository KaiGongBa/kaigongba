from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


class CategoryModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class ServiceCategoryRead(CategoryModel):
    id: str
    name: str
    parent_id: str | None
    description: str
    aliases: list[str]
    example_tasks: list[str]
    required_facets: list[str]
    status: str
    version: int
    sort_order: int
    created_at: datetime
    updated_at: datetime


class ServiceCategoryCreate(CategoryModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    name: str = Field(min_length=2, max_length=80)
    parent_id: str | None = Field(default=None, max_length=64)
    description: str = Field(default="", max_length=1000)
    aliases: list[str] = Field(default_factory=list, max_length=30)
    example_tasks: list[str] = Field(default_factory=list, max_length=30)
    required_facets: list[str] = Field(default_factory=list, max_length=30)
    status: str = Field(default="active", pattern=r"^(active|inactive)$")
    sort_order: int = Field(default=0, ge=0, le=1_000_000)


class ServiceCategoryUpdate(CategoryModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    parent_id: str | None = Field(default=None, max_length=64)
    clear_parent: bool = False
    description: str | None = Field(default=None, max_length=1000)
    aliases: list[str] | None = Field(default=None, max_length=30)
    example_tasks: list[str] | None = Field(default=None, max_length=30)
    required_facets: list[str] | None = Field(default=None, max_length=30)
    sort_order: int | None = Field(default=None, ge=0, le=1_000_000)

    @model_validator(mode="after")
    def validate_change(self) -> ServiceCategoryUpdate:
        supplied = self.model_fields_set - {"clear_parent"}
        if not supplied and not self.clear_parent:
            raise ValueError("至少提供一个要更新的字段")
        if self.clear_parent and "parent_id" in self.model_fields_set:
            raise ValueError("clearParent 与 parentId 不能同时提供")
        return self

class ServiceCategoryStatusUpdate(CategoryModel):
    status: str = Field(pattern=r"^(active|inactive)$")


class ServiceCategorySortItem(CategoryModel):
    id: str = Field(min_length=2, max_length=64)
    sort_order: int = Field(ge=0, le=1_000_000)


class ServiceCategoryReorder(CategoryModel):
    items: list[ServiceCategorySortItem] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> ServiceCategoryReorder:
        ids = [item.id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("分类排序列表不能包含重复 ID")
        return self
