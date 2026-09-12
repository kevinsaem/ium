from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import current_user_optional
from app.models import User
from app.rendering import HOME, templates
from app.security import verify_password

router = APIRouter()


def _demo_users(db: Session) -> list[User]:
    """로그인 화면의 계정 바로가기 — 개발 전용. 운영에서 켜 두면 위원·운영자 명단이 공개된다."""
    if settings.is_production:
        return []
    return list(db.scalars(select(User).order_by(User.role, User.id)).all())


@router.get("/")
def root(user: User | None = Depends(current_user_optional)):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return RedirectResponse(HOME[user.role], status_code=303)


@router.get("/login")
def login_form(
    request: Request,
    email: str | None = None,
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user_optional),
):
    if user is not None:
        return RedirectResponse(HOME[user.role], status_code=303)
    return templates.TemplateResponse(
        request,
        "auth/login.html",
        {"email": email, "error": request.session.pop("flash", None),
         "demo_users": _demo_users(db), "settings": settings},
    )


@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not verify_password(password, user.password_hash):
        request.session["flash"] = "이메일 또는 비밀번호가 올바르지 않습니다."
        return RedirectResponse("/login", status_code=303)
    if not user.is_active:
        request.session["flash"] = "위촉이 해제된 계정입니다. 운영자에게 문의하세요."
        return RedirectResponse("/login", status_code=303)

    request.session.clear()
    request.session["uid"] = user.id
    return RedirectResponse(HOME[user.role], status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
