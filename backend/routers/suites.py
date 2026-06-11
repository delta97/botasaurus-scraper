"""Test suites: ordered groups of recipes run sequentially with aggregate
pass/fail and JUnit XML export for CI."""
import json
from xml.sax.saxutils import escape, quoteattr

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Recipe, Run, SuiteRecipe, SuiteRun, TestSuite, utcnow
from ..runs.manager import run_manager

router = APIRouter(prefix="/api/suites", tags=["suites"])


class CreateSuite(BaseModel):
    name: str = Field(min_length=1)
    description: str = None


class AddRecipe(BaseModel):
    recipe_id: int
    variables: dict = Field(default_factory=dict)


def _get_suite(session, suite_id) -> TestSuite:
    suite = session.get(TestSuite, suite_id)
    if suite is None:
        raise HTTPException(status_code=404, detail="suite not found")
    return suite


def _suite_run_dict(sr: SuiteRun):
    return {"id": sr.id, "suite_id": sr.suite_id, "status": sr.status,
            "total": sr.total, "passed": sr.passed, "failed": sr.failed,
            "created_at": sr.created_at, "started_at": sr.started_at,
            "finished_at": sr.finished_at}


@router.get("")
def list_suites(session: Session = Depends(get_session)):
    suites = session.query(TestSuite).order_by(TestSuite.id.desc()).all()
    counts = dict(session.query(SuiteRecipe.suite_id,
                                func.count(SuiteRecipe.id))
                  .group_by(SuiteRecipe.suite_id).all())
    return {"suites": [{
        "id": s.id, "name": s.name, "description": s.description,
        "recipe_count": counts.get(s.id, 0), "created_at": s.created_at,
    } for s in suites]}


@router.post("")
def create_suite(payload: CreateSuite, session: Session = Depends(get_session)):
    suite = TestSuite(name=payload.name, description=payload.description)
    session.add(suite)
    session.commit()
    return {"suite_id": suite.id}


@router.get("/{suite_id}")
def get_suite(suite_id: int, session: Session = Depends(get_session)):
    suite = _get_suite(session, suite_id)
    items = (session.query(SuiteRecipe, Recipe)
             .join(Recipe, SuiteRecipe.recipe_id == Recipe.id)
             .filter(SuiteRecipe.suite_id == suite_id)
             .order_by(SuiteRecipe.position, SuiteRecipe.id).all())
    runs = (session.query(SuiteRun).filter(SuiteRun.suite_id == suite_id)
            .order_by(SuiteRun.id.desc()).limit(20).all())
    return {
        "id": suite.id, "name": suite.name, "description": suite.description,
        "recipes": [{
            "suite_recipe_id": sr.id, "recipe_id": recipe.id, "name": recipe.name,
            "position": sr.position,
            "variables": json.loads(sr.variables) if sr.variables else {},
        } for sr, recipe in items],
        "runs": [_suite_run_dict(r) for r in runs],
    }


@router.delete("/{suite_id}")
def delete_suite(suite_id: int, session: Session = Depends(get_session)):
    suite = _get_suite(session, suite_id)
    session.query(SuiteRecipe).filter(SuiteRecipe.suite_id == suite_id).delete()
    session.delete(suite)
    session.commit()
    return {"ok": True}


@router.post("/{suite_id}/recipes")
def add_recipe(suite_id: int, payload: AddRecipe, session: Session = Depends(get_session)):
    _get_suite(session, suite_id)
    if session.get(Recipe, payload.recipe_id) is None:
        raise HTTPException(status_code=404, detail="recipe not found")
    max_pos = (session.query(func.max(SuiteRecipe.position))
               .filter(SuiteRecipe.suite_id == suite_id).scalar()) or 0
    item = SuiteRecipe(suite_id=suite_id, recipe_id=payload.recipe_id,
                       position=max_pos + 1,
                       variables=json.dumps(payload.variables) if payload.variables else None)
    session.add(item)
    session.commit()
    return {"suite_recipe_id": item.id}


@router.delete("/{suite_id}/recipes/{suite_recipe_id}")
def remove_recipe(suite_id: int, suite_recipe_id: int, session: Session = Depends(get_session)):
    item = session.get(SuiteRecipe, suite_recipe_id)
    if item is None or item.suite_id != suite_id:
        raise HTTPException(status_code=404, detail="suite recipe not found")
    session.delete(item)
    session.commit()
    return {"ok": True}


@router.post("/{suite_id}/run")
def run_suite(suite_id: int, session: Session = Depends(get_session)):
    _get_suite(session, suite_id)
    count = session.query(SuiteRecipe).filter(SuiteRecipe.suite_id == suite_id).count()
    if count == 0:
        raise HTTPException(status_code=400, detail="suite has no recipes")
    suite_run = SuiteRun(suite_id=suite_id, status="queued", total=count)
    session.add(suite_run)
    session.commit()
    run_manager.start_suite_run(suite_run.id)
    return {"suite_run_id": suite_run.id}


@router.get("/{suite_id}/runs/{suite_run_id}")
def get_suite_run(suite_id: int, suite_run_id: int, session: Session = Depends(get_session)):
    suite_run = session.get(SuiteRun, suite_run_id)
    if suite_run is None or suite_run.suite_id != suite_id:
        raise HTTPException(status_code=404, detail="suite run not found")
    children = (session.query(Run).filter(Run.suite_run_id == suite_run_id)
                .order_by(Run.id).all())
    data = _suite_run_dict(suite_run)
    data["children"] = [{
        "run_id": r.id, "recipe_id": r.recipe_id, "goal": r.goal,
        "status": r.status, "error": r.error,
        "started_at": r.started_at, "finished_at": r.finished_at,
    } for r in children]
    return data


@router.post("/{suite_id}/runs/{suite_run_id}/cancel")
def cancel_suite_run(suite_id: int, suite_run_id: int, session: Session = Depends(get_session)):
    suite_run = session.get(SuiteRun, suite_run_id)
    if suite_run is None or suite_run.suite_id != suite_id:
        raise HTTPException(status_code=404, detail="suite run not found")
    if suite_run.status not in ("queued", "running"):
        raise HTTPException(status_code=409, detail=f"suite run is already {suite_run.status}")
    if not run_manager.cancel_suite(suite_run_id):
        suite_run.status = "cancelled"
        suite_run.finished_at = utcnow()
        session.commit()
    return {"ok": True}


def _duration_seconds(started, finished):
    from datetime import datetime
    try:
        delta = datetime.fromisoformat(finished) - datetime.fromisoformat(started)
        return max(delta.total_seconds(), 0.0)
    except Exception:
        return 0.0


@router.get("/{suite_id}/runs/{suite_run_id}/junit.xml")
def junit_report(suite_id: int, suite_run_id: int, session: Session = Depends(get_session)):
    suite = _get_suite(session, suite_id)
    suite_run = session.get(SuiteRun, suite_run_id)
    if suite_run is None or suite_run.suite_id != suite_id:
        raise HTTPException(status_code=404, detail="suite run not found")
    children = (session.query(Run).filter(Run.suite_run_id == suite_run_id)
                .order_by(Run.id).all())

    total_time = sum(_duration_seconds(r.started_at, r.finished_at) for r in children)
    cases = []
    for r in children:
        name = (r.goal or f"run-{r.id}").replace("Suite run: ", "")
        time_s = _duration_seconds(r.started_at, r.finished_at)
        case = f'  <testcase classname={quoteattr(suite.name)} name={quoteattr(name)} time="{time_s:.2f}"'
        if r.status == "succeeded":
            cases.append(case + " />")
        elif r.status == "cancelled":
            cases.append(case + ">\n    <skipped />\n  </testcase>")
        else:
            cases.append(case + f">\n    <failure message={quoteattr(r.error or r.status)}>"
                         f"{escape(r.error or r.status)}</failure>\n  </testcase>")

    xml = (f'<?xml version="1.0" encoding="UTF-8"?>\n'
           f'<testsuite name={quoteattr(suite.name)} tests="{len(children)}" '
           f'failures="{suite_run.failed}" errors="0" time="{total_time:.2f}">\n'
           + "\n".join(cases) + "\n</testsuite>\n")
    return Response(xml, media_type="application/xml",
                    headers={"Content-Disposition":
                             f'attachment; filename="suite-{suite_id}-run-{suite_run_id}.xml"'})
