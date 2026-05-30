from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.database import supabase
from gotrue.types import User

security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security)
) -> User:
    """Valida el JWT de Supabase y retorna el usuario autenticado."""
    token = credentials.credentials
    try:
        response = supabase.auth.get_user(token)
        if not response or not response.user:
            raise HTTPException(status_code=401, detail="Token inválido o expirado")
        return response.user
    except Exception as e:
        raise HTTPException(status_code=401, detail="No autenticado")

async def get_current_profile(user = Depends(get_current_user)) -> dict:
    """Retorna el perfil completo del usuario autenticado."""
    result = supabase.table("profiles") \
        .select("*") \
        .eq("id", str(user.id)) \
        .execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    return result.data[0]

async def require_therapist(profile = Depends(get_current_profile)) -> dict:
    """Solo permite acceso a psicólogos."""
    if profile.get("role") != "therapist":
        raise HTTPException(status_code=403, detail="Acceso exclusivo para psicólogos")
    return profile

async def require_patient(profile = Depends(get_current_profile)) -> dict:
    """Solo permite acceso a pacientes."""
    if profile.get("role") != "patient":
        raise HTTPException(status_code=403, detail="Acceso exclusivo para pacientes")
    return profile