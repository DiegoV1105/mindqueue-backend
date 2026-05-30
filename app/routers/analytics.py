from fastapi import APIRouter, HTTPException, Depends
from app.database import supabase
from app.dependencies import get_current_profile, require_patient, require_therapist
from app.services.analytics_service import generate_weekly_summary
from datetime import date, timedelta, datetime
import anthropic
import json
from app.config import settings

router = APIRouter()

@router.get("/summary/current")
async def get_current_summary(profile = Depends(require_patient)):
    """Retorna el resumen de la semana actual del paciente."""
    week_start = date.today() - timedelta(days=date.today().weekday())
    result = supabase.table("weekly_summaries") \
        .select("*") \
        .eq("user_id", profile["id"]) \
        .eq("week_start", str(week_start)) \
        .execute()
    return result.data[0] if result.data else None

@router.get("/summary/history")
async def get_summary_history(
    limit: int = 8,
    profile = Depends(get_current_profile)
):
    """Historial de resúmenes semanales (últimas N semanas)."""
    user_id = profile["id"]

    # Si es psicólogo consultando sin patient_id, retornar error
    if profile["role"] == "therapist":
        raise HTTPException(status_code=400, detail="Especifica un patient_id")

    result = supabase.table("weekly_summaries") \
        .select("*") \
        .eq("user_id", user_id) \
        .order("week_start", desc=True) \
        .limit(limit) \
        .execute()
    return result.data

@router.get("/summary/patient/{patient_id}")
async def get_patient_summaries(
    patient_id: str,
    limit: int = 8,
    profile = Depends(get_current_profile)
):
    """El psicólogo consulta los resúmenes de un paciente específico."""
    if profile["role"] != "therapist":
        raise HTTPException(status_code=403, detail="Solo psicólogos")

    relation = supabase.table("patient_therapist") \
        .select("id") \
        .eq("patient_id", patient_id) \
        .eq("therapist_id", profile["id"]) \
        .execute()

    if not relation.data:
        raise HTTPException(status_code=403, detail="Paciente no asignado")

    # Si no hay resumen de la semana actual pero sí hay entradas, generar ahora
    week_start = date.today() - timedelta(days=date.today().weekday())
    existing = supabase.table("weekly_summaries") \
        .select("id") \
        .eq("user_id", patient_id) \
        .eq("week_start", str(week_start)) \
        .execute()

    if not existing.data:
        await generate_weekly_summary(patient_id, week_start)

    result = supabase.table("weekly_summaries") \
        .select("*") \
        .eq("user_id", patient_id) \
        .order("week_start", desc=True) \
        .limit(limit) \
        .execute()

    # Marcar como revisado
    if result.data:
        latest_id = result.data[0]["id"]
        supabase.table("weekly_summaries") \
            .update({"is_reviewed": True}) \
            .eq("id", latest_id) \
            .execute()

    return result.data

@router.post("/summary/generate")
async def trigger_summary_generation(profile = Depends(require_patient)):
    """Genera manualmente el resumen de la semana actual (si hay al menos 3 entradas)."""
    week_start = date.today() - timedelta(days=date.today().weekday())
    result = await generate_weekly_summary(profile["id"], week_start)
    if not result:
        raise HTTPException(status_code=400, detail="No hay entradas esta semana para generar resumen")
    return result

@router.get("/trends/{user_id}")
async def get_trends(
    user_id: str,
    weeks: int = 4,
    profile = Depends(get_current_profile)
):
    """Tendencias de las últimas N semanas para gráficas."""
    # Validar acceso
    if profile["role"] == "patient" and profile["id"] != user_id:
        raise HTTPException(status_code=403, detail="No autorizado")

    result = supabase.table("weekly_summaries") \
        .select("week_start, avg_stress, avg_mood, avg_energy, avg_sleep, alert_level") \
        .eq("user_id", user_id) \
        .order("week_start", desc=True) \
        .limit(weeks) \
        .execute()

    return list(reversed(result.data))  # Orden cronológico para gráficas

@router.get("/comparison/{user_id}")
async def get_weekly_comparison(
    user_id: str,
    profile = Depends(get_current_profile)
):
    """
    Compara las últimas 4 semanas del usuario.
    Útil para la gráfica de tendencias del frontend.
    Muestra deltas: ↑2.1 estrés vs semana anterior.
    """
    # Validar acceso
    if profile["role"] == "patient" and profile["id"] != user_id:
        raise HTTPException(status_code=403, detail="No autorizado")

    summaries = supabase.table("weekly_summaries") \
        .select("week_start, avg_stress, avg_mood, avg_energy, avg_sleep, alert_level, days_recorded") \
        .eq("user_id", user_id) \
        .order("week_start", desc=True) \
        .limit(4) \
        .execute()

    if not summaries.data or len(summaries.data) < 2:
        return {"comparison": None, "message": "No hay suficientes semanas para comparar"}

    current = summaries.data[0]
    previous = summaries.data[1]

    def pct_change(curr, prev):
        if not prev or float(prev) == 0:
            return None
        return round(((float(curr) - float(prev)) / float(prev)) * 100, 1)

    return {
        "current_week":  current,
        "previous_week": previous,
        "deltas": {
            "stress": {
                "absolute": round(float(current["avg_stress"]) - float(previous["avg_stress"]), 2),
                "pct": pct_change(current["avg_stress"], previous["avg_stress"]),
                "direction": "up" if float(current["avg_stress"]) > float(previous["avg_stress"]) else "down"
            },
            "mood": {
                "absolute": round(float(current["avg_mood"]) - float(previous["avg_mood"]), 2),
                "pct": pct_change(current["avg_mood"], previous["avg_mood"]),
                "direction": "up" if float(current["avg_mood"]) > float(previous["avg_mood"]) else "down"
            },
            "energy": {
                "absolute": round(float(current["avg_energy"]) - float(previous["avg_energy"]), 2),
                "direction": "up" if float(current["avg_energy"]) > float(previous["avg_energy"]) else "down"
            },
        },
        "history": list(reversed(summaries.data))  # orden cronológico para gráficas
    }

@router.get("/therapist-insight")
async def get_therapist_weekly_insight(profile = Depends(require_therapist)):
    """
    Genera un insight semanal sobre TODOS los pacientes del psicólogo.
    Responde la pregunta: "¿Cómo está mi práctica esta semana?"
    Se recalcula máximo una vez cada 24 horas.
    """
    # Obtener todos los pacientes
    relations = supabase.table("patient_therapist") \
        .select("patient_id") \
        .eq("therapist_id", profile["id"]) \
        .eq("status", "active") \
        .execute()

    if not relations.data:
        return {"insight": "Aún no tienes pacientes activos.", "generated_at": datetime.now().isoformat()}

    # Obtener resúmenes semanales recientes de todos los pacientes
    patient_ids = [r["patient_id"] for r in relations.data]
    week_start = str(date.today() - timedelta(days=date.today().weekday()))

    summaries_data = []
    for pid in patient_ids:
        profile_r_res = supabase.table("profiles").select("full_name").eq("id", pid).execute()
        profile_r = profile_r_res.data[0] if profile_r_res.data else {}
        
        summary = supabase.table("weekly_summaries") \
            .select("avg_stress,avg_mood,avg_energy,alert_level,patterns,critical_days") \
            .eq("user_id", pid) \
            .gte("week_start", week_start) \
            .execute()

        if summary.data:
            summaries_data.append({
                "nombre": profile_r.get("full_name", "Paciente"),
                "resumen": summary.data[0]
            })

    if not summaries_data:
        return {"insight": "Ningún paciente ha completado su diario esta semana todavía.", "generated_at": datetime.now().isoformat()}

    if not settings.anthropic_api_key:
        return {
            "insight": None,
            "patients_analyzed": len(summaries_data),
            "generated_at": datetime.now().isoformat(),
            "error": "api_key_missing"
        }

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        prompt = f"""
Eres un asistente para un psicólogo clínico.
Analiza los datos de todos sus pacientes esta semana y escribe un resumen ejecutivo
de máximo 3 oraciones para el dashboard. El psicólogo lo leerá en 10 segundos.

Datos de pacientes:
{json.dumps(summaries_data, ensure_ascii=False, indent=2)}

Incluye:
1. Estado general del grupo (una oración)
2. Paciente(s) que requieren atención prioritaria esta semana (menciona nombre si aplica)
3. Una observación positiva si existe

Tono: directo, clínico, útil. Sin presentación ni cierre.
"""

        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=250,
            messages=[{"role": "user", "content": prompt}]
        )

        return {
            "insight": response.content[0].text.strip(),
            "patients_analyzed": len(summaries_data),
            "generated_at": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error al generar insight: {str(e)}")