"""
Endpoints for managing school announcements
"""

from datetime import date
from typing import Any, Dict, List, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from ..database import announcements_collection, teachers_collection

router = APIRouter(
    prefix="/announcements",
    tags=["announcements"]
)


class AnnouncementIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    start_date: Optional[str] = None  # ISO date (YYYY-MM-DD), optional
    expiration_date: str  # ISO date (YYYY-MM-DD), required

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message cannot be blank")
        return value

    @field_validator("start_date", "expiration_date", mode="before")
    @classmethod
    def validate_iso_date(cls, value):
        if value in (None, ""):
            return None
        try:
            date.fromisoformat(value)
        except (TypeError, ValueError):
            raise ValueError("Dates must use the YYYY-MM-DD format")
        return value

    @field_validator("expiration_date")
    @classmethod
    def expiration_required(cls, value):
        if not value:
            raise ValueError("Expiration date is required")
        return value


def _serialize(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "message": doc["message"],
        "start_date": doc.get("start_date"),
        "expiration_date": doc["expiration_date"],
    }


def _require_teacher(teacher_username: Optional[str]) -> None:
    if not teacher_username:
        raise HTTPException(
            status_code=401, detail="Authentication required for this action")
    if not teachers_collection.find_one({"_id": teacher_username}):
        raise HTTPException(
            status_code=401, detail="Invalid teacher credentials")


def _to_object_id(announcement_id: str) -> ObjectId:
    try:
        return ObjectId(announcement_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=404, detail="Announcement not found")


def _validate_range(payload: AnnouncementIn) -> None:
    if payload.start_date and payload.start_date > payload.expiration_date:
        raise HTTPException(
            status_code=400,
            detail="Start date must be on or before the expiration date")


@router.get("", response_model=List[Dict[str, Any]])
def get_active_announcements() -> List[Dict[str, Any]]:
    """Public: announcements that have started (if a start date is set) and not yet expired"""
    today = date.today().isoformat()
    query = {
        "expiration_date": {"$gte": today},
        "$or": [
            {"start_date": None},
            {"start_date": {"$exists": False}},
            {"start_date": {"$lte": today}},
        ],
    }
    docs = announcements_collection.find(query).sort("expiration_date", 1)
    return [_serialize(doc) for doc in docs]


@router.get("/all", response_model=List[Dict[str, Any]])
def get_all_announcements(teacher_username: Optional[str] = Query(None)) -> List[Dict[str, Any]]:
    """Signed-in users: every announcement, including expired and scheduled ones"""
    _require_teacher(teacher_username)
    docs = announcements_collection.find().sort("expiration_date", -1)
    return [_serialize(doc) for doc in docs]


@router.post("", response_model=Dict[str, Any])
def create_announcement(payload: AnnouncementIn, teacher_username: Optional[str] = Query(None)):
    _require_teacher(teacher_username)
    _validate_range(payload)
    doc = payload.model_dump()
    result = announcements_collection.insert_one(doc)
    return _serialize({**doc, "_id": result.inserted_id})


@router.put("/{announcement_id}", response_model=Dict[str, Any])
def update_announcement(announcement_id: str, payload: AnnouncementIn, teacher_username: Optional[str] = Query(None)):
    _require_teacher(teacher_username)
    _validate_range(payload)
    object_id = _to_object_id(announcement_id)
    result = announcements_collection.update_one(
        {"_id": object_id}, {"$set": payload.model_dump()})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")
    return _serialize({**payload.model_dump(), "_id": object_id})


@router.delete("/{announcement_id}")
def delete_announcement(announcement_id: str, teacher_username: Optional[str] = Query(None)):
    _require_teacher(teacher_username)
    result = announcements_collection.delete_one(
        {"_id": _to_object_id(announcement_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")
    return {"message": "Announcement deleted"}
