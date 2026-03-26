from typing import Any

from pydantic import BaseModel


class Asset(BaseModel):
    asset_id: str | None = None
    title: str | None = None
    description: str | None = None
    file_name: str | None = None
    state: str | None = None
    ai_influenced: bool | None = None
    thumbnail_url: str | None = None
    full_url: str | None = None

    @classmethod
    def from_result(cls, raw: dict) -> "Asset":
        return cls(
            asset_id=raw.get("assetId") or raw.get("asset_id"),
            title=(
                raw.get("title")
                or raw.get("fileName")
                or raw.get("file_name")
                or "Untitled asset"
            ),
            description=raw.get("description"),
            file_name=raw.get("fileName") or raw.get("file_name"),
            state=raw.get("state"),
            ai_influenced=raw.get("aiInfluenced")
            if "aiInfluenced" in raw
            else raw.get("ai_influenced"),
            thumbnail_url=raw.get("thumbnailUrl") or raw.get("thumbnail_url"),
            full_url=(
                raw.get("originalSizeUri")
                or raw.get("original_size_uri")
                or raw.get("fullUrl")
                or raw.get("full_url")
                or raw.get("imageUrl")
                or raw.get("image_url")
                or raw.get("thumbnailUrl")
                or raw.get("thumbnail_url")
            ),
        )