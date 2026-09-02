"""产品内登录和改密的 API 数据结构。"""

from pydantic import BaseModel, Field


class AuthConfigOut(BaseModel):
    login_required: bool
    password_change_supported: bool
    global_search_enabled: bool
    knowledge_qa_enabled: bool
    retrospective_center_enabled: bool
    retrospective_ai_draft_enabled: bool
    quant_research_enabled: bool
    quant_demo_enabled: bool


class LoginIn(BaseModel):
    user_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=10, max_length=128)


class AuthUserOut(BaseModel):
    user_id: str
    teams: list[str]
    must_change_password: bool


class AuthSessionOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: AuthUserOut
