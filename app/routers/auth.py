"""로그인 · 가입.

로그인 방법이 역할마다 다르다 (위원회 결정, 안건 07).

- 위원: 이메일 + 비밀번호. 관리자가 계정을 발급한다.
- 후원자: 휴대폰 번호 + 숫자 4자리. 직접 가입하거나, 위원이 대신 등록해 준다.

한 화면에 두 칸을 같이 두고 들어온 값으로 갈라 보낸다. 가게를 하다 잠깐 들어오는 분에게
"어느 쪽 로그인인지" 를 먼저 고르게 하고 싶지 않았다.

가입만 협의체별 주소를 쓴다 (/c/<slug>/signup). 로그인은 그렇지 않다 — 전화번호와 숫자로
사람을 찾아 그 사람의 소속으로 보내면 되는데, 주소에 동까지 적게 하면 "우리 동 주소가
뭐였지" 를 매번 기억해야 한다. 가입은 사정이 다르다. 들어온 사람이 어느 협의체 소속이
되는지를 정할 단서가 주소밖에 없다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import accounts, devices
from app.config import settings
from app.db import get_db
from app import deps
from app.deps import current_user_optional
from app.models import Council, Role, User
from app.rendering import HOME, templates
from app.security import PIN_LENGTH, verify_password

router = APIRouter()


def _demo_users(db: Session) -> list[User]:
    """로그인 화면의 계정 바로가기 — 개발 전용. 운영에서 켜 두면 위원 명단이 공개된다."""
    if settings.is_production:
        return []
    return list(db.scalars(select(User).order_by(User.role, User.id)).all())


def _sole_council(db: Session):
    """협의체가 딱 하나 열려 있으면 그 협의체. 아니면 None.

    로그인 화면은 로그인 전이라 어느 협의체인지 알 수 없다. 협의체가 하나뿐일 때만
    그 협의체의 이야기를 할 수 있고, 여러 개면 아무 동 이름도 적지 않는 게 맞다.

    협의체를 못 찾는 것을 오류로 다루지 않는 것이 중요하다. 로그인 화면이 협의체에
    의존하면, 그 협의체가 중지된 순간 로그인 화면 자체가 열리지 않고 — 중지를 되돌릴
    슈퍼 관리자도 들어올 수 없게 된다. 실제로 그렇게 됐다.
    """
    councils = list(
        db.scalars(
            select(Council).where(Council.is_active.is_(True), Council.approved_at.is_not(None))
        ).all()
    )
    return councils[0] if len(councils) == 1 else None


def _team_contact_value(db: Session) -> str | None:
    from app import retention

    council = _sole_council(db)
    return retention.current(db, council).team_contact if council is not None else None


def _login_dong(db: Session) -> str | None:
    """로그인·가입 화면에 적을 동 이름. 모르면 None 이다.

    협의체가 여럿일 때 설정값으로 떨어뜨리면 안 된다. 그러면 선부2동 주민이 보는
    로그인 화면에 "선부3동 지역사회보장협의체" 가 적힌다 — 틀린 이름을 적는 것보다
    아무 이름도 적지 않는 쪽이 낫다. 화면은 dong 이 비면 동 없이 말한다.
    """
    council = _sole_council(db)
    return council.dong if council is not None else None


def _page(request: Request, db: Session, template: str, **extra):
    return templates.TemplateResponse(
        request,
        template,
        {
            "error": request.session.pop("flash", None),
            "demo_users": _demo_users(db),
            "settings": settings,
            "pin_length": PIN_LENGTH,
            "team_contact": _team_contact_value(db),
            "council": None,
            "dong": _login_dong(db),
            "action": "/signup",
            **extra,
        },
    )


@router.get("/")
def root(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user_optional),
):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if user.role is Role.MEMBER and not user.is_approved:
        # 승인 대기 위원을 역할 홈으로 보내면 그 화면이 403 을 내고, 403 은 홈으로
        # 되돌리고, 홈은 다시 역할 홈으로 보낸다. 여기서 끊는다.
        return _page(request, db, "auth/pending.html", pending_user=user)
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

    # 기억된 기기면 숫자를 묻지 않는다 (위원회 결정, 안건 13). 30일이 지나면 토큰이 만료돼
    # 여기서 걸러지고, 그때 다시 숫자를 받는다.
    remembered = devices.resolve(db, request.cookies.get(devices.COOKIE_NAME))
    if remembered is not None:
        request.session.clear()
        request.session["uid"] = remembered.id
        return RedirectResponse(HOME[remembered.role], status_code=303)

    return _page(request, db, "auth/login.html", email=email)


def _contact(db: Session) -> str:
    """잠긴 분에게 어디로 연락할지 알려 준다 (위원회 결정, 안건 15).

    잠금이 시간이 지나 풀리지 않으므로, 연락처가 없으면 들어올 길이 없다.
    """
    from app import retention

    council = _sole_council(db)
    contact = retention.current(db, council).team_contact if council is not None else None
    if contact:
        return f"운영팀에 연락해 주세요 — {contact}"
    return "운영팀에 연락해 잠금을 풀어 주세요."


def _deny(request: Request, message: str):
    request.session["flash"] = message
    return RedirectResponse("/login", status_code=303)


def _start_session(request: Request, user: User):
    request.session.clear()
    request.session["uid"] = user.id
    if user.must_change_password:
        return RedirectResponse("/account/password", status_code=303)
    if user.role is Role.MEMBER and not user.is_approved:
        # 역할 홈으로 보내면 그 화면이 403 을 내고, 그 안내 문구가 방금 띄운 "가입
        # 신청이 접수되었습니다" 를 덮어쓴다. 승인 대기 화면으로 바로 보낸다.
        return RedirectResponse("/", status_code=303)
    return RedirectResponse(HOME[user.role], status_code=303)


def _remember_device(request: Request, db: Session, user: User, response):
    """후원자 기기만 기억한다.

    위원는 식별정보와 승인 권한이 걸려 있어 기억해 두지 않는다. 결정도 후원자를
    두고 한 이야기였다 ("본인 기기는 한동안 인증 없이 사용하고").
    """
    if user.role is not Role.DONOR or user.must_change_password:
        return response
    token = devices.remember(db, user, request.headers.get("user-agent"))
    devices.set_cookie(response, token)
    return response


def _sign_in(request: Request, db: Session, user: User | None, secret: str, wrong: str):
    """계정을 찾았는지와 비밀번호가 맞는지를 한 문장으로 답한다.

    "그런 번호 없습니다" 와 "번호는 맞는데 숫자가 틀립니다" 를 구분해 주면, 어떤 번호가
    등록되어 있는지 알려 주는 셈이 된다.
    """
    if user is None:
        return _deny(request, wrong)

    if accounts.is_locked(user):
        return _deny(request, f"연속 실패로 잠긴 계정입니다. {_contact(db)}")

    if not verify_password(secret, user.password_hash):
        left = accounts.record_failure(db, user)
        if left == 0:
            return _deny(
                request,
                f"{accounts.MAX_FAILED_LOGINS}회 연속 틀려 계정이 잠겼습니다. {_contact(db)}",
            )
        return _deny(request, f"{wrong} ({left}번 남음)")

    if not user.is_active:
        return _deny(request, "위촉이 해제된 계정입니다. 관리자에게 문의하세요.")

    if not deps._council_is_open(user):
        # 비밀번호를 맞힌 뒤에 알려 준다. 틀린 비밀번호와 같은 자리에서 막으면 어느
        # 협의체가 중지됐는지를 비밀번호 없이도 알아낼 수 있다.
        return _deny(request, "협의체 운영이 중지되어 로그인할 수 없습니다. 운영팀에 문의하세요.")

    accounts.unlock(db, user)
    return _remember_device(request, db, user, _start_session(request, user))


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


def _signup_page(request: Request, db: Session, council):
    """가입 화면. 협의체가 정해져 있으면 그 동 이름으로 말한다."""
    return _page(
        request,
        db,
        "auth/signup.html",
        council=council,
        dong=council.dong if council is not None else settings.dong,
        action=f"/c/{council.slug}/signup" if council is not None else "/signup",
    )


def _do_signup(request: Request, db: Session, council, back: str, **fields):
    try:
        donor = accounts.signup_donor(
            db, council_id=council.id if council is not None else None, **fields
        )
    except accounts.AccountError as exc:
        request.session["flash"] = str(exc)
        return RedirectResponse(back, status_code=303)

    request.session["flash"] = f"{donor.name}님, 가입했습니다. 나눔글을 올려 보세요."
    return _remember_device(request, db, donor, _start_session(request, donor))


@router.get("/signup")
def signup_form(
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user_optional),
):
    """협의체를 적지 않은 가입 주소 — 파일럿 협의체로 보낸다.

    협의체가 하나였을 때 돌린 주소라 남겨 둔다. 지금 지우면 이미 카톡으로 돌아다니는
    주소가 404 가 된다. 협의체가 여러 개인 상태에서 이 주소로 들어오면 어느 동인지
    알 수 없으므로, 파일럿 협의체의 주소로 보내 그 동 이름을 보고 들어왔는지
    확인하게 한다.
    """
    if user is not None:
        return RedirectResponse(HOME[user.role], status_code=303)
    from app import tenancy

    try:
        council = tenancy.default(db)
    except tenancy.CouncilNotFound:
        return _signup_page(request, db, None)
    return RedirectResponse(f"/c/{council.slug}/signup", status_code=303)


@router.get("/c/{slug}/signup")
def council_signup_form(
    slug: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user_optional),
):
    """협의체 전용 가입 주소 — 후원자에게 전하는 주소다 (안건 13).

    승인되지 않았거나 중지된 협의체의 주소는 404 다 (app/tenancy.py 의 by_slug).
    준비가 끝나기 전에 주소를 뿌려 주민을 받는 길을 막는다.
    """
    from app import tenancy

    if user is not None:
        return RedirectResponse(HOME[user.role], status_code=303)
    return _signup_page(request, db, tenancy.by_slug(db, slug))


@router.post("/signup")
def signup(
    request: Request,
    name: str = Form(""),
    phone: str = Form(""),
    pin: str = Form(""),
    confirm: str = Form(""),
    shop_name: str = Form(""),
    address: str = Form(""),
    postal_code: str = Form(""),
    db: Session = Depends(get_db),
):
    return _do_signup(
        request, db, None, "/signup",
        name=name, phone=phone, pin=pin, confirm=confirm,
        shop_name=shop_name, address=address, postal_code=postal_code,
    )


@router.post("/c/{slug}/signup")
def council_signup(
    slug: str,
    request: Request,
    name: str = Form(""),
    phone: str = Form(""),
    pin: str = Form(""),
    confirm: str = Form(""),
    shop_name: str = Form(""),
    address: str = Form(""),
    postal_code: str = Form(""),
    db: Session = Depends(get_db),
):
    from app import tenancy

    council = tenancy.by_slug(db, slug)
    return _do_signup(
        request, db, council, f"/c/{council.slug}/signup",
        name=name, phone=phone, pin=pin, confirm=confirm,
        shop_name=shop_name, address=address, postal_code=postal_code,
    )


@router.get("/c/{slug}/join")
def council_join_form(
    slug: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user_optional),
):
    """위원 초대 코드로 가입하는 화면.

    후원자 가입(/c/<slug>/signup)과 다른 주소를 쓴다. 한 화면에 두면 "나는 위원인가
    후원자인가" 가 아니라 "어느 칸을 채워야 하나" 를 고르게 되고, 잘못 고른 가입은
    되돌리기 번거롭다 — 위원으로 들어온 계정은 승인 대기에 걸려 관리자 손이 간다.
    """
    from app import tenancy

    if user is not None:
        return RedirectResponse("/", status_code=303)
    council = tenancy.by_slug(db, slug)
    return _page(
        request,
        db,
        "auth/join.html",
        council=council,
        dong=council.dong,
        action=f"/c/{council.slug}/join",
        locked=council.join_is_locked,
        wait_label=council.join_wait_label,
    )


@router.post("/c/{slug}/join")
def council_join(
    slug: str,
    request: Request,
    code: str = Form(""),
    name: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
    confirm: str = Form(""),
    db: Session = Depends(get_db),
):
    from app import accounts, invites, tenancy

    council = tenancy.by_slug(db, slug)
    back = f"/c/{council.slug}/join"
    try:
        member = invites.redeem(
            db, council, code=code, name=name, email=email,
            password=password, confirm=confirm,
        )
    except (invites.InviteError, accounts.AccountError) as exc:
        request.session["flash"] = str(exc)
        return RedirectResponse(back, status_code=303)

    request.session["flash"] = (
        f"{member.name}님, 가입 신청이 접수되었습니다. 관리자 승인 후 이용하실 수 있습니다."
    )
    return _start_session(request, member)


@router.get("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    """로그아웃은 이 기기 기억도 함께 끊는다.

    끊지 않으면 로그아웃하고도 로그인 화면에서 그대로 다시 들어가, 나간 것처럼 보이지 않는다.
    """
    devices.forget(db, request.cookies.get(devices.COOKIE_NAME))
    request.session.clear()
    response = RedirectResponse("/login", status_code=303)
    devices.clear_cookie(response)
    return response
