"""내 계정 — 비밀번호 바꾸기.

임시 비밀번호로 들어온 사람은 여기서 새 비밀번호를 정하기 전까지 다른 화면을 쓸 수 없다
(app/deps.py 의 PasswordChangeRequired). 그래서 이 라우터는 역할 대신 로그인만 확인한다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import accounts
from app.db import get_db
from app.deps import current_user
from app.models import User
from app.rendering import HOME, flash, render
from app.security import MIN_PASSWORD_LENGTH

router = APIRouter(prefix="/account")


@router.get("/password")
def password_form(request: Request, user: User = Depends(current_user)):
    forced = user.must_change_password
    # 변경 전에는 하단 탭을 숨긴다. 눌러 봐야 이 화면으로 되돌아올 뿐이다.
    hide_tabs = {"tabs": []} if forced else {}
    return render(
        request,
        "account/password.html",
        user,
        "",
        forced=forced,
        min_length=MIN_PASSWORD_LENGTH,
        home=HOME[user.role],
        **hide_tabs,
    )


@router.post("/password")
def change_password(
    request: Request,
    current_password: str = Form(""),
    new_password: str = Form(""),
    confirm_password: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    try:
        accounts.change_password(
            db, user, current=current_password, new=new_password, confirm=confirm_password
        )
    except accounts.AccountError as exc:
        flash(request, str(exc))
        return RedirectResponse("/account/password", status_code=303)

    flash(request, "비밀번호를 바꿨습니다.")
    return RedirectResponse(HOME[user.role], status_code=303)
