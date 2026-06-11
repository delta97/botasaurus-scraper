from datetime import datetime, timezone

from sqlalchemy import Column, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Setting(Base):
    __tablename__ = "settings"
    key = Column(Text, primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False, default=utcnow)


class Run(Base):
    __tablename__ = "runs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(Text, nullable=False)  # agent | replay
    goal = Column(Text)
    start_url = Column(Text, nullable=False)
    # queued | running | succeeded | failed | cancelled | max_steps
    status = Column(Text, nullable=False, default="queued")
    botasaurus_config = Column(Text, nullable=False, default="{}")  # JSON
    model = Column(Text)
    result = Column(Text)  # JSON
    error = Column(Text)
    recipe_id = Column(Integer, ForeignKey("recipes.id"))
    suite_run_id = Column(Integer, ForeignKey("suite_runs.id"))  # set for suite children
    total_prompt_tokens = Column(Integer, default=0)
    total_completion_tokens = Column(Integer, default=0)
    created_at = Column(Text, default=utcnow)
    started_at = Column(Text)
    finished_at = Column(Text)


class RunStep(Base):
    __tablename__ = "run_steps"
    __table_args__ = (UniqueConstraint("run_id", "step_index"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("runs.id"), nullable=False, index=True)
    step_index = Column(Integer, nullable=False)
    page_url = Column(Text)
    action = Column(Text, nullable=False)
    selector = Column(Text)
    value = Column(Text)
    status = Column(Text, nullable=False)  # ok | error | skipped
    error = Column(Text)
    screenshot_path = Column(Text)
    duration_ms = Column(Integer)
    detail = Column(Text)  # JSON
    created_at = Column(Text, default=utcnow)


class LlmCall(Base):
    __tablename__ = "llm_calls"
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("runs.id"), nullable=False, index=True)
    step_id = Column(Integer, ForeignKey("run_steps.id"))
    model = Column(Text, nullable=False)
    purpose = Column(Text, nullable=False)
    request_messages = Column(Text, nullable=False)  # JSON
    response_content = Column(Text)  # JSON
    prompt_tokens = Column(Integer)
    completion_tokens = Column(Integer)
    latency_ms = Column(Integer)
    error = Column(Text)
    created_at = Column(Text, default=utcnow)


class Recipe(Base):
    __tablename__ = "recipes"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    description = Column(Text)
    definition = Column(Text, nullable=False)  # canonical JSON
    variables = Column(Text)  # JSON [{name, default, description}]
    source_run_id = Column(Integer, ForeignKey("runs.id"))
    # self-healing: relocate a broken selector with the LLM during replay
    self_heal = Column(Integer, default=0)  # bool
    heal_mode = Column(Text, default="propose")  # 'propose' | 'auto'
    created_at = Column(Text, default=utcnow)
    updated_at = Column(Text, default=utcnow)


class RecipeHeal(Base):
    __tablename__ = "recipe_heals"
    id = Column(Integer, primary_key=True, autoincrement=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False, index=True)
    run_id = Column(Integer, ForeignKey("runs.id"))
    step_index = Column(Integer, nullable=False)
    original_selector = Column(Text)
    healed_selector = Column(Text)
    healed_fallbacks = Column(Text)  # JSON
    element_label = Column(Text)
    # proposed (awaiting review) | applied (auto-patched) | accepted | rejected
    status = Column(Text, nullable=False, default="proposed")
    llm_call_id = Column(Integer, ForeignKey("llm_calls.id"))
    created_at = Column(Text, default=utcnow)
    resolved_at = Column(Text)


class RecipeRun(Base):
    __tablename__ = "recipe_runs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False, index=True)
    run_id = Column(Integer, ForeignKey("runs.id"), nullable=False)
    variables_used = Column(Text)  # JSON
    created_at = Column(Text, default=utcnow)


class TestSuite(Base):
    __test__ = False  # not a pytest test class
    __tablename__ = "test_suites"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    description = Column(Text)
    created_at = Column(Text, default=utcnow)
    updated_at = Column(Text, default=utcnow)


class SuiteRecipe(Base):
    __tablename__ = "suite_recipes"
    id = Column(Integer, primary_key=True, autoincrement=True)
    suite_id = Column(Integer, ForeignKey("test_suites.id"), nullable=False, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)
    position = Column(Integer, nullable=False, default=0)
    variables = Column(Text)  # JSON: per-suite variable overrides for this recipe


class SuiteRun(Base):
    __tablename__ = "suite_runs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    suite_id = Column(Integer, ForeignKey("test_suites.id"), nullable=False, index=True)
    # queued | running | passed | failed | cancelled
    status = Column(Text, nullable=False, default="queued")
    total = Column(Integer, default=0)
    passed = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    created_at = Column(Text, default=utcnow)
    started_at = Column(Text)
    finished_at = Column(Text)
