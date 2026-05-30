import pandas as pd
import numpy as np
from scipy import stats
from collections import Counter
from datetime import date, timedelta
from typing import Optional
from app.database import supabase

# ============================================================
# FUNCIÓN PRINCIPAL: genera el resumen semanal completo
# ============================================================

async def check_and_generate_summary(user_id: str):
    """
    Genera (o regenera) el resumen semanal después de cada entrada.
    Con 1 entrada ya se produce un resumen básico que permite seguimiento inmediato.
    """
    week_start = date.today() - timedelta(days=date.today().weekday())
    week_end = week_start + timedelta(days=6)

    entries = supabase.table("journal_entries") \
        .select("*") \
        .eq("user_id", user_id) \
        .gte("entry_date", str(week_start)) \
        .lte("entry_date", str(week_end)) \
        .execute()

    if len(entries.data) >= 1:
        await generate_weekly_summary(user_id, week_start, entries.data)

async def generate_weekly_summary(
    user_id: str,
    week_start: date,
    entries: list = None
) -> Optional[dict]:
    """
    Genera el resumen semanal completo usando pandas + scipy.
    Sin dependencias externas. Funciona offline.
    """
    week_end = week_start + timedelta(days=6)

    if entries is None:
        result = supabase.table("journal_entries") \
            .select("*") \
            .eq("user_id", user_id) \
            .gte("entry_date", str(week_start)) \
            .lte("entry_date", str(week_end)) \
            .order("entry_date") \
            .execute()
        entries = result.data

    if len(entries) < 1:
        return None

    # Convertir a DataFrame para análisis
    df = pd.DataFrame(entries)
    df["entry_date"] = pd.to_datetime(df["entry_date"])
    df = df.sort_values("entry_date").reset_index(drop=True)
    df["day_index"] = range(len(df))  # índice numérico para regresión

    # ─── ESTADÍSTICAS BASE ───────────────────────────────────
    stats_data = compute_base_stats(df)

    # ─── TENDENCIAS (regresión lineal) ───────────────────────
    trends = compute_trends(df)

    # ─── PATRONES EMOCIONALES ────────────────────────────────
    patterns = detect_patterns(df, trends)

    # ─── FRECUENCIA DE EMOCIONES ─────────────────────────────
    emotions_freq = compute_emotion_frequency(df)

    # ─── DÍAS CRÍTICOS ───────────────────────────────────────
    critical_days = identify_critical_days(df)

    # ─── NIVEL DE ALERTA ─────────────────────────────────────
    alert_level = calculate_alert_level(stats_data, critical_days, patterns, trends)

    # ─── TEXTO NARRATIVO ─────────────────────────────────────
    summary_text = build_narrative_text(
        stats_data, trends, patterns, emotions_freq,
        critical_days, alert_level, len(entries)
    )

    # ─── COMPARACIÓN CON SEMANA ANTERIOR ─────────────────────
    comparison = await compute_week_comparison(user_id, week_start, stats_data)

    # Días de semana registrados (0=lunes … 6=domingo), para mostrar cuadrículas exactas en frontend
    recorded_days = sorted(df["entry_date"].dt.dayofweek.tolist())

    # Guardar en BD
    summary_data = {
        "user_id":        user_id,
        "week_start":     str(week_start),
        "week_end":       str(week_end),
        "days_recorded":  len(entries),
        "recorded_days":  recorded_days,
        "avg_stress":    stats_data["avg_stress"],
        "avg_mood":      stats_data["avg_mood"],
        "avg_energy":    stats_data["avg_energy"],
        "avg_sleep":     stats_data["avg_sleep"],
        "max_stress":    stats_data["max_stress"],
        "min_mood":      stats_data["min_mood"],
        "critical_days": critical_days,
        "patterns":      {**patterns, "trends": trends, "comparison": comparison},
        "emotions_freq": emotions_freq,
        "summary_text":  summary_text,
        "alert_level":   alert_level,
    }

    result = supabase.table("weekly_summaries").upsert(summary_data).execute()

    await notify_therapist_new_summary(user_id, alert_level)

    return result.data[0] if result.data else None


# ============================================================
# ESTADÍSTICAS BASE
# ============================================================

def compute_base_stats(df: pd.DataFrame) -> dict:
    """Calcula promedios, máximos, mínimos y desviación estándar."""
    return {
        "avg_stress":  round(df["stress_level"].mean(), 2),
        "avg_mood":    round(df["mood"].mean(), 2),
        "avg_energy":  round(df["energy_level"].mean(), 2),
        "avg_sleep":   round(df["sleep_quality"].mean(), 2),
        "max_stress":  int(df["stress_level"].max()),
        "min_mood":    int(df["mood"].min()),
        "max_energy":  int(df["energy_level"].max()),
        "std_stress":  round(float(df["stress_level"].std(ddof=0)), 2),
        "std_mood":    round(float(df["mood"].std(ddof=0)), 2),
    }


# ============================================================
# TENDENCIAS (regresión lineal con scipy)
# ============================================================

def compute_trends(df: pd.DataFrame) -> dict:
    """
    Calcula si cada métrica está subiendo, bajando o estable
    usando regresión lineal sobre los días de la semana.

    slope > 0 = sube, slope < 0 = baja
    p_value < 0.05 = estadísticamente significativo
    """
    trends = {}
    metrics = {
        "stress": "stress_level",
        "mood":   "mood",
        "energy": "energy_level",
        "sleep":  "sleep_quality",
    }

    x = df["day_index"].values

    for name, col in metrics.items():
        y = df[col].values
        if len(y) < 3:
            trends[name] = {"direction": "stable", "slope": 0, "significant": False}
            continue

        slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)

        # Determinar dirección
        # Un cambio de 1 punto en 7 días es significativo clínicamente
        if abs(slope) < 0.15:
            direction = "stable"
        elif slope > 0:
            direction = "increasing"
        else:
            direction = "decreasing"

        # Cambio total estimado de inicio a fin de semana
        total_change = slope * (len(y) - 1)

        trends[name] = {
            "direction":    direction,
            "slope":        round(slope, 3),
            "total_change": round(total_change, 2),
            "significant":  p_value < 0.1,  # umbral más permisivo para muestras pequeñas
            "r_squared":    round(r_value ** 2, 3),
        }

    return trends


# ============================================================
# DETECCIÓN DE PATRONES
# ============================================================

def detect_patterns(df: pd.DataFrame, trends: dict) -> dict:
    """
    Detecta patrones clínicamente relevantes.
    Cada patrón tiene un nombre descriptivo y datos de soporte.
    """
    patterns = {}
    n = len(df)

    # ── Patrón 1: Alta frecuencia de estrés elevado
    high_stress_days = (df["stress_level"] >= 7).sum()
    very_high_stress = (df["stress_level"] >= 9).sum()
    if high_stress_days >= 4:
        patterns["high_stress_frequency"] = {
            "active": True,
            "days": int(high_stress_days),
            "very_high_days": int(very_high_stress),
            "label": f"Estrés elevado en {high_stress_days}/{n} días"
        }

    # ── Patrón 2: Estado de ánimo bajo persistente
    low_mood_days = (df["mood"] <= 4).sum()
    if low_mood_days >= 3:
        patterns["low_mood_persistent"] = {
            "active": True,
            "days": int(low_mood_days),
            "avg": round(df["mood"].mean(), 1),
            "label": f"Ánimo bajo en {low_mood_days}/{n} días"
        }

    # ── Patrón 3: Correlación sueño–energía
    if n >= 4:
        corr_sleep_energy = df["sleep_quality"].corr(df["energy_level"])
        avg_sleep = df["sleep_quality"].mean()
        avg_energy = df["energy_level"].mean()
        if corr_sleep_energy > 0.5 and avg_sleep < 3 and avg_energy < 5:
            patterns["sleep_energy_correlation"] = {
                "active": True,
                "correlation": round(corr_sleep_energy, 2),
                "avg_sleep": round(avg_sleep, 1),
                "avg_energy": round(avg_energy, 1),
                "label": "Sueño deficiente → baja energía"
            }

    # ── Patrón 4: Variabilidad emocional alta (inestabilidad)
    # Desviación estándar alta = ánimo muy variable
    if df["mood"].std() > 2.5:
        patterns["emotional_instability"] = {
            "active": True,
            "std_mood": round(df["mood"].std(), 2),
            "label": "Ánimo muy variable durante la semana"
        }

    # ── Patrón 5: Estrés laboral (lunes-viernes vs fin de semana)
    df["weekday"] = df["entry_date"].dt.dayofweek
    weekday_entries = df[df["weekday"] < 5]
    weekend_entries = df[df["weekday"] >= 5]

    if len(weekday_entries) >= 3 and len(weekend_entries) >= 1:
        avg_wd_stress = weekday_entries["stress_level"].mean()
        avg_we_stress = weekend_entries["stress_level"].mean()
        diff = avg_wd_stress - avg_we_stress
        if diff > 2.0:
            patterns["work_stress_pattern"] = {
                "active": True,
                "weekday_avg": round(avg_wd_stress, 1),
                "weekend_avg": round(avg_we_stress, 1),
                "difference": round(diff, 1),
                "label": f"Estrés laboral: {round(avg_wd_stress,1)} vs {round(avg_we_stress,1)} fines de semana"
            }

    # ── Patrón 6: Estrés escalante (de tendencias)
    stress_trend = trends.get("stress", {})
    if stress_trend.get("direction") == "increasing" and stress_trend.get("total_change", 0) > 1.5:
        patterns["stress_escalating"] = {
            "active": True,
            "change": stress_trend["total_change"],
            "label": f"Estrés aumentó {stress_trend['total_change']:.1f} puntos en la semana"
        }

    # ── Patrón 7: Recuperación positiva (mejora del ánimo)
    mood_trend = trends.get("mood", {})
    if mood_trend.get("direction") == "increasing" and mood_trend.get("total_change", 0) > 1.5:
        patterns["positive_recovery"] = {
            "active": True,
            "change": mood_trend["total_change"],
            "label": f"Ánimo mejoró {mood_trend['total_change']:.1f} puntos esta semana"
        }

    # ── Patrón 8: Fatiga acumulada (energía decreciente + sueño malo)
    energy_trend = trends.get("energy", {})
    if (energy_trend.get("direction") == "decreasing" and
        df["sleep_quality"].mean() < 3 and
        df["energy_level"].mean() < 4):
        patterns["accumulated_fatigue"] = {
            "active": True,
            "avg_energy": round(df["energy_level"].mean(), 1),
            "avg_sleep": round(df["sleep_quality"].mean(), 1),
            "label": "Fatiga acumulada: energía baja y sueño deficiente"
        }

    return patterns


# ============================================================
# FRECUENCIA DE EMOCIONES
# ============================================================

def compute_emotion_frequency(df: pd.DataFrame) -> dict:
    """
    Calcula qué emociones aparecieron más durante la semana.
    Retorna ordenado de mayor a menor frecuencia.
    """
    all_emotions = []
    for _, row in df.iterrows():
        tags = row.get("emotions_tags") or []
        if isinstance(tags, list):
            all_emotions.extend(tags)

    counter = Counter(all_emotions)
    # Retornar top 8 emociones
    return dict(counter.most_common(8))


# ============================================================
# DÍAS CRÍTICOS
# ============================================================

def identify_critical_days(df: pd.DataFrame) -> list:
    """
    Identifica días con valores extremos que requieren atención.
    Criterios: estrés >= 8 O ánimo <= 3 O energía <= 2
    """
    mask = (
        (df["stress_level"] >= 8) |
        (df["mood"] <= 3) |
        (df["energy_level"] <= 2)
    )
    critical = df[mask]

    return [
        {
            "date":       row["entry_date"].strftime("%Y-%m-%d"),
            "day_name":   row["entry_date"].strftime("%A"),
            "stress":     int(row["stress_level"]),
            "mood":       int(row["mood"]),
            "energy":     int(row["energy_level"]),
            "sleep":      int(row["sleep_quality"]),
            "situation":  row.get("main_situation", "") or "",
            "emotions":   row.get("emotions_tags", []) or [],
            "severity":   _day_severity(row),
        }
        for _, row in critical.iterrows()
    ]

def _day_severity(row) -> str:
    """Calcula la severidad de un día crítico."""
    score = 0
    if row["stress_level"] >= 9: score += 2
    elif row["stress_level"] >= 8: score += 1
    if row["mood"] <= 2: score += 2
    elif row["mood"] <= 3: score += 1
    if row["energy_level"] <= 2: score += 1
    return "high" if score >= 3 else "medium"


# ============================================================
# NIVEL DE ALERTA
# ============================================================

def calculate_alert_level(stats: dict, critical_days: list, patterns: dict, trends: dict) -> str:
    """
    Calcula el nivel de alerta: 'normal', 'attention', 'urgent'
    Algoritmo de puntuación ponderada.
    """
    score = 0

    # Métricas base
    if stats["avg_stress"] >= 8:    score += 3
    elif stats["avg_stress"] >= 6.5: score += 1

    if stats["avg_mood"] <= 3:      score += 3
    elif stats["avg_mood"] <= 5:    score += 1

    if stats["avg_sleep"] < 2:      score += 2
    elif stats["avg_sleep"] < 3:    score += 1

    # Días críticos
    high_severity = sum(1 for d in critical_days if d.get("severity") == "high")
    score += high_severity * 2
    score += max(0, len(critical_days) - high_severity) * 1

    # Patrones activos
    urgent_patterns = ["stress_escalating", "accumulated_fatigue", "low_mood_persistent"]
    for p in urgent_patterns:
        if patterns.get(p, {}).get("active"):
            score += 2

    attention_patterns = ["high_stress_frequency", "work_stress_pattern", "emotional_instability"]
    for p in attention_patterns:
        if patterns.get(p, {}).get("active"):
            score += 1

    # Tendencia de estrés creciente
    if trends.get("stress", {}).get("direction") == "increasing":
        if trends["stress"].get("total_change", 0) > 2:
            score += 2

    # Determinar nivel
    if score >= 5:   return "urgent"
    elif score >= 2: return "attention"
    return "normal"


# ============================================================
# TEXTO NARRATIVO CON PLANTILLAS INTELIGENTES
# ============================================================

def build_narrative_text(
    stats: dict, trends: dict, patterns: dict,
    emotions_freq: dict, critical_days: list,
    alert_level: str, days_count: int
) -> str:
    """
    Genera un texto narrativo legible para el psicólogo.
    Usa plantillas condicionales que se combinan según los datos.
    Resultado: párrafo de 3-5 oraciones que resume la semana.
    """
    sentences = []

    # ── Frase de apertura según días registrados
    if days_count == 7:
        sentences.append(f"Semana completa registrada ({days_count}/7 días).")
    elif days_count >= 5:
        sentences.append(f"Semana con buena adherencia al diario ({days_count}/7 días).")
    else:
        sentences.append(f"Semana con registro parcial ({days_count}/7 días).")

    # ── Estado general
    stress = stats["avg_stress"]
    mood   = stats["avg_mood"]
    energy = stats["avg_energy"]
    sleep  = stats["avg_sleep"]

    stress_trend = trends.get("stress", {})
    mood_trend   = trends.get("mood", {})

    if stress >= 7.5 and mood <= 4.5:
        sentences.append(
            f"Semana difícil: estrés elevado ({stress:.1f}/10) y ánimo bajo ({mood:.1f}/10), "
            f"ambos por encima de umbrales de atención."
        )
    elif stress >= 7.5:
        direction_text = _trend_text(stress_trend, "estrés", invert=True)
        sentences.append(
            f"Nivel de estrés significativo esta semana ({stress:.1f}/10){direction_text}."
        )
    elif mood <= 4.5:
        direction_text = _trend_text(mood_trend, "ánimo", invert=False)
        sentences.append(
            f"Estado de ánimo bajo durante la semana ({mood:.1f}/10){direction_text}."
        )
    else:
        sentences.append(
            f"Semana dentro de rangos manejables: estrés {stress:.1f}/10, ánimo {mood:.1f}/10."
        )

    # ── Sueño y energía
    if sleep < 2.5 and energy < 4:
        sentences.append(
            f"Sueño deficiente ({sleep:.1f}/5) correlaciona con baja energía ({energy:.1f}/10) — "
            f"posible fatiga acumulada."
        )
    elif sleep < 2.5:
        sentences.append(f"Calidad de sueño baja esta semana ({sleep:.1f}/5).")

    # ── Días críticos
    if len(critical_days) > 0:
        high = [d for d in critical_days if d.get("severity") == "high"]
        if high:
            situations = [d["situation"] for d in high[:2] if d.get("situation")]
            if situations:
                sentences.append(
                    f"{len(critical_days)} día(s) crítico(s). Situación destacada: \"{situations[0][:80]}\"."
                )
            else:
                sentences.append(
                    f"{len(critical_days)} día(s) con indicadores críticos (estrés ≥8 o ánimo ≤3)."
                )

    # ── Patrones activos más relevantes
    active_patterns = [
        p_data["label"]
        for p_name, p_data in patterns.items()
        if isinstance(p_data, dict) and p_data.get("active")
    ]
    if active_patterns:
        sentences.append(f"Patrones detectados: {'; '.join(active_patterns[:3])}.")

    # ── Emociones dominantes
    if emotions_freq:
        top = list(emotions_freq.keys())[:3]
        sentences.append(f"Emociones predominantes: {', '.join(top)}.")

    # ── Frase de cierre según alerta
    if alert_level == "urgent":
        sentences.append(
            "Recomendación: revisar este resumen antes de la sesión y evaluar si se adelanta el contacto."
        )
    elif alert_level == "attention":
        sentences.append(
            "Hay puntos de atención que vale la pena explorar en la próxima sesión."
        )

    return " ".join(sentences)

def _trend_text(trend: dict, metric_name: str, invert: bool) -> str:
    """Genera texto de tendencia para incluir en una oración."""
    direction = trend.get("direction")
    change = trend.get("total_change", 0)

    if not direction or direction == "stable" or abs(change) < 0.5:
        return ""

    is_bad = (direction == "increasing" and invert) or (direction == "decreasing" and not invert)

    if is_bad:
        return f" y en tendencia {_dir_es(direction)} (+{abs(change):.1f} pts)"
    else:
        return f" aunque mejorando durante la semana (+{abs(change):.1f} pts)"

def _dir_es(direction: str) -> str:
    return {"increasing": "creciente", "decreasing": "decreciente", "stable": "estable"}.get(direction, "")


# ============================================================
# COMPARACIÓN CON SEMANA ANTERIOR
# ============================================================

async def compute_week_comparison(user_id: str, current_week: date, current_stats: dict) -> dict:
    """
    Compara la semana actual con la semana anterior.
    Retorna deltas para mostrar en el dashboard (↑2.1 estrés vs semana pasada)
    """
    prev_week = current_week - timedelta(days=7)

    prev_summary = supabase.table("weekly_summaries") \
        .select("avg_stress, avg_mood, avg_energy, avg_sleep") \
        .eq("user_id", user_id) \
        .eq("week_start", str(prev_week)) \
        .execute()

    if not prev_summary.data:
        return {"available": False}

    prev = prev_summary.data[0]

    def delta(current, previous):
        if previous is None:
            return None
        diff = round(current - float(previous), 2)
        return {"value": diff, "direction": "up" if diff > 0 else "down" if diff < 0 else "same"}

    return {
        "available":   True,
        "stress_delta": delta(current_stats["avg_stress"], prev["avg_stress"]),
        "mood_delta":   delta(current_stats["avg_mood"],   prev["avg_mood"]),
        "energy_delta": delta(current_stats["avg_energy"], prev["avg_energy"]),
        "sleep_delta":  delta(current_stats["avg_sleep"],  prev["avg_sleep"]),
    }


# ============================================================
# NOTIFICACIÓN AL PSICÓLOGO
# ============================================================

async def notify_therapist_new_summary(patient_id: str, alert_level: str):
    """Notifica al psicólogo cuando hay un nuevo resumen disponible."""
    relation = supabase.table("patient_therapist") \
        .select("therapist_id") \
        .eq("patient_id", patient_id) \
        .eq("status", "active") \
        .execute()

    if not relation.data:
        return

    therapist_id = relation.data[0]["therapist_id"]

    patient = supabase.table("profiles") \
        .select("full_name") \
        .eq("id", patient_id) \
        .execute()

    name = patient.data[0].get("full_name", "Tu paciente") if patient.data else "Tu paciente"

    messages = {
        "urgent":    f"{name} tuvo una semana difícil — revisa el resumen antes de la sesión.",
        "attention": f"{name} completó su diario. Hay algunos puntos de atención.",
        "normal":    f"{name} completó su diario semanal. Semana estable.",
    }

    supabase.table("notifications").insert({
        "user_id":    therapist_id,
        "type":       "new_summary",
        "title":      "Nuevo resumen semanal",
        "message":    messages.get(alert_level, messages["normal"]),
        "action_url": f"/therapist/patients/{patient_id}",
        "metadata":   {"patient_id": patient_id, "alert_level": alert_level}
    }).execute()
