import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..agent.selectors import SELECTOR_SPEC_VERSION
from ..auth import require_pairing_token
from ..db import get_session
from ..models import Recipe, RecipeRun, Run, utcnow
from ..recipes.schema import RecipeError, to_json, to_yaml, validate_definition
from ..runs.manager import run_manager
from ..schemas import CreateRecipe, ReplayRecipe, UpdateRecipe

router = APIRouter(prefix="/api/recipes", tags=["recipes"])


@router.post("", dependencies=[Depends(require_pairing_token)])
def create_recipe(payload: CreateRecipe, session: Session = Depends(get_session)):
    """Create a recipe directly from a definition. Used by the Chrome extension
    recorder (token-gated) and as a generic import path."""
    try:
        validated = validate_definition(payload.definition)
    except RecipeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    incoming_version = validated.selector_spec_version
    warning = None
    if incoming_version is not None and incoming_version != SELECTOR_SPEC_VERSION:
        warning = (f"recording used selector spec v{incoming_version}, server is "
                   f"v{SELECTOR_SPEC_VERSION}; selectors may differ — update the extension")

    definition = payload.definition
    recipe = Recipe(
        name=payload.name,
        description=payload.description,
        definition=json.dumps(definition),
        variables=json.dumps([v.model_dump() for v in validated.variables]),
    )
    session.add(recipe)
    session.commit()
    return {"recipe_id": recipe.id, "warning": warning}


def _get_recipe(session, recipe_id) -> Recipe:
    recipe = session.get(Recipe, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail="recipe not found")
    return recipe


def _recipe_dict(recipe: Recipe, include_definition=True):
    data = {
        "id": recipe.id,
        "name": recipe.name,
        "description": recipe.description,
        "variables": json.loads(recipe.variables) if recipe.variables else [],
        "source_run_id": recipe.source_run_id,
        "created_at": recipe.created_at,
        "updated_at": recipe.updated_at,
    }
    if include_definition:
        data["definition"] = json.loads(recipe.definition)
    return data


@router.get("")
def list_recipes(session: Session = Depends(get_session)):
    rows = session.query(Recipe).order_by(Recipe.id.desc()).all()
    return {"recipes": [_recipe_dict(r, include_definition=False) for r in rows]}


@router.get("/{recipe_id}")
def get_recipe(recipe_id: int, session: Session = Depends(get_session)):
    recipe = _get_recipe(session, recipe_id)
    data = _recipe_dict(recipe)
    replays = (session.query(RecipeRun, Run)
               .join(Run, RecipeRun.run_id == Run.id)
               .filter(RecipeRun.recipe_id == recipe_id)
               .order_by(RecipeRun.id.desc()).limit(20).all())
    data["replays"] = [{
        "run_id": run.id,
        "status": run.status,
        "variables_used": json.loads(rr.variables_used) if rr.variables_used else {},
        "created_at": rr.created_at,
    } for rr, run in replays]
    return data


@router.put("/{recipe_id}")
def update_recipe(recipe_id: int, payload: UpdateRecipe, session: Session = Depends(get_session)):
    from ..models import utcnow
    recipe = _get_recipe(session, recipe_id)
    if payload.definition is not None:
        try:
            validated = validate_definition(payload.definition)
        except RecipeError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        recipe.definition = json.dumps(payload.definition)
        recipe.variables = json.dumps([v.model_dump() for v in validated.variables])
    if payload.name is not None:
        recipe.name = payload.name
    if payload.description is not None:
        recipe.description = payload.description
    recipe.updated_at = utcnow()
    session.commit()
    return _recipe_dict(recipe)


@router.delete("/{recipe_id}")
def delete_recipe(recipe_id: int, session: Session = Depends(get_session)):
    recipe = _get_recipe(session, recipe_id)
    session.query(RecipeRun).filter(RecipeRun.recipe_id == recipe_id).delete()
    session.delete(recipe)
    session.commit()
    return {"ok": True}


@router.get("/{recipe_id}/export")
def export_recipe(recipe_id: int, format: str = "yaml", session: Session = Depends(get_session)):
    recipe = _get_recipe(session, recipe_id)
    validated = validate_definition(json.loads(recipe.definition))
    safe_name = "".join(c if c.isalnum() or c in "-_" else "-" for c in recipe.name) or "recipe"
    if format == "json":
        return Response(
            to_json(validated), media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.json"'})
    return Response(
        to_yaml(validated), media_type="application/yaml",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.yaml"'})


@router.post("/{recipe_id}/replay")
def replay(recipe_id: int, payload: ReplayRecipe, session: Session = Depends(get_session)):
    recipe = _get_recipe(session, recipe_id)
    definition = json.loads(recipe.definition)
    validated = validate_definition(definition)

    cfg = validated.botasaurus.model_dump()
    cfg.update(payload.botasaurus_overrides or {})

    first_nav = next((s for s in validated.steps if s.type == "navigate"), None)
    run = Run(
        kind="replay",
        goal=f"Replay recipe: {recipe.name}",
        start_url=first_nav.url if first_nav else "",
        status="queued",
        botasaurus_config=json.dumps(cfg),
        recipe_id=recipe.id,
    )
    session.add(run)
    session.commit()
    session.add(RecipeRun(recipe_id=recipe.id, run_id=run.id,
                          variables_used=json.dumps(payload.variables)))
    session.commit()

    run_manager.start_replay_run(run.id, definition, payload.variables,
                                 payload.botasaurus_overrides)
    return {"run_id": run.id}
