import pytest

from backend.agent.recorder import build_recipe_definition, variablize_steps
from backend.recipes.schema import (
    RecipeError,
    load_recipe_text,
    substitute_all,
    to_json,
    to_yaml,
    validate_definition,
)
from backend.secrets import deobfuscate, obfuscate

EXAMPLE = {
    "version": 1,
    "name": "lead-form",
    "variables": [{"name": "email", "default": "a@b.com"}],
    "botasaurus": {"headless": True, "block_images": True},
    "steps": [
        {"type": "navigate", "url": "https://example.com/quote"},
        {"type": "type", "selector": "input[name='email']", "value": "{{email}}"},
        {"type": "click", "selector": "button[type='submit']",
         "selector_fallbacks": ["form button"]},
        {"type": "assert", "selector": "#thanks", "message": "no confirmation"},
        {"type": "extract_markdown", "into": "confirmation"},
    ],
}


def test_validate_and_yaml_round_trip():
    recipe = validate_definition(EXAMPLE)
    yaml_text = to_yaml(recipe)
    reloaded = load_recipe_text(yaml_text)
    assert reloaded.model_dump(exclude_none=True) == recipe.model_dump(exclude_none=True)
    # JSON form parses as YAML too (YAML is a superset)
    assert load_recipe_text(to_json(recipe)).name == "lead-form"


def test_variable_substitution_defaults_and_overrides():
    recipe = validate_definition(EXAMPLE)
    steps = substitute_all(recipe)
    assert steps[1].value == "a@b.com"
    steps = substitute_all(recipe, {"email": "x@y.com"})
    assert steps[1].value == "x@y.com"


def test_unknown_variable_is_hard_error():
    bad = dict(EXAMPLE, steps=[{"type": "type", "selector": "i", "value": "{{nope}}"}])
    recipe = validate_definition(bad)
    with pytest.raises(RecipeError, match="unknown variable"):
        substitute_all(recipe)


def test_invalid_step_type_rejected():
    with pytest.raises(RecipeError):
        validate_definition(dict(EXAMPLE, steps=[{"type": "explode"}]))


def test_variablize_turns_typed_values_into_variables():
    steps = [
        {"type": "navigate", "url": "https://example.com"},
        {"type": "type", "selector": "input[name='email']", "value": "joe@x.com"},
        {"type": "type", "selector": "input[name='zip']", "value": "94107"},
    ]
    new_steps, variables = variablize_steps(steps)
    assert new_steps[1]["value"] == "{{email}}"
    assert new_steps[2]["value"] == "{{zip}}"
    assert {"name": "email", "default": "joe@x.com"} in variables


def test_build_recipe_definition_is_valid_and_replayable():
    steps = [
        {"type": "navigate", "url": "https://example.com"},
        {"type": "type", "selector": "input[name='email']", "value": "joe@x.com"},
    ]
    definition = build_recipe_definition(
        "test", steps, {"headless": True, "screenshots": False, "output_format": "json"})
    recipe = validate_definition(definition)
    resolved = substitute_all(recipe)
    assert resolved[1].value == "joe@x.com"


def test_secret_obfuscation_round_trip():
    key = "sk-or-v1-abcdef0123456789"
    stored = obfuscate(key)
    assert key not in stored
    assert stored.startswith("obf:")
    assert deobfuscate(stored) == key
    assert deobfuscate("plaintext") == "plaintext"
