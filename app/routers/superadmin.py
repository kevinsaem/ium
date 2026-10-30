"""슈퍼 관리자 화면 — 협의체를 만들고 열어 준다.

이 화면에 오는 것은 협의체 목록과 사람 수뿐이다. 케이스도, 식별정보도, 매칭도 오지 않는다.
시스템 전체를 관리하는 사람이 당연히 다 볼 수 있다고 생각하기 쉬운데 이음에서는 아니다 —
협의체를 늘리는 권한과 그 안을 들여다보는 권한은 다른 권한이다 (app/permissions.py).

그래서 이 라우터에는 Case·Match·CaseIdentity 를 import 하지 않는다. 쓰지 않는 import 를
지운 게 아니라, 들여다볼 수 없다는 것을 코드에서 보이게 둔 것이다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import accounts, councils
from app.db import get_db
from app.deps import require_role
from app.models import Council, Role, User
from app.rendering import flash, render

router = APIRouter(prefix="/super", dependencies=[Depends(require_role(Role.SUPER))])
super_dep = require_role(Role.SUPER)


def _council(db: Session, council_id: int) -> Council:
    council = db.get(Council, council_id)
    if council is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="협의체를 찾을 수 없습니다.")
    return council


def _dashboard(request: Request, db: Session, user: User, **extra):
    rows = [
        {
            "council": c,
            "manager": councils.manager_of(db, c),
            "counts": councils.counts_for(db, c),
            "members": councils.members_of(db, c),
        }
        for c in councils.all_councils(db)
    ]
    return render(
        request,
        "super/councils.html",
        user,
        "councils",
        rows=rows,
        waiting=[r for r in rows if not r["council"].is_approved],
        **extra,
    )


@router.get("")
def dashboard(request: Request, user: User = Depends(super_dep), db: Session = Depends(get_db)):
    return _dashboard(request, db, user)


@router.post("/councils")
def register_council(
    request: Request,
    region: str = Form(...),
    dong: str = Form(...),
    slug: str = Form(...),
    region_code: str = Form(""),
    user: User = Depends(super_dep),
    db: Session = Depends(get_db),
):
    try:
        council = councils.register(
            db, user, region=region, dong=dong, slug=slug, region_code=region_code
        )
    except councils.CouncilError as exc:
        flash(request, str(exc))
        return RedirectResponse("/super", status_code=303)

    flash(
        request,
        f"{council.label} 협의체를 등록했습니다. 관리자를 발급하면 승인할 수 있습니다.",
    )
    return RedirectResponse("/super", status_code=303)


@router.post("/councils/{council_id}/manager")
def issue_manager(
    council_id: int,
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    note: str = Form(""),
    user: User = Depends(super_dep),
    db: Session = Depends(get_db),
):
    """협의체의 첫 관리자를 발급한다.

    임시 비밀번호는 이 응답 한 번에만 실어 보낸다. 리다이렉트로 돌려보내면서 세션에
    담으면 쿠키를 타고 브라우저에 남는다 — 위원 발급에서와 같은 이유다.
    """
    council = _council(db, council_id)
    try:
        manager, temp = accounts.issue_manager(
            db, user, council, name=name, email=email, note=note
        )
    except accounts.AccountError as exc:
        flash(request, str(exc))
        return RedirectResponse("/super", status_code=303)

    response = _dashboard(
        request,
        db,
        user,
        issued={"user": manager, "temp": temp, "council": council},
        flash=f"{council.label} 관리자 계정을 발급했습니다.",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/councils/{council_id}/manager/replace")
def replace_manager(
    council_id: int,
    request: Request,
    member_id: str = Form(""),
    user: User = Depends(super_dep),
    db: Session = Depends(get_db),
):
    """관리자를 교체한다 — 관리자가 연락이 안 될 때의 길이다."""
    council = _council(db, council_id)
    successor = db.get(User, int(member_id)) if member_id.isdigit() else None
    if successor is None:
        flash(request, "교체할 위원을 선택해 주세요.")
        return RedirectResponse("/super", status_code=303)

    try:
        councils.replace_manager(db, user, council, successor)
    except councils.CouncilError as exc:
        flash(request, str(exc))
        return RedirectResponse("/super", status_code=303)

    flash(request, f"{council.label} 관리자를 {successor.name}님으로 교체했습니다.")
    return RedirectResponse("/super", status_code=303)


@router.post("/councils/{council_id}/approve")
def approve_council(
    council_id: int,
    request: Request,
    user: User = Depends(super_dep),
    db: Session = Depends(get_db),
):
    council = _council(db, council_id)
    try:
        councils.approve(db, user, council)
    except councils.CouncilError as exc:
        flash(request, str(exc))
        return RedirectResponse("/super", status_code=303)

    flash(request, f"{council.label} 협의체를 승인했습니다. 전용 주소 /c/{council.slug} 가 열렸습니다.")
    return RedirectResponse("/super", status_code=303)


@router.post("/councils/{council_id}/suspend")
def suspend_council(
    council_id: int,
    request: Request,
    reason: str = Form(""),
    user: User = Depends(super_dep),
    db: Session = Depends(get_db),
):
    council = _council(db, council_id)
    try:
        councils.suspend(db, user, council, reason)
    except councils.CouncilError as exc:
        flash(request, str(exc))
        return RedirectResponse("/super", status_code=303)

    flash(request, f"{council.label} 협의체를 중지했습니다. 기록은 그대로 남습니다.")
    return RedirectResponse("/super", status_code=303)


@router.post("/councils/{council_id}/resume")
def resume_council(
    council_id: int,
    request: Request,
    user: User = Depends(super_dep),
    db: Session = Depends(get_db),
):
    council = _council(db, council_id)
    councils.resume(db, user, council)
    flash(request, f"{council.label} 협의체를 다시 열었습니다.")
    return RedirectResponse("/super", status_code=303)
