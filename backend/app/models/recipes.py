from typing import List, Optional
from pydantic import BaseModel, Field


class Recipe(BaseModel):
    id: int
    title: str
    ingredients: List[str]
    steps: List[str]
    cuisine: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
