from pydantic import BaseModel, Field
from typing import List, Optional


class Horario(BaseModel):
    dia_semana: str = Field(..., description="Día de la semana, ej. Lunes")
    hora_inicio: str = Field(..., description="Hora de inicio en formato HH:MM")
    hora_fin: str = Field(..., description="Hora de fin en formato HH:MM")


class DisponibilidadResponse(BaseModel):
    usuario_id: int = Field(..., description="ID único del estudiante")
    disponibilidad: List[Horario]


class GrupoCreate(BaseModel):
    nombre: str = Field(..., max_length=150)
    materia_id: int
    miembros: List[int] = Field(..., description="Lista de IDs de los estudiantes")


class ErrorResponse(BaseModel):
    code: int
    message: str
    details: Optional[str] = None
    request_id: str