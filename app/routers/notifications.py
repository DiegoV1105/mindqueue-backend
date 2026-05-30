from fastapi import APIRouter, Depends
from app.database import supabase
from app.dependencies import get_current_profile

router = APIRouter()

@router.get("/")
async def get_notifications(profile = Depends(get_current_profile)):
    result = supabase.table("notifications") \
        .select("*") \
        .eq("user_id", profile["id"]) \
        .order("created_at", desc=True) \
        .limit(30) \
        .execute()
    return result.data

@router.patch("/read-all")
async def mark_all_read(profile = Depends(get_current_profile)):
    supabase.table("notifications") \
        .update({"is_read": True}) \
        .eq("user_id", profile["id"]) \
        .eq("is_read", False) \
        .execute()
    return {"ok": True}
