from fastapi import APIRouter, HTTPException, Depends
from app.database import supabase
from app.models.user import UserRegister, UserLogin, TherapistProfileCreate, ProfileUpdate
from app.dependencies import get_current_user, get_current_profile

router = APIRouter()

@router.post("/register")
async def register(data: UserRegister):
    """
    Registra un nuevo usuario (paciente o psicólogo).
    Supabase Auth crea el usuario y el trigger crea el perfil automáticamente.
    """
    try:
        response = supabase.auth.sign_up({
            "email": data.email,
            "password": data.password,
            "options": {
                "data": {
                    "full_name": data.full_name,
                    "role": data.role,
                }
            }
        })
        if not response.user:
            raise HTTPException(status_code=400, detail="Error al registrar usuario")

        # Actualizar campos adicionales del perfil
        supabase.table("profiles").update({
            "phone": data.phone,
            "city": data.city,
        }).eq("id", str(response.user.id)).execute()

        return {
            "message": "Usuario registrado exitosamente.",
            "user_id": str(response.user.id),
            "role": data.role
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/login")
async def login(data: UserLogin):
    """Login con email y contraseña. Retorna access_token y refresh_token."""
    try:
        response = supabase.auth.sign_in_with_password({
            "email": data.email,
            "password": data.password
        })
        if not response.user:
            raise HTTPException(status_code=401, detail="Credenciales incorrectas")

        # Obtener perfil con rol
        profile_res = supabase.table("profiles") \
            .select("*") \
            .eq("id", str(response.user.id)) \
            .execute()

        if not profile_res.data:
            raise HTTPException(status_code=404, detail="Perfil de usuario no encontrado")
            
        profile = profile_res.data[0]

        return {
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
            "token_type": "bearer",
            "expires_in": response.session.expires_in,
            "user": {
                "id": str(response.user.id),
                "email": response.user.email,
                "role": profile.get("role"),
                "full_name": profile.get("full_name"),
                "avatar_url": profile.get("avatar_url"),
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        print(e)
        if "email not confirmed" in str(e).lower() or "email_not_confirmed" in str(e).lower():
            raise HTTPException(status_code=401, detail="EMAIL_NOT_CONFIRMED")
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")

@router.post("/logout")
async def logout(user = Depends(get_current_user)):
    """Cierra la sesión del usuario."""
    supabase.auth.sign_out()
    return {"message": "Sesión cerrada exitosamente"}

@router.post("/refresh")
async def refresh_token(refresh_token: str):
    """Renueva el access_token usando el refresh_token."""
    try:
        response = supabase.auth.refresh_session(refresh_token)
        return {
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
            "expires_in": response.session.expires_in,
        }
    except Exception:
        raise HTTPException(status_code=401, detail="Refresh token inválido")

@router.get("/me")
async def get_me(profile = Depends(get_current_profile)):
    """Retorna el perfil completo del usuario autenticado."""
    return profile

@router.put("/me")
async def update_profile(
    data: ProfileUpdate,
    user = Depends(get_current_user)
):
    """Actualiza los datos del perfil del usuario autenticado."""
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No hay datos para actualizar")

    result = supabase.table("profiles") \
        .update(update_data) \
        .eq("id", str(user.id)) \
        .execute()
    return result.data[0]

@router.get("/profile/{user_id}")
async def get_user_profile(
    user_id: str,
    profile = Depends(get_current_profile)
):
    """
    Retorna el perfil de un usuario específico.
    Si el solicitante es un psicólogo, verifica que el usuario sea su paciente.
    """
    # Si el usuario pide su propio perfil
    if profile["id"] == user_id:
        return profile

    # Si el solicitante es psicólogo, verificar relación con el paciente
    if profile["role"] == "therapist":
        relation = supabase.table("patient_therapist") \
            .select("id") \
            .eq("patient_id", user_id) \
            .eq("therapist_id", profile["id"]) \
            .eq("status", "active") \
            .execute()

        if not relation.data:
            raise HTTPException(status_code=403, detail="No tienes acceso al perfil de este paciente")
    else:
        # Si no es psicólogo y no es su propio perfil, denegar acceso
        raise HTTPException(status_code=403, detail="No tienes permiso para ver este perfil")

    # Obtener el perfil solicitado
    result = supabase.table("profiles") \
        .select("*") \
        .eq("id", user_id) \
        .execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")

    return result.data[0]

@router.post("/therapist-profile")
async def create_therapist_profile(
    data: TherapistProfileCreate,
    profile = Depends(get_current_profile)
):
    """Crea el perfil extendido del psicólogo (licencia, especialidades, tarifas)."""
    if profile["role"] != "therapist":
        raise HTTPException(status_code=403, detail="Solo psicólogos pueden crear este perfil")

    result = supabase.table("therapist_profiles").upsert({
        "id": profile["id"],
        **data.model_dump()
    }).execute()
    return result.data[0]