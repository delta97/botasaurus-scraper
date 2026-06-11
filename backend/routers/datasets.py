"""Dataset (CSV) batch replays: run a recipe once per row, mapping columns to
{{variables}}."""
import csv
import io
import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import BatchRun, Recipe, Run
from ..runs.manager import run_manager

router = APIRouter(prefix="/api/recipes/{recipe_id}/batch", tags=["datasets"])


class BatchFromRows(BaseModel):
    rows: list[dict]


def _get_recipe(session, recipe_id):
    recipe = session.get(Recipe, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail="recipe not found")
    return recipe


def _start_batch(session, recipe_id, rows):
    if not rows:
        raise HTTPException(status_code=400, detail="dataset has no rows")
    batch = BatchRun(recipe_id=recipe_id, status="queued", total=len(rows),
                     rows=json.dumps(rows))
    session.add(batch)
    session.commit()
    run_manager.start_batch_run(batch.id)
    return {"batch_run_id": batch.id, "rows": len(rows)}


@router.post("/csv")
async def run_csv(recipe_id: int, file: UploadFile = File(...),
                  session: Session = Depends(get_session)):
    _get_recipe(session, recipe_id)
    raw = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    rows = [{k: (v or "") for k, v in row.items() if k} for row in reader]
    return _start_batch(session, recipe_id, rows)


@router.post("")
def run_rows(recipe_id: int, payload: BatchFromRows, session: Session = Depends(get_session)):
    _get_recipe(session, recipe_id)
    return _start_batch(session, recipe_id, payload.rows)


@router.get("")
def list_batches(recipe_id: int, session: Session = Depends(get_session)):
    rows = (session.query(BatchRun).filter(BatchRun.recipe_id == recipe_id)
            .order_by(BatchRun.id.desc()).all())
    return {"batches": [{
        "id": b.id, "status": b.status, "total": b.total,
        "succeeded": b.succeeded, "failed": b.failed,
        "created_at": b.created_at, "finished_at": b.finished_at,
    } for b in rows]}


@router.get("/{batch_run_id}")
def get_batch(recipe_id: int, batch_run_id: int, session: Session = Depends(get_session)):
    batch = session.get(BatchRun, batch_run_id)
    if batch is None or batch.recipe_id != recipe_id:
        raise HTTPException(status_code=404, detail="batch run not found")
    children = (session.query(Run).filter(Run.batch_run_id == batch_run_id)
                .order_by(Run.id).all())
    return {
        "id": batch.id, "status": batch.status, "total": batch.total,
        "succeeded": batch.succeeded, "failed": batch.failed,
        "children": [{
            "run_id": c.id, "status": c.status, "goal": c.goal, "error": c.error,
            "row": (json.loads(c.result).get("row") if c.result else None),
        } for c in children],
    }


@router.post("/{batch_run_id}/cancel")
def cancel_batch(recipe_id: int, batch_run_id: int, session: Session = Depends(get_session)):
    batch = session.get(BatchRun, batch_run_id)
    if batch is None or batch.recipe_id != recipe_id:
        raise HTTPException(status_code=404, detail="batch run not found")
    if batch.status not in ("queued", "running"):
        raise HTTPException(status_code=409, detail=f"batch is already {batch.status}")
    run_manager.cancel_batch(batch_run_id)
    return {"ok": True}
