"""CLI recipe runner for cron / external scheduling. No LLM, no API key.

    python -m backend.runner path/to/recipe.yaml --var first_name=Jane
    python -m backend.runner --recipe-id 3 --var zip=10001 --out result.json
    python -m backend.runner recipe.yaml --no-log   # don't write run rows to the DB

Exit code 0 on success, 1 on failure.
"""
import argparse
import json
import sys
from pathlib import Path


def parse_vars(pairs):
    variables = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise SystemExit(f"--var must be name=value, got: {pair}")
        name, value = pair.split("=", 1)
        variables[name] = value
    return variables


def main(argv=None):
    parser = argparse.ArgumentParser(description="Replay a saved recipe (no AI involved)")
    parser.add_argument("recipe_file", nargs="?", help="recipe .yaml or .json file")
    parser.add_argument("--recipe-id", type=int, help="load recipe from the app database instead")
    parser.add_argument("--var", action="append", help="variable override: name=value")
    parser.add_argument("--headless", action="store_true", help="force headless mode")
    parser.add_argument("--out", help="write result JSON to this file")
    parser.add_argument("--self-heal", action="store_true",
                        help="relocate broken selectors with the LLM (needs an API key in the app DB)")
    parser.add_argument("--no-log", action="store_true",
                        help="don't record this run in the app database")
    args = parser.parse_args(argv)

    if not args.recipe_file and args.recipe_id is None:
        parser.error("provide a recipe file or --recipe-id")

    from . import db
    from .recipes.replay import replay_recipe
    from .recipes.schema import RecipeError, load_recipe_text

    variables = parse_vars(args.var)
    overrides = {"headless": True} if args.headless else None

    db.init_db()

    if args.recipe_id is not None:
        from .models import Recipe
        with db.SessionLocal() as session:
            row = session.get(Recipe, args.recipe_id)
            if row is None:
                raise SystemExit(f"recipe {args.recipe_id} not found in the database")
            definition = json.loads(row.definition)
            recipe_name = row.name
    else:
        text = Path(args.recipe_file).read_text()
        try:
            definition = load_recipe_text(text).model_dump(exclude_none=True)
        except RecipeError as exc:
            raise SystemExit(str(exc))
        recipe_name = definition.get("name", args.recipe_file)

    on_step = None
    run_id = None
    if args.no_log:
        def on_step(index, step, status, error, duration_ms, result):
            print(json.dumps({"step": index, "type": step.get("type"),
                              "status": status, "error": error,
                              "duration_ms": duration_ms}), file=sys.stderr)
    else:
        from .models import RecipeRun, Run, utcnow
        from .runs.logging import StepLogger
        with db.SessionLocal() as session:
            run = Run(kind="replay", goal=f"CLI replay: {recipe_name}",
                      start_url=next((s.get("url", "") for s in definition.get("steps", [])
                                      if s.get("type") == "navigate"), ""),
                      status="running", started_at=utcnow(),
                      botasaurus_config=json.dumps(definition.get("botasaurus", {})),
                      recipe_id=args.recipe_id)
            session.add(run)
            session.commit()
            run_id = run.id
            if args.recipe_id is not None:
                session.add(RecipeRun(recipe_id=args.recipe_id, run_id=run_id,
                                      variables_used=json.dumps(variables)))
                session.commit()
        logger = StepLogger(run_id)

        def on_step(index, step, status, error, duration_ms, result):
            logger.log_step(action=step.get("type"), status=status,
                            selector=step.get("selector"),
                            value=step.get("value") or step.get("label") or step.get("url"),
                            error=error, duration_ms=duration_ms)
            print(f"  [{status}] step {index}: {step.get('type')}"
                  + (f" — {error}" if error else ""), file=sys.stderr)

    # Self-healing needs a key; degrade gracefully so a cron replay never
    # crashes just because no key is configured.
    heal = None
    if args.self_heal:
        from . import settings_store
        from .recipes.replay import HealContext
        with db.SessionLocal() as session:
            api_key = settings_store.get_api_key(session)
            model = settings_store.get_model(session)
        if api_key:
            from .llm.openrouter import OpenRouterClient
            heal = HealContext(llm=OpenRouterClient(api_key=api_key, model=model),
                               mode="propose")
            print("self-healing enabled", file=sys.stderr)
        else:
            print("warning: --self-heal requested but no API key configured; "
                  "continuing without healing", file=sys.stderr)

    print(f"Replaying '{recipe_name}'...", file=sys.stderr)
    try:
        outcome = replay_recipe(definition, variables, overrides, on_step=on_step, heal=heal)
    except RecipeError as exc:
        raise SystemExit(str(exc))

    if run_id is not None:
        from .models import Run, utcnow
        with db.SessionLocal() as session:
            run = session.get(Run, run_id)
            run.status = "succeeded" if outcome["success"] else "failed"
            run.error = outcome["error"]
            run.result = json.dumps({"extracts": outcome["extracts"],
                                     "steps_executed": outcome["steps_executed"]})
            run.finished_at = utcnow()
            session.commit()

    output = json.dumps(outcome, indent=2, default=str)
    if args.out:
        Path(args.out).write_text(output)
    else:
        print(output)
    return 0 if outcome["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
