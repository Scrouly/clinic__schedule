"""
models.py — Структуры данных (DTO) для проекта.
Содержит Pydantic-модели и dataclass-отчеты.
"""

from typing import Dict, List, Optional
from dataclasses import dataclass, field as dc_field
from pydantic import BaseModel, Field

class Shift(BaseModel):
    """Смена врача на один день."""
    time: Optional[str] = None
    hours: float = Field(default=0.0, ge=0.0)

class DoctorRecord(BaseModel):
    """Запись о расписании конкретного врача из источника."""
    name: str
    direction: str
    cabinet: str
    spec_hint: str = ""  # специальность из строки источника, например "(невролог 1,0)"
    schedule: Dict[int, Shift] = Field(default_factory=dict)

@dataclass
class DiagReport:
    """Структура для сбора статистики и расхождений при генерации табеля."""
    month_str: str = ""
    # Врачи из шаблона, которых нет ни в источнике вообще
    not_in_source: List[str] = dc_field(default_factory=list)
    # Найдены в источнике, но score < порога (не назначены)
    low_score: List[dict] = dc_field(default_factory=list)
    # Назначены, но с низким/сомнительным баллом (0.0 .. 1.0)
    dubious: List[dict] = dc_field(default_factory=list)
    # Назначены, но у врача нет ни одного часа во всём месяце
    no_hours: List[dict] = dc_field(default_factory=list)
    # Назначены, есть часы, но нет времени хотя бы в одном рабочем дне
    missing_time: List[dict] = dc_field(default_factory=list)
    # Назначены, но расписание полностью пустое (только выходные)
    empty_schedule: List[dict] = dc_field(default_factory=list)
    # Врачи из источника, которых нет ни на одном листе шаблона
    source_not_in_template: List[str] = dc_field(default_factory=list)
    # Успешно назначены без замечаний
    ok: List[dict] = dc_field(default_factory=list)