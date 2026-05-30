from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime

class UserRegister(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: str  # 'patient' o 'therapist'
    phone: Optional[str] = None
    city: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class TherapistProfileCreate(BaseModel):
    license_number: str
    specialties: Optional[List[str]] = []
    approach: Optional[str] = None
    years_experience: Optional[int] = 0
    min_fee: Optional[int] = 0
    max_fee: Optional[int] = 0
    bio: Optional[str] = None

class ProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    bio: Optional[str] = None
    phone: Optional[str] = None
    city: Optional[str] = None
    avatar_url: Optional[str] = None

class ProfileResponse(BaseModel):
    id: str
    role: str
    full_name: str
    avatar_url: Optional[str]
    bio: Optional[str]
    phone: Optional[str]
    city: Optional[str]
    created_at: datetime
