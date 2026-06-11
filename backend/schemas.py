"""Pydantic request/response models for the REST API."""
from typing import Optional

from pydantic import BaseModel, Field


class SettingsUpdate(BaseModel):
    openrouter_api_key: Optional[str] = None
    openrouter_model: Optional[str] = None
    default_botasaurus_config: Optional[dict] = None


class CreateRun(BaseModel):
    goal: str = Field(min_length=3)
    start_url: str = Field(min_length=4)
    botasaurus_config: Optional[dict] = None
    model: Optional[str] = None


class SaveRecipe(BaseModel):
    name: str = Field(min_length=1)
    description: Optional[str] = None
    variablize: bool = True


class UpdateRecipe(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    definition: Optional[dict] = None


class ReplayRecipe(BaseModel):
    variables: dict = Field(default_factory=dict)
    botasaurus_overrides: Optional[dict] = None
