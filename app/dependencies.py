from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.database import supabase

security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security)
):
    token = credentials.credentials
    try:
        user = supabase.auth.get_user(token)
        if not user or not user.user:
            raise HTTPException(status_code=401, detail="Token inválido")
        return user.user
    except Exception:
        raise HTTPException(status_code=401, detail="No autenticado")

async def require_therapist(user=Security(get_current_user)):
    profile = supabase.table("profiles") \
        .select("role") \
        .eq("id", str(user.id)) \
        .single() \
        .execute()

    if not profile.data or profile.data["role"] != "therapist":
        raise HTTPException(status_code=403, detail="Solo psicólogos pueden acceder")
    return user

async def require_patient(user=Security(get_current_user)):
    profile = supabase.table("profiles") \
        .select("role") \
        .eq("id", str(user.id)) \
        .single() \
        .execute()

    if not profile.data or profile.data["role"] != "patient":
        raise HTTPException(status_code=403, detail="Solo pacientes pueden acceder")
    return user