"""Failure notifications via a generic webhook (Slack/Discord compatible).

The payload carries both `text` (Slack incoming webhooks) and `content`
(Discord) plus the structured fields, so one URL setting works everywhere.
Fired from run worker threads — always best-effort, never raises.
"""
import json

import httpx

from . import db, settings_store

NOTIFY_STATUSES = {"failed", "max_steps"}


def _payload(kind, title, status, error, extra=None):
    summary = f"❌ {kind} {title!r} {status}" + (f": {error}" if error else "")
    body = {
        "text": summary,
        "content": summary,
        "kind": kind,
        "status": status,
        "error": error,
    }
    body.update(extra or {})
    return body


def post_webhook(payload):
    with db.SessionLocal() as session:
        url = settings_store.get_webhook_url(session)
    if not url:
        return False
    try:
        httpx.post(url, json=payload, timeout=10.0)
        return True
    except Exception as exc:
        print(f"webhook notification failed: {exc}")
        return False


def notify_run_finished(run_id):
    """Called after a run reaches a terminal state; posts only on failure."""
    from .models import Run
    with db.SessionLocal() as session:
        run = session.get(Run, run_id)
    if run is None or run.status not in NOTIFY_STATUSES:
        return False
    return post_webhook(_payload(
        f"{run.kind} run", run.goal or run.start_url, run.status, run.error,
        {"run_id": run.id, "start_url": run.start_url},
    ))


def notify_suite_finished(suite_run_id):
    from .models import SuiteRun, TestSuite
    with db.SessionLocal() as session:
        suite_run = session.get(SuiteRun, suite_run_id)
        suite = session.get(TestSuite, suite_run.suite_id) if suite_run else None
    if suite_run is None or suite_run.status != "failed":
        return False
    return post_webhook(_payload(
        "suite", suite.name if suite else f"#{suite_run.suite_id}", "failed",
        f"{suite_run.failed}/{suite_run.total} recipes failed",
        {"suite_run_id": suite_run.id, "suite_id": suite_run.suite_id,
         "passed": suite_run.passed, "failed": suite_run.failed, "total": suite_run.total},
    ))
