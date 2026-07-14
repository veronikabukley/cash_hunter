"""
MCP Stub Server — CRM интеграция для Cash Hunter.

FastAPI-сервер, имитирующий CRM для управления лидами.
Хранит данные в leads.json.

Эндпоинты:
  POST   /create_lead       — создать лид
  GET    /leads              — список всех лидов (с фильтром по status)
  GET    /leads/{lead_id}    — получить лид по ID
  PUT    /update_lead/{id}    — обновить статус лида
  DELETE /leads/{lead_id}    — удалить лид
  GET    /health             — проверка здоровья

Запуск:
  uvicorn server.mcp_stub:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

# ── Константы ────────────────────────────────────────────────

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LEADS_FILE = DATA_DIR / "leads.json"

VALID_STATUSES = {"new", "interested", "rejected"}

# ── Модели ───────────────────────────────────────────────────


class LeadCreate(BaseModel):
    """Схема создания лида."""

    company_id: int = Field(..., description="ID компании из companies.csv")
    name: str = Field(..., description="Название компании")
    inn: str = Field(..., description="ИНН компании")
    region: str = Field(..., description="Регион")
    score: float = Field(..., description="Скоринг агента")
    script: str = Field(default="", description="Скрипт для звонка")
    status: str = Field(default="new", description="Статус: new/interested/rejected")


class LeadUpdate(BaseModel):
    """Схема обновления лида."""

    status: Optional[str] = Field(None, description="Новый статус")
    score: Optional[float] = Field(None, description="Обновлённый скоринг")
    script: Optional[str] = Field(None, description="Обновлённый скрипт")


class LeadOut(BaseModel):
    """Схема ответа — лид."""

    id: int
    company_id: int
    name: str
    inn: str
    region: str
    score: float
    script: str
    status: str
    created_at: str
    updated_at: str


# ── Хранилище ────────────────────────────────────────────────


def _ensure_storage() -> None:
    """Создать файл хранилища, если отсутствует."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not LEADS_FILE.exists():
        _write_leads([])


def _read_leads() -> list[dict]:
    """Прочитать все лиды из JSON."""
    if not LEADS_FILE.exists():
        return []
    try:
        with open(LEADS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _write_leads(leads: list[dict]) -> None:
    """Записать все лиды в JSON (атомарно)."""
    tmp = LEADS_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(leads, f, ensure_ascii=False, indent=2)
    os.replace(tmp, LEADS_FILE)


def _next_id(leads: list[dict]) -> int:
    """Сгенерировать следующий ID."""
    if not leads:
        return 1
    return max(l["id"] for l in leads) + 1


# ── Приложение FastAPI ───────────────────────────────────────

app = FastAPI(
    title="Cash Hunter — MCP CRM Stub",
    description="CRM-заглушка для управления лидами инкассации",
    version="1.0.0",
)


@app.on_event("startup")
def _startup() -> None:
    _ensure_storage()


@app.get("/health")
def health():
    """Проверка здоровья сервера."""
    return {"status": "ok", "service": "cash-hunter-crm", "version": "1.0.0"}


@app.post("/create_lead", response_model=LeadOut, status_code=201)
def create_lead(lead: LeadCreate):
    """Создать новый лид."""
    if lead.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{lead.status}'. Must be one of {VALID_STATUSES}",
        )

    leads = _read_leads()
    now = datetime.now(timezone.utc).isoformat()

    new_lead = {
        "id": _next_id(leads),
        "company_id": lead.company_id,
        "name": lead.name,
        "inn": lead.inn,
        "region": lead.region,
        "score": lead.score,
        "script": lead.script,
        "status": lead.status,
        "created_at": now,
        "updated_at": now,
    }

    leads.append(new_lead)
    _write_leads(leads)

    return LeadOut(**new_lead)


@app.get("/leads", response_model=list[LeadOut])
def get_leads(
    status: Optional[str] = Query(None, description="Фильтр по статусу"),
    region: Optional[str] = Query(None, description="Фильтр по региону"),
):
    """Получить список лидов. Опциональная фильтрация по status и region."""
    leads = _read_leads()

    if status:
        if status not in VALID_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status '{status}'. Must be one of {VALID_STATUSES}",
            )
        leads = [l for l in leads if l["status"] == status]

    if region:
        leads = [l for l in leads if l["region"].lower() == region.lower()]

    return [LeadOut(**l) for l in leads]


@app.get("/leads/{lead_id}", response_model=LeadOut)
def get_lead(lead_id: int):
    """Получить лид по ID."""
    leads = _read_leads()
    for l in leads:
        if l["id"] == lead_id:
            return LeadOut(**l)
    raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")


@app.put("/update_lead/{lead_id}", response_model=LeadOut)
def update_lead(lead_id: int, update: LeadUpdate):
    """Обновить лид (статус, score, script)."""
    leads = _read_leads()

    for l in leads:
        if l["id"] == lead_id:
            if update.status is not None:
                if update.status not in VALID_STATUSES:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid status '{update.status}'. Must be one of {VALID_STATUSES}",
                    )
                l["status"] = update.status
            if update.score is not None:
                l["score"] = update.score
            if update.script is not None:
                l["script"] = update.script

            l["updated_at"] = datetime.now(timezone.utc).isoformat()
            _write_leads(leads)
            return LeadOut(**l)

    raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")


@app.delete("/leads/{lead_id}")
def delete_lead(lead_id: int):
    """Удалить лид по ID."""
    leads = _read_leads()
    new_leads = [l for l in leads if l["id"] != lead_id]

    if len(new_leads) == len(leads):
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")

    _write_leads(new_leads)
    return {"deleted": lead_id}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
