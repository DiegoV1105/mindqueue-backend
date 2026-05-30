from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date, datetime

class JournalEntryCreate(BaseModel):
    sleep_quality: int = Field(..., ge=1, le=5, description="Calidad del sueño 1-5")
    stress_level: int = Field(..., ge=1, le=10, description="Nivel de estrés 1-10")
    energy_level: int = Field(..., ge=1, le=10, description="Nivel de energía 1-10")
    mood: int = Field(..., ge=1, le=10, description="Estado de ánimo 1-10")
    main_situation: Optional[str] = Field(None, max_length=500)
    emotions_tags: Optional[List[str]] = []
    free_text: Optional[str] = Field(None, max_length=2000)
    entry_date: Optional[date] = None  # si no se envía, usa la fecha de hoy

class JournalEntryResponse(BaseModel):
    id: str
    user_id: str
    entry_date: date
    sleep_quality: int
    stress_level: int
    energy_level: int
    mood: int
    main_situation: Optional[str]
    emotions_tags: List[str]
    free_text: Optional[str]
    created_at: datetime

class WeeklySummaryResponse(BaseModel):
    id: str
    user_id: str
    week_start: date
    week_end: date
    days_recorded: int
    avg_stress: float
    avg_mood: float
    avg_energy: float
    avg_sleep: float
    max_stress: Optional[int]
    min_mood: Optional[int]
    critical_days: list
    patterns: dict
    emotions_freq: dict
    summary_text: str
    alert_level: str
    is_reviewed: bool
    generated_at: datetime
