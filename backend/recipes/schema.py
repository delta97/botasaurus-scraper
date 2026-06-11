"""Recipe DSL: validation, JSON<->YAML, and {{variable}} substitution.
The canonical form stored in the DB is JSON; YAML is an export format."""
import json
import re
from typing import List, Literal, Optional

import yaml
from pydantic import BaseModel, Field, ValidationError

STEP_TYPES = (
    "navigate", "click", "type", "select_option", "wait_for", "scroll",
    "extract_markdown", "extract_text", "screenshot", "run_js", "assert",
)

_VAR_PATTERN = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_SUBSTITUTABLE_FIELDS = ("url", "value", "label", "script", "text_contains")


class RecipeError(Exception):
    pass


class RecipeVariable(BaseModel):
    name: str
    default: str = ""
    description: Optional[str] = None


class BotasaurusConfig(BaseModel):
    headless: bool = True
    wait_for_complete_page_load: bool = True
    block_images: bool = False
    block_images_and_css: bool = False
    bypass_cloudflare: bool = False
    screenshots: bool = True
    proxy: Optional[str] = None
    user_agent: Optional[str] = None
    window_size: Optional[str] = None
    profile: Optional[str] = None
    max_retry: int = 0
    enable_xvfb_virtual_display: bool = False


class RecipeStep(BaseModel):
    type: Literal[STEP_TYPES]
    url: Optional[str] = None
    selector: Optional[str] = None
    selector_fallbacks: List[str] = Field(default_factory=list)
    fragile: bool = False
    value: Optional[str] = None
    label: Optional[str] = None
    to: Optional[str] = None
    into: Optional[str] = None
    script: Optional[str] = None
    name: Optional[str] = None
    text_contains: Optional[str] = None
    message: Optional[str] = None
    timeout: Optional[int] = None
    wait: Optional[int] = None
    bypass_cloudflare: bool = False
    optional: bool = False


class Recipe(BaseModel):
    version: int = 1
    name: str
    description: Optional[str] = None
    variables: List[RecipeVariable] = Field(default_factory=list)
    botasaurus: BotasaurusConfig = Field(default_factory=BotasaurusConfig)
    output_format: Literal["json", "markdown"] = "json"
    steps: List[RecipeStep] = Field(default_factory=list)


def validate_definition(definition: dict) -> Recipe:
    try:
        return Recipe.model_validate(definition)
    except ValidationError as exc:
        raise RecipeError(f"invalid recipe: {exc}") from exc


def load_recipe_text(text: str) -> Recipe:
    """Parse a recipe from a YAML or JSON string (YAML is a JSON superset)."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RecipeError(f"could not parse recipe file: {exc}") from exc
    if not isinstance(data, dict):
        raise RecipeError("recipe file must contain a mapping at the top level")
    return validate_definition(data)


def to_json(recipe: Recipe) -> str:
    return json.dumps(recipe.model_dump(exclude_none=True), indent=2)


def to_yaml(recipe: Recipe) -> str:
    return yaml.safe_dump(recipe.model_dump(exclude_none=True), sort_keys=False,
                          allow_unicode=True, default_flow_style=False)


def resolve_variables(recipe: Recipe, provided: Optional[dict] = None) -> dict:
    """Merge provided values over declared defaults."""
    values = {v.name: v.default for v in recipe.variables}
    for key, val in (provided or {}).items():
        values[key] = val
    return values


def substitute_step(step: RecipeStep, values: dict) -> RecipeStep:
    """Replace {{var}} placeholders. Unknown variable -> hard error, raised
    before any browser is launched."""
    data = step.model_dump()
    for fld in _SUBSTITUTABLE_FIELDS:
        text = data.get(fld)
        if not isinstance(text, str):
            continue

        def repl(match):
            var = match.group(1)
            if var not in values:
                raise RecipeError(f"unknown variable '{{{{{var}}}}}' in step '{step.type}'")
            return str(values[var])

        data[fld] = _VAR_PATTERN.sub(repl, text)
    return RecipeStep.model_validate(data)


def substitute_all(recipe: Recipe, provided: Optional[dict] = None) -> List[RecipeStep]:
    values = resolve_variables(recipe, provided)
    return [substitute_step(step, values) for step in recipe.steps]
