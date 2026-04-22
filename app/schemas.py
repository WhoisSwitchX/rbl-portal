from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime
from app.models import UserRole, BudgetStatus, ExpenseSubType, OldNew, ApprovalAction


class UserBase(BaseModel):
    full_name  : str
    email      : EmailStr
    role       : UserRole
    department : Optional[str] = None
    spoc_email : Optional[str] = None
    cost_code  : Optional[int] = None


class UserCreate(UserBase):
    password: str = Field(..., min_length=6)


class UserResponse(UserBase):
    id        : int
    is_active : bool
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type  : str = "bearer"
    role        : UserRole
    full_name   : str
    user_id     : int
