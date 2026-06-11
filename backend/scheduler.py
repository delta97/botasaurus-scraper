"""In-app cron scheduler (APScheduler). Schedules live in our own `schedules`
table (not APScheduler's jobstore, to avoid pickling app callables); jobs are
rebuilt from the table at startup and kept in sync as schedules change.

The server must stay running for schedules to fire. The CLI runner + external
cron remain available for setups where that's not desirable.
"""
import json

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import config, db
from .models import Recipe, Run, Schedule, utcnow

_scheduler = None


def _fire(schedule_id):
    """Run the schedule's recipe with its variable overrides."""
    from . import settings_store
    from .runs.manager import run_manager

    with db.SessionLocal() as session:
        schedule = session.get(Schedule, schedule_id)
        if schedule is None or not schedule.enabled:
            return
        recipe = session.get(Recipe, schedule.recipe_id)
        if recipe is None:
            return
        definition = json.loads(recipe.definition)
        variables = json.loads(schedule.variables) if schedule.variables else {}
        cfg = definition.get("botasaurus", {})
        first_nav = next((s for s in definition.get("steps", [])
                          if s.get("type") == "navigate"), None)
        run = Run(kind="replay", goal=f"Scheduled: {recipe.name}",
                  start_url=(first_nav or {}).get("url", ""), status="queued",
                  botasaurus_config=json.dumps(cfg), recipe_id=recipe.id)
        session.add(run)
        session.commit()
        run_id = run.id
        schedule.last_run_at = utcnow()
        schedule.last_run_id = run_id
        self_heal = bool(recipe.self_heal)
        api_key = settings_store.get_api_key(session) if self_heal else None
        model = settings_store.get_model(session) if self_heal else None
        session.commit()

    run_manager.start_replay_run(
        run_id, definition, variables, recipe_id=schedule.recipe_id,
        self_heal=self_heal and bool(api_key),
        heal_mode=recipe.heal_mode or "propose", api_key=api_key, model=model)


def _job_id(schedule_id):
    return f"schedule-{schedule_id}"


def add_job(schedule):
    """(Re)register a job for a Schedule row. No-op if scheduler isn't started."""
    if _scheduler is None:
        return
    remove_job(schedule.id)
    if not schedule.enabled:
        return
    try:
        trigger = CronTrigger.from_crontab(schedule.cron)
    except ValueError:
        return  # invalid cron; surfaced at create time by validate_cron
    _scheduler.add_job(_fire, trigger=trigger, args=[schedule.id],
                       id=_job_id(schedule.id), replace_existing=True)


def remove_job(schedule_id):
    if _scheduler is None:
        return
    if _scheduler.get_job(_job_id(schedule_id)):
        _scheduler.remove_job(_job_id(schedule_id))


def validate_cron(expr):
    try:
        CronTrigger.from_crontab(expr)
        return True
    except (ValueError, TypeError):
        return False


def start():
    """Start the scheduler and register all enabled schedules. Idempotent."""
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.start()
    with db.SessionLocal() as session:
        for schedule in session.query(Schedule).filter(Schedule.enabled == 1).all():
            add_job(schedule)


def shutdown():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
