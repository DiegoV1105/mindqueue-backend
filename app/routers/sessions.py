from fastapi import APIRouter, HTTPException, Depends
from app.database import supabase
from app.config import settings
from app.models.session import SessionCreate, SessionUpdate
from app.dependencies import get_current_profile, require_therapist
from datetime import datetime, timedelta
from pydantic import BaseModel, EmailStr
import httpx

router = APIRouter()

class LinkPatientRequest(BaseModel):
    patient_email: EmailStr

@router.get("/available-slots/{therapist_id}")
async def get_available_slots(
    therapist_id: str,
    week_start: str,  # formato: YYYY-MM-DD (lunes de la semana)
    profile = Depends(get_current_profile)
):
    """
    Retorna todos los slots disponibles de un psicólogo para una semana dada.
    Descuenta: sesiones ya agendadas + bloqueos manuales.
    El frontend usa esto para construir el calendario visual.
    """
    try:
        week_start_dt = datetime.fromisoformat(week_start)
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido. Usa YYYY-MM-DD")
        
    week_end_dt = week_start_dt + timedelta(days=7)

    # 1. Obtener horario de trabajo del psicólogo
    availability = supabase.table("therapist_availability") \
        .select("*") \
        .eq("therapist_id", therapist_id) \
        .eq("is_active", True) \
        .execute()

    # 2. Obtener sesiones ya agendadas en esa semana
    booked = supabase.table("sessions") \
        .select("scheduled_at, status, patient_id") \
        .eq("therapist_id", therapist_id) \
        .gte("scheduled_at", week_start_dt.isoformat()) \
        .lt("scheduled_at", week_end_dt.isoformat()) \
        .not_.in_("status", ["cancelled"]) \
        .execute()

    booked_times = {s["scheduled_at"] for s in booked.data}

    # 3. Obtener bloqueos manuales
    blocks = supabase.table("availability_blocks") \
        .select("blocked_from, blocked_until, reason") \
        .eq("therapist_id", therapist_id) \
        .lte("blocked_from", week_end_dt.isoformat()) \
        .gte("blocked_until", week_start_dt.isoformat()) \
        .execute()

    # 4. Construir grilla de slots (cada hora, según disponibilidad)
    slots = []
    for day_offset in range(7):
        day = week_start_dt + timedelta(days=day_offset)
        day_of_week = day.weekday()  # 0=lunes, 6=domingo

        # Verificar si el psicólogo trabaja ese día (ajustar si 0=domingo en BD)
        # El SQL dice 0=domingo, 1=lunes. Python weekday() es 0=lunes, 6=domingo.
        # Ajuste: (day.weekday() + 1) % 7 para que 0 sea Domingo
        db_day_of_week = (day.weekday() + 1) % 7
        
        day_schedule = next(
            (a for a in availability.data if a["day_of_week"] == db_day_of_week),
            None
        )
        if not day_schedule:
            continue

        # Generar slots por hora
        start_hour = int(day_schedule["start_time"].split(":")[0])
        end_hour   = int(day_schedule["end_time"].split(":")[0])

        for hour in range(start_hour, end_hour):
            slot_dt = day.replace(hour=hour, minute=0, second=0, microsecond=0)
            slot_iso = slot_dt.isoformat()

            # Verificar si está bloqueado manualmente
            is_blocked = any(
                b["blocked_from"] <= slot_iso < b["blocked_until"]
                for b in blocks.data
            )

            # Determinar estado del slot
            if slot_iso in booked_times:
                session_info = next(s for s in booked.data if s["scheduled_at"] == slot_iso)
                status = "booked"
                patient_id = session_info["patient_id"]
            elif is_blocked:
                status = "blocked"
                patient_id = None
            else:
                status = "available"
                patient_id = None

            slots.append({
                "datetime": slot_iso,
                "status": status,
                "patient_id": patient_id,
                "day_of_week": db_day_of_week,
                "hour": hour,
            })

    return {"slots": slots, "week_start": week_start}

@router.post("/")
async def create_session(
    data: SessionCreate,
    profile = Depends(require_therapist)
):
    """
    Agenda una sesión. Verifica conflictos antes de insertar.
    Si hay conflicto, retorna 409 con los próximos 3 horarios disponibles.
    """
    # 1. Verificar conflicto de horario
    conflict = supabase.table("sessions") \
        .select("id, patient_id") \
        .eq("therapist_id", profile["id"]) \
        .eq("scheduled_at", data.scheduled_at.isoformat()) \
        .not_.in_("status", ["cancelled"]) \
        .execute()

    if conflict.data:
        # Buscar próximos 3 slots disponibles
        next_slots = await find_next_available_slots(
            profile["id"],
            data.scheduled_at,
            count=3
        )
        raise HTTPException(
            status_code=409,
            detail={
                "error": "SLOT_CONFLICT",
                "message": "Este horario ya está ocupado.",
                "next_available": next_slots
            }
        )

    # 2. Verificar que el paciente está asignado
    relation = supabase.table("patient_therapist") \
        .select("id") \
        .eq("patient_id", data.patient_id) \
        .eq("therapist_id", profile["id"]) \
        .eq("status", "active") \
        .execute()

    if not relation.data:
        raise HTTPException(status_code=403, detail="Paciente no asignado a ti")

    # 3. Insertar sesión
    try:
        result = supabase.table("sessions").insert({
            "patient_id":     data.patient_id,
            "therapist_id":   profile["id"],
            "scheduled_at":   data.scheduled_at.isoformat(),
            "duration_min":   data.duration_min,
            "meet_link":      data.meet_link,
            "session_goals":  data.session_goals,
            "summary_id":     data.summary_id,
            "status":         "scheduled"
        }).execute()
    except Exception as e:
        # El UNIQUE INDEX de la BD también protege (doble barrera)
        if "no_overlap_therapist" in str(e):
            raise HTTPException(status_code=409, detail={"error": "SLOT_CONFLICT", "message": "Conflicto de horario detectado."})
        raise

    session = result.data[0]

    # 4. Notificar al paciente
    supabase.table("notifications").insert({
        "user_id":     data.patient_id,
        "type":        "session_scheduled",
        "title":       "Nueva sesión agendada",
        "message":     f"Tienes una sesión agendada para {data.scheduled_at.strftime('%d/%m/%Y a las %H:%M')}",
        "action_url":  f"/patient/sessions",
        "metadata":    {"session_id": session["id"]}
    }).execute()

    return session

async def find_next_available_slots(therapist_id: str, from_dt: datetime, count: int = 3) -> list:
    """Encuentra los próximos N slots disponibles después de una fecha dada."""
    slots = []
    check_dt = from_dt + timedelta(hours=1)

    for _ in range(48):  # buscar hasta 48 horas hacia adelante
        # Verificar si ese slot está disponible
        conflict = supabase.table("sessions") \
            .select("id") \
            .eq("therapist_id", therapist_id) \
            .eq("scheduled_at", check_dt.isoformat()) \
            .not_.in_("status", ["cancelled"]) \
            .execute()

        if not conflict.data and 8 <= check_dt.hour <= 18 and check_dt.weekday() < 6:
            slots.append(check_dt.isoformat())

        if len(slots) >= count:
            break

        check_dt += timedelta(hours=1)

    return slots

@router.post("/availability")
async def set_availability(
    schedule: list,  # [{"day_of_week": 1, "start_time": "08:00", "end_time": "18:00"}]
    profile = Depends(require_therapist)
):
    """El psicólogo configura su horario de trabajo semanal."""
    # Eliminar disponibilidad anterior
    supabase.table("therapist_availability") \
        .delete() \
        .eq("therapist_id", profile["id"]) \
        .execute()

    # Insertar nueva disponibilidad
    records = [
        {
            "therapist_id": profile["id"],
            "day_of_week":  s["day_of_week"],
            "start_time":   s["start_time"],
            "end_time":     s["end_time"],
        }
        for s in schedule
    ]

    result = supabase.table("therapist_availability").insert(records).execute()
    return {"message": "Disponibilidad actualizada", "schedule": result.data}

@router.post("/block")
async def block_time(
    blocked_from: datetime,
    blocked_until: datetime,
    reason: str = None,
    profile = Depends(require_therapist)
):
    """El psicólogo bloquea un rango de tiempo (vacaciones, reuniones, etc.)."""
    result = supabase.table("availability_blocks").insert({
        "therapist_id":  profile["id"],
        "blocked_from":  blocked_from.isoformat(),
        "blocked_until": blocked_until.isoformat(),
        "reason":        reason,
    }).execute()
    return result.data[0]

@router.get("/my-sessions")
async def get_my_sessions(
    status: str = None,
    profile = Depends(get_current_profile)
):
    """Retorna las sesiones del usuario (paciente o psicólogo)."""
    field = "therapist_id" if profile["role"] == "therapist" else "patient_id"

    query = supabase.table("sessions") \
        .select("*, profiles!sessions_patient_id_fkey(full_name, avatar_url)") \
        .eq(field, profile["id"]) \
        .order("scheduled_at", desc=True)

    if status:
        query = query.eq("status", status)

    result = query.execute()

    # Si es paciente, filtrar therapist_notes
    if profile["role"] == "patient":
        for session in result.data:
            session.pop("therapist_notes", None)

    return result.data

@router.put("/{session_id}")
async def update_session(
    session_id: str,
    data: SessionUpdate,
    profile = Depends(get_current_profile)
):
    """Actualiza una sesión. Las notas clínicas solo las puede editar el psicólogo."""
    update_data = {k: v for k, v in data.model_dump().items() if v is not None}

    # Paciente solo puede actualizar su feedback
    if profile["role"] == "patient":
        allowed = {"patient_feedback"}
        update_data = {k: v for k, v in update_data.items() if k in allowed}

    if not update_data:
        raise HTTPException(status_code=400, detail="No hay datos para actualizar")

    result = supabase.table("sessions") \
        .update(update_data) \
        .eq("id", session_id) \
        .execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    session = result.data[0]
    if profile["role"] == "patient":
        session.pop("therapist_notes", None)

    return session

@router.post("/link-patient")
async def link_patient(
    data: LinkPatientRequest,
    profile = Depends(require_therapist)
):
    """Vincula un paciente al psicólogo por email. Crea la relación en patient_therapist."""
    # Use Supabase admin REST API directly — more reliable than the gotrue-py SDK admin methods
    try:
        resp = httpx.get(
            f"{settings.supabase_url}/auth/v1/admin/users",
            headers={
                "apikey": settings.supabase_service_key,
                "Authorization": f"Bearer {settings.supabase_service_key}",
            },
            params={"filter": data.patient_email, "per_page": 10},
            timeout=10,
        )
        resp.raise_for_status()
        users = resp.json().get("users", [])
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=500, detail=f"Error al consultar usuarios: {e.response.status_code}")
    except Exception:
        raise HTTPException(status_code=500, detail="Error al buscar usuario")

    patient_auth = next(
        (u for u in users if u.get("email", "").lower() == data.patient_email.lower()),
        None,
    )

    if not patient_auth:
        raise HTTPException(status_code=404, detail="No existe un usuario con ese email")

    patient_id = patient_auth.get("id")

    if patient_id == profile["id"]:
        raise HTTPException(status_code=400, detail="No puedes vincularte a ti mismo")

    patient_profile = supabase.table("profiles") \
        .select("id, full_name, role") \
        .eq("id", patient_id) \
        .execute()

    if not patient_profile.data or patient_profile.data[0]["role"] != "patient":
        raise HTTPException(status_code=400, detail="Este usuario no tiene un perfil de paciente")

    existing = supabase.table("patient_therapist") \
        .select("id, status") \
        .eq("patient_id", patient_id) \
        .eq("therapist_id", profile["id"]) \
        .execute()

    if existing.data:
        if existing.data[0]["status"] == "active":
            raise HTTPException(status_code=400, detail="Este paciente ya está vinculado a tu cuenta")
        supabase.table("patient_therapist") \
            .update({"status": "active"}) \
            .eq("id", existing.data[0]["id"]) \
            .execute()
    else:
        supabase.table("patient_therapist").insert({
            "patient_id":   patient_id,
            "therapist_id": profile["id"],
            "status":       "active"
        }).execute()

    return {"message": "Paciente vinculado exitosamente", "patient": patient_profile.data[0]}


@router.get("/patients")
async def get_my_patients(profile = Depends(require_therapist)):
    """Retorna la lista de pacientes activos del psicólogo con su último estado emocional."""
    relations = supabase.table("patient_therapist") \
        .select("patient_id, status") \
        .eq("therapist_id", profile["id"]) \
        .eq("status", "active") \
        .execute()

    if not relations.data:
        return []

    patient_ids = [r["patient_id"] for r in relations.data]

    # 4 queries en batch en lugar de N×3 queries secuenciales
    profiles_res = supabase.table("profiles") \
        .select("id, full_name, avatar_url, city") \
        .in_("id", patient_ids) \
        .execute()

    summaries_res = supabase.table("weekly_summaries") \
        .select("user_id, avg_stress, avg_mood, alert_level, week_start, is_reviewed, days_recorded") \
        .in_("user_id", patient_ids) \
        .order("week_start", desc=True) \
        .execute()

    entries_res = supabase.table("journal_entries") \
        .select("user_id, entry_date, mood, stress_level") \
        .in_("user_id", patient_ids) \
        .order("entry_date", desc=True) \
        .execute()

    profiles_map = {p["id"]: p for p in profiles_res.data}

    # Primera ocurrencia = más reciente (ya viene ordenado desc)
    summaries_map = {}
    for s in summaries_res.data:
        summaries_map.setdefault(s["user_id"], s)

    entries_map = {}
    for e in entries_res.data:
        entries_map.setdefault(e["user_id"], e)

    return [
        {
            "profile":      profiles_map[pid],
            "last_summary": summaries_map.get(pid),
            "last_entry":   entries_map.get(pid),
        }
        for pid in patient_ids
        if pid in profiles_map
    ]
