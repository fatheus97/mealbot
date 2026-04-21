import re

from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlmodel import SQLModel

# These are pure Pydantic/SQLModel schemas for API communication
# They do NOT have table=True because they aren't database tables

class UserBase(SQLModel):
    email: EmailStr

class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        return v

class UserRead(UserBase):
    id: int
    country: str | None = None
    language: str
    measurement_system: str
    variability: str
    include_spices: bool
    track_snacks: bool
    onboarding_completed: bool
    is_demo: bool = False

class UserUpdate(SQLModel):
    country: str | None = None
    language: str | None = None
    measurement_system: str | None = None
    variability: str | None = None
    include_spices: bool | None = None
    track_snacks: bool | None = None
    onboarding_completed: bool | None = None

class MessageResponse(BaseModel):
    message: str


class Token(BaseModel):
    access_token: str
    token_type: str
    user_id: int
    email: str
    onboarding_completed: bool
    is_demo: bool = False
