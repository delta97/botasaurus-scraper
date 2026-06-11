import json
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import settings_store
from ..agent.recorder import build_recipe_definition
from ..db import get_session
from ..models import LlmCall, Recipe, Run, RunStep, utcnow
from ..runs.manager import run_manager
from ..schemas import CreateRun, SaveRecipe

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _run_dict(run: Run, include_result=False):
    data = {
        "id": run.id,
        "kind": run.kind,
        "goal": run.goal,
        "start_url": run.start_url,
        "status": run.status,
        "model": run.model,
        "error": run.error,
        "recipe_id": run.recipe_id,
        "total_prompt_tokens": run.total_prompt_tokens,
        "total_completion_tokens": run.total_completion_tokens,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "botasaurus_config": json.loads(run.botasaurus_config or "{}"),
    }
    if include_result:
        data["result"] = json.loads(run.result) if run.result else None
    return data


@router.post("")
def create_run(payload: CreateRun, session: Session = Depends(get_session)):
    api_key = settings_store.get_api_key(session)
    if not api_key:
        raise HTTPException(status_code=400, detail="Set your OpenRouter API key in Settings first")
    cfg = settings_store.get_default_botasaurus_config(session)
    cfg.update(payload.botasaurus_config or {})
    run = Run(
        kind="agent",
        goal=payload.goal,
        start_url=payload.start_url,
        status="queued",
        botasaurus_config=json.dumps(cfg),
        model=payload.model or settings_store.get_model(session),
    )
    session.add(run)
    session.commit()
    run_manager.start_agent_run(run.id)
    return {"run_id": run.id}


@router.get("")
def list_runs(limit: int = 50, offset: int = 0, session: Session = Depends(get_session)):
    rows = (session.query(Run).order_by(Run.id.desc())
            .limit(min(limit, 200)).offset(offset).all())
    return {"runs": [_run_dict(r) for r in rows]}


def _get_run(session, run_id) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.get("/{run_id}")
def get_run(run_id: int, session: Session = Depends(get_session)):
    return _run_dict(_get_run(session, run_id), include_result=True)


@router.get("/{run_id}/steps")
def get_steps(run_id: int, after: int = -1, session: Session = Depends(get_session)):
    _get_run(session, run_id)
    rows = (session.query(RunStep)
            .filter(RunStep.run_id == run_id, RunStep.step_index > after)
            .order_by(RunStep.step_index).all())
    return {"steps": [{
        "step_index": s.step_index,
        "action": s.action,
        "status": s.status,
        "page_url": s.page_url,
        "selector": s.selector,
        "value": s.value,
        "error": s.error,
        "has_screenshot": bool(s.screenshot_path),
        "duration_ms": s.duration_ms,
        "detail": json.loads(s.detail) if s.detail else None,
        "created_at": s.created_at,
    } for s in rows]}


@router.get("/{run_id}/llm_calls")
def get_llm_calls(run_id: int, session: Session = Depends(get_session)):
    _get_run(session, run_id)
    rows = (session.query(LlmCall).filter(LlmCall.run_id == run_id)
            .order_by(LlmCall.id).all())
    return {"llm_calls": [{
        "id": c.id,
        "model": c.model,
        "purpose": c.purpose,
        "request_messages": json.loads(c.request_messages),
        "response_content": json.loads(c.response_content) if c.response_content else None,
        "prompt_tokens": c.prompt_tokens,
        "completion_tokens": c.completion_tokens,
        "latency_ms": c.latency_ms,
        "error": c.error,
        "created_at": c.created_at,
    } for c in rows]}


@router.get("/{run_id}/screenshots/{step_index}")
def get_screenshot(run_id: int, step_index: int, session: Session = Depends(get_session)):
    _get_run(session, run_id)
    step = (session.query(RunStep)
            .filter(RunStep.run_id == run_id, RunStep.step_index == step_index).first())
    if not step or not step.screenshot_path or not os.path.exists(step.screenshot_path):
        raise HTTPException(status_code=404, detail="screenshot not found")
    return FileResponse(step.screenshot_path, media_type="image/png")


@router.post("/{run_id}/cancel")
def cancel_run(run_id: int, session: Session = Depends(get_session)):
    run = _get_run(session, run_id)
    if run.status not in ("queued", "running"):
        raise HTTPException(status_code=409, detail=f"run is already {run.status}")
    if not run_manager.cancel(run_id):
        # no live thread (e.g. server restarted) — mark it directly
        run.status = "cancelled"
        run.error = "cancelled by user"
        run.finished_at = utcnow()
        session.commit()
    return {"ok": True}


@router.post("/{run_id}/save_recipe")
def save_recipe(run_id: int, payload: SaveRecipe, session: Session = Depends(get_session)):
    run = _get_run(session, run_id)
    result = json.loads(run.result) if run.result else {}
    steps = result.get("recorded_steps") or []
    if not steps:
        raise HTTPException(status_code=400, detail="run has no recorded steps to save")
    cfg = json.loads(run.botasaurus_config or "{}")
    definition = build_recipe_definition(
        name=payload.name,
        steps=steps,
        botasaurus_config=cfg,
        description=payload.description or run.goal,
        output_format=cfg.get("output_format", "json"),
        variablize=payload.variablize,
    )
    recipe = Recipe(
        name=payload.name,
        description=payload.description or run.goal,
        definition=json.dumps(definition),
        variables=json.dumps(definition["variables"]),
        source_run_id=run.id,
    )
    session.add(recipe)
    session.commit()
    return {"recipe_id": recipe.id}
