"""로그인 · 가입.

로그인 방법이 역할마다 다르다 (위원회 결정, 안건 07).

- 위원·운영자: 이메일 + 비밀번호. 운영자가 계정을 발급한다.
- 후원자: 휴대폰 번호 + 숫자 4자리. 직접 가입하거나, 운영자·위원이 대신 등록해 준다.

한 화면에 두 칸을 같이 두고 들어온 값으로 갈라 보낸다. 가게를 하다 잠깐 들어오는 분에게
"어느 쪽 로그인인지" 를 먼저 고르게 하고 싶지 않았다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import accounts
from app.config import settings
from app.db import get_db
from app.deps import current_user_optional
from app.models import Role, User
from app.rendering import HOME, templates
from app.security import PIN_LENGTH, verify_password

router = APIRouter()


def _demo_users(db: Session) -> list[User]:
    """로그인 화면의 계정 바로가기 — 개발 전용. 운영에서 켜 두면 위원·운영자 명단이 공개된다."""
    if settings.is_production:
        return []
    return list(db.scalars(select(User).order_by(User.role, User.id)).all())


def _page(request: Request, db: Session, template: str, **extra):
    return templates.TemplateResponse(
        request,
        template,
        {
            "error": request.session.pop("flash", None),
            "demo_users": _demo_users(db),
            "settings": settings,
            "pin_length": PIN_LENGTH,
            **extra,
        },
    )


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
    return _page(request, db, "auth/login.html", email=email)


def _deny(request: Request, message: str):
    request.session["flash"] = message
    return RedirectResponse("/login", status_code=303)


def _start_session(request: Request, user: User):
    request.session.clear()
    request.session["uid"] = user.id
    if user.must_change_password:
        return RedirectResponse("/account/password", status_code=303)
    return RedirectResponse(HOME[user.role], status_code=303)


def _sign_in(request: Request, db: Session, user: User | None, secret: str, wrong: str):
    """계정을 찾았는지와 비밀번호가 맞는지를 한 문장으로 답한다.

    "그런 번호 없습니다" 와 "번호는 맞는데 숫자가 틀립니다" 를 구분해 주면, 어떤 번호가
    등록되어 있는지 알려 주는 셈이 된다.
    """
    if user is None:
        return _deny(request, wrong)

    locked = accounts.lock_remaining(user)
    if locked:
        return _deny(request, f"연속 실패로 잠겼습니다. {locked}분 후에 다시 시도해 주세요.")

    if not verify_password(secret, user.password_hash):
        left = accounts.record_failure(db, user)
        if left == 0:
            return _deny(
                request,
                f"{accounts.MAX_FAILED_LOGINS}회 연속 틀려 "
                f"{accounts.LOCK_MINUTES}분간 잠겼습니다.",
            )
        return _deny(request, f"{wrong} ({left}번 남음)")

    if not user.is_active:
        return _deny(request, "위촉이 해제된 계정입니다. 운영자에게 문의하세요.")

    accounts.unlock(db, user)
    return _start_session(request, user)


@router.post("/login")
def login(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    phone: str = Form(""),
    pin: str = Form(""),
    db: Session = Depends(get_db),
):
    if phone.strip() or pin.strip():
        try:
            donor = accounts.find_donor_by_phone(db, phone)
        except accounts.AccountError as exc:
            return _deny(request, str(exc))
        return _sign_in(
            request, db, donor, pin, f"휴대폰 번호 또는 숫자 {PIN_LENGTH}자리가 올바르지 않습니다."
        )

    user = db.scalar(select(User).where(User.email == email.strip().lower())) if email.strip() else None
    return _sign_in(request, db, user, password, "이메일 또는 비밀번호가 올바르지 않습니다.")


@router.get("/signup")
def signup_form(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user_optional),
):
    """후원자 직접 가입 — 로그인 없이 들어온다."""
    if user is not None:
        return RedirectResponse(HOME[user.role], status_code=303)
    return _page(request, db, "auth/signup.html")


@router.post("/signup")
def signup(
    request: Request,
    name: str = Form(""),
    phone: str = Form(""),
    pin: str = Form(""),
    confirm: str = Form(""),
    shop_name: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        donor = accounts.signup_donor(
            db, name=name, phone=phone, pin=pin, confirm=confirm, shop_name=shop_name
        )
    except accounts.AccountError as exc:
        request.session["flash"] = str(exc)
        return RedirectResponse("/signup", status_code=303)

    request.session["flash"] = f"{donor.name}님, 가입했습니다. 나눔글을 올려 보세요."
    return _start_session(request, donor)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
