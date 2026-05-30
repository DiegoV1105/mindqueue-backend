from fastapi import APIRouter, HTTPException, Depends
from app.database import supabase
from app.models.journal import JournalEntryCreate, JournalEntryResponse
from app.dependencies import get_current_profile, require_patient
from app.services.analytics_service import check_and_generate_summary
from app.services.motivation_service import get_motivational_message
from datetime import date, timedelta

router = APIRouter()

@router.post("/entry", response_model=dict)
async def create_journal_entry(
    data: JournalEntryCreate,
    profile = Depends(require_patient)
):
    """
    Crea una entrada del diario emocional para hoy.
    Si el paciente ya llenó 7 días de la semana, genera el resumen automáticamente.
    """
    entry_date = data.entry_date or date.today()

    # Verificar si ya existe entrada para ese día
    existing = supabase.table("journal_entries") \
        .select("id") \
        .eq("user_id", profile["id"]) \
        .eq("entry_date", str(entry_date)) \
        .execute()

    if existing.data:
        raise HTTPException(
            status_code=409,
            detail="Ya existe una entrada para este día. Usa PUT para actualizar."
        )

    entry_data = {
        "user_id": profile["id"],
        "entry_date": str(entry_date),
        "sleep_quality": data.sleep_quality,
        "stress_level": data.stress_level,
        "energy_level": data.energy_level,
        "mood": data.mood,
        "main_situation": data.main_situation,
        "emotions_tags": data.emotions_tags or [],
        "free_text": data.free_text,
    }

    result = supabase.table("journal_entries").insert(entry_data).execute()
    entry = result.data[0]

    # Verificar si se debe generar resumen semanal
    await check_and_generate_summary(profile["id"])

    # Generar mensaje motivador personalizado
    motivational_message = await get_motivational_message(profile["id"], entry)

    # Calcular racha actual para mostrarla en la pantalla de éxito
    streak_result = supabase.table("journal_entries") \
        .select("entry_date") \
        .eq("user_id", profile["id"]) \
        .order("entry_date", desc=True) \
        .limit(60) \
        .execute()

    streak = 0
    today_date = date.today()
    entry_dates = {e["entry_date"] for e in streak_result.data}
    for i in range(60):
        check_date = str(today_date - timedelta(days=i))
        if check_date in entry_dates:
            streak += 1
        else:
            break

    return {
        "entry": entry,
        "message": "Entrada registrada exitosamente",
        "motivational_message": motivational_message,
        "streak": streak
    }

@router.put("/entry/{entry_date}")
async def update_journal_entry(
    entry_date: str,
    data: JournalEntryCreate,
    profile = Depends(require_patient)
):
    """Actualiza la entrada del día especificado."""
    result = supabase.table("journal_entries") \
        .update({
            "sleep_quality": data.sleep_quality,
            "stress_level": data.stress_level,
            "energy_level": data.energy_level,
            "mood": data.mood,
            "main_situation": data.main_situation,
            "emotions_tags": data.emotions_tags or [],
            "free_text": data.free_text,
        }) \
        .eq("user_id", profile["id"]) \
        .eq("entry_date", entry_date) \
        .execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Entrada no encontrada")
    return result.data[0]

@router.get("/entries")
async def get_my_entries(
    limit: int = 30,
    profile = Depends(get_current_profile)
):
    """Retorna las últimas N entradas del usuario autenticado."""
    result = supabase.table("journal_entries") \
        .select("*") \
        .eq("user_id", profile["id"]) \
        .order("entry_date", desc=True) \
        .limit(limit) \
        .execute()
    return result.data

@router.get("/entries/patient/{patient_id}")
async def get_patient_entries(
    patient_id: str,
    limit: int = 30,
    profile = Depends(get_current_profile)
):
    """
    Retorna las entradas de un paciente específico.
    Solo el psicólogo asignado puede consultar esto.
    """
    if profile["role"] != "therapist":
        raise HTTPException(status_code=403, detail="Solo psicólogos pueden ver entradas de pacientes")

    # Verificar que el paciente le pertenece al psicólogo
    relation = supabase.table("patient_therapist") \
        .select("id") \
        .eq("patient_id", patient_id) \
        .eq("therapist_id", profile["id"]) \
        .eq("status", "active") \
        .execute()

    if not relation.data:
        raise HTTPException(status_code=403, detail="Este paciente no está asignado a ti")

    result = supabase.table("journal_entries") \
        .select("*") \
        .eq("user_id", patient_id) \
        .order("entry_date", desc=True) \
        .limit(limit) \
        .execute()
    return result.data

@router.get("/streak")
async def get_streak(profile = Depends(require_patient)):
    """Retorna la racha actual del paciente (días consecutivos llenando el diario)."""
    result = supabase.table("journal_entries") \
        .select("entry_date") \
        .eq("user_id", profile["id"]) \
        .order("entry_date", desc=True) \
        .limit(60) \
        .execute()

    entries = result.data
    if not entries:
        return {"streak": 0, "total_entries": 0}

    streak = 0
    today = date.today()
    entry_dates = {e["entry_date"] for e in entries}

    for i in range(60):
        from datetime import timedelta
        check_date = str(today - timedelta(days=i))
        if check_date in entry_dates:
            streak += 1
        else:
            break

    return {"streak": streak, "total_entries": len(entries)}