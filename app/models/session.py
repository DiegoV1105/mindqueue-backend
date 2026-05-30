from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class SessionCreate(BaseModel):
    patient_id: str
    scheduled_at: datetime
    duration_min: Optional[int] = 50
    meet_link: Optional[str] = None
    session_goals: Optional[str] = None
    summary_id: Optional[str] = None  # resumen semanal a adjuntar

class SessionUpdate(BaseModel):
    status: Optional[str] = None
    therapist_notes: Optional[str] = None
    meet_link: Optional[str] = None
    session_goals: Optional[str] = None
    patient_feedback: Optional[int] = None
    cancelled_reason: Optional[str] = None

class SessionResponse(BaseModel):
    id: str
    patient_id: str
    therapist_id: str
    scheduled_at: datetime
    duration_min: int
    status: str
    meet_link: Optional[str]
    session_goals: Optional[str]
    patient_feedback: Optional[int]
    created_at: datetime
    # therapist_notes NO se incluye aquí — es privado
    # Se expone en SessionResponseTherapist abajo

class SessionResponseTherapist(SessionResponse):
    therapist_notes: Optional[str]  # Solo para el psicólogo
    summary_id: Optional[str]
