"""
Genera mensajes motivadores sin IA usando reglas contextuales.
Los mensajes son variados (múltiples opciones por situación) y
se seleccionan según el estado emocional real del paciente.
No son frases genéricas — cada categoría tiene 4-5 variantes
que se eligen pseudo-aleatoriamente basadas en el user_id
(mismo usuario siempre ve variantes distintas en días distintos).
"""
import hashlib
from datetime import date, timedelta
from app.database import supabase

# ── BANCO DE MENSAJES POR SITUACIÓN ──────────────────────────
# Cada situación tiene mensajes que reconocen el contexto real
# Se elige uno basado en (user_id + fecha) para variedad

MESSAGES = {
    # Día muy difícil (estrés ≥ 8 o ánimo ≤ 3)
    "very_hard_day": [
        "Hoy fue pesado de verdad. El hecho de que igual te tomaste este minuto para registrar cómo te sentiste dice mucho de ti. Descansa bien.",
        "Días así agotan. No tienes que tener todo resuelto hoy — con llegar hasta acá es suficiente por ahora.",
        "Registrar un día difícil también es valentía. Tu psicólogo va a tener esto cuando se sienten juntos, y eso importa.",
        "No siempre los días salen bien, y está bien reconocerlo. Lo que sientes es válido. Mañana empieza de nuevo.",
    ],

    # Día difícil con situación específica mencionada
    "hard_day_with_situation": [
        "Lo que pasó hoy no fue fácil. Haberlo escrito ya es procesarlo un poco. Tu psicólogo lo va a leer antes de la sesión.",
        "Esa situación que describiste suena agotadora. Bien que la registraste — es exactamente el tipo de cosa que vale la pena explorar en sesión.",
        "Gracias por escribirlo. No guardarlo todo adentro, aunque sea aquí, ayuda más de lo que parece.",
    ],

    # Sueño muy malo (sleep ≤ 2)
    "bad_sleep": [
        "Dormir mal lo cambia todo — el ánimo, la energía, cómo se siente el día. Ojalá esta noche sea mejor.",
        "Con poco sueño encima, que hayas llenado esto igual es mérito. Intenta descansar bien hoy.",
        "El cuerpo cuando no duerme bien nos lo cobra. Anota mentalmente irte a la cama un poco más temprano hoy.",
    ],

    # Racha larga (streak ≥ 7)
    "long_streak": [
        "Llevas una semana seguida registrando. Eso no es casualidad — es un hábito tomando forma.",
        "7 días consecutivos. Muchos lo intentan, pocos llegan. Tú ya llegaste.",
        "Una semana completa. Tu psicólogo tiene ahora una imagen mucho más completa de cómo estuvo tu semana.",
    ],

    # Primera semana (streak ≤ 3)
    "first_days": [
        "Los primeros días son los más difíciles de cualquier hábito. Ya tienes lo más duro encima.",
        "Arrancar siempre cuesta. Que hayas vuelto a abrir la app es lo que importa.",
        "Cada registro cuenta. Aunque no lo sientas, estás construyendo algo útil para ti y para tu proceso.",
    ],

    # Buen día (mood ≥ 7, estrés ≤ 4)
    "good_day": [
        "Qué bien que hoy estuvo mejor. Registrar los días buenos también ayuda a entender qué los hace posibles.",
        "Los días así recargan. Disfrútalo y guarda esa energía para cuando la necesites.",
        "Bien por hoy. Que el resto de la semana tenga más días así.",
    ],

    # Día promedio
    "neutral_day": [
        "Otro día registrado. Cada entrada suma, aunque el día haya sido del montón.",
        "Los días normales también importan. Gracias por llenar esto.",
        "Estás construyendo un registro honesto de cómo te sientes. Eso tiene más valor de lo que parece.",
        "No todos los días son drama ni euforia. Los días como hoy también son parte del proceso.",
    ],

    # Mejora de ánimo respecto a ayer
    "mood_improving": [
        "Algo mejoró hoy respecto a ayer. No siempre es evidente en el momento, pero está en los datos.",
        "El ánimo subió un poco hoy. A veces los cambios pequeños son los más importantes.",
    ],

    # Emociones difíciles (ansiedad, tristeza, miedo)
    "difficult_emotions": [
        "Reconocer lo que sentiste hoy, aunque sea difícil, es parte del trabajo. Buen registro.",
        "Poner nombre a lo que se siente ya es un paso. Tu proceso está funcionando.",
        "Las emociones difíciles son información. Que las hayas anotado significa que las estás mirando de frente.",
    ],
}

def generate_contextual_message(
    user_id: str,
    today_entry: dict,
    streak: int,
    yesterday_mood: int = None
) -> str:
    """
    Genera un mensaje motivador contextual basado en reglas.
    Selecciona la categoría según el estado emocional del día,
    luego elige una variante usando un hash del user_id + fecha
    para garantizar variedad entre días.
    """
    mood    = today_entry.get("mood", 5)
    stress  = today_entry.get("stress_level", 5)
    sleep   = today_entry.get("sleep_quality", 3)
    situation = today_entry.get("main_situation", "") or ""
    emotions  = today_entry.get("emotions_tags", []) or []

    # Determinar categoría
    difficult_emotions_list = {"ansiedad", "tristeza", "miedo", "abrumado", "soledad", "enojo"}
    has_difficult_emotions = bool(set(e.lower() for e in emotions) & difficult_emotions_list)

    if mood <= 3 or stress >= 8:
        if situation and len(situation) > 10:
            category = "hard_day_with_situation"
        else:
            category = "very_hard_day"
    elif sleep <= 2:
        category = "bad_sleep"
    elif streak >= 7 and mood >= 5:
        category = "long_streak"
    elif streak <= 3:
        category = "first_days"
    elif mood >= 7 and stress <= 4:
        category = "good_day"
    elif yesterday_mood and mood > yesterday_mood + 1:
        category = "mood_improving"
    elif has_difficult_emotions:
        category = "difficult_emotions"
    else:
        category = "neutral_day"

    # Seleccionar variante pseudo-aleatoria
    messages = MESSAGES[category]
    seed = f"{user_id}{date.today().isoformat()}"
    index = int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(messages)

    return messages[index]

async def get_motivational_message(user_id: str, today_entry: dict) -> str:
    """
    Wrapper que obtiene el contexto del usuario y genera el mensaje.
    Llamado desde el router de journal al finalizar el POST /entry.
    """
    # Racha actual
    entries = supabase.table("journal_entries") \
        .select("entry_date, mood") \
        .eq("user_id", user_id) \
        .order("entry_date", desc=True) \
        .limit(14) \
        .execute()

    streak = 0
    today = date.today()
    entry_dates = {e["entry_date"] for e in entries.data}

    for i in range(14):
        check = str(today - timedelta(days=i))
        if check in entry_dates:
            streak += 1
        else:
            break

    # Ánimo de ayer
    yesterday = str(today - timedelta(days=1))
    yesterday_entry = next((e for e in entries.data if e["entry_date"] == yesterday), None)
    yesterday_mood = yesterday_entry["mood"] if yesterday_entry else None

    return generate_contextual_message(user_id, today_entry, streak, yesterday_mood)
