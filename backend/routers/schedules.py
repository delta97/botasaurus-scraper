"""CRUD for cron schedules attached to recipes."""
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import scheduler
from ..db import get_session
from ..models import Recipe, Schedule, utcnow

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


class CreateSchedule(BaseModel):
    recipe_id: int
    cron: str = Field(min_length=1)
    variables: dict = Field(default_factory=dict)
    enabled: bool = True


class UpdateSchedule(BaseModel):
    cron: str = None
    variables: dict = None
    enabled: bool = None


def _dict(s: Schedule, recipe_name=None):
    return {"id": s.id, "recipe_id": s.recipe_id, "recipe_name": recipe_name,
            "cron": s.cron, "variables": json.loads(s.variables) if s.variables else {},
            "enabled": bool(s.enabled), "last_run_at": s.last_run_at,
            "last_run_id": s.last_run_id, "created_at": s.created_at}


@router.get("")
def list_schedules(session: Session = Depends(get_session)):
    rows = session.query(Schedule, Recipe).join(
        Recipe, Schedule.recipe_id == Recipe.id).order_by(Schedule.id.desc()).all()
    return {"schedules": [_dict(s, r.name) for s, r in rows]}


@router.post("")
def create_schedule(payload: CreateSchedule, session: Session = Depends(get_session)):
    if session.get(Recipe, payload.recipe_id) is None:
        raise HTTPException(status_code=404, detail="recipe not found")
    if not scheduler.validate_cron(payload.cron):
        raise HTTPException(status_code=400, detail="invalid cron expression (5 fields expected)")
    schedule = Schedule(recipe_id=payload.recipe_id, cron=payload.cron,
                        variables=json.dumps(payload.variables) if payload.variables else None,
                        enabled=1 if payload.enabled else 0)
    session.add(schedule)
    session.commit()
    scheduler.add_job(schedule)
    return _dict(schedule)


@router.put("/{schedule_id}")
def update_schedule(schedule_id: int, payload: UpdateSchedule,
                    session: Session = Depends(get_session)):
    schedule = session.get(Schedule, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    if payload.cron is not None:
        if not scheduler.validate_cron(payload.cron):
            raise HTTPException(status_code=400, detail="invalid cron expression")
        schedule.cron = payload.cron
    if payload.variables is not None:
        schedule.variables = json.dumps(payload.variables)
    if payload.enabled is not None:
        schedule.enabled = 1 if payload.enabled else 0
    session.commit()
    scheduler.add_job(schedule)  # re-registers or removes (if disabled)
    return _dict(schedule)


@router.delete("/{schedule_id}")
def delete_schedule(schedule_id: int, session: Session = Depends(get_session)):
    schedule = session.get(Schedule, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    scheduler.remove_job(schedule_id)
    session.delete(schedule)
    session.commit()
    return {"ok": True}
