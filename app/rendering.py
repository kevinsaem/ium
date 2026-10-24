"""템플릿 렌더링 공통 설정 — 역할별 하단 탭 정의 포함."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.icons import icon
from app.models import Role, User
from app.permissions import is_manager
from app.timeutil import to_local

TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
templates.env.globals["icon"] = icon
templates.env.globals["settings"] = settings
# 저장은 UTC, 화면은 한국 시간. 템플릿에서 strftime 을 직접 부르지 말고 이 필터를 쓴다.
templates.env.filters["local"] = (
    lambda dt, fmt="%Y-%m-%d %H:%M": to_local(dt).strftime(fmt) if dt else ""
)

TABS: dict[Role, list[dict[str, str]]] = {
    Role.DONOR: [
        {"key": "feed", "href": "/donor", "icon": "heart", "label": "나눔"},
        {"key": "post", "href": "/donor/post", "icon": "pen", "label": "나눔하기"},
        {"key": "mine", "href": "/donor/mine", "icon": "doc", "label": "내활동"},
    ],
    Role.MEMBER: [
        {"key": "cases", "href": "/member", "icon": "compass", "label": "케이스"},
        {"key": "match", "href": "/member/matches", "icon": "link", "label": "매칭"},
        {"key": "donors", "href": "/member/donors", "icon": "store", "label": "후원자"},
        {"key": "report", "href": "/member/report", "icon": "chart", "label": "활동기록"},
    ],
    Role.OFFICE: [
        {"key": "dash", "href": "/office", "icon": "building", "label": "현황"},
        {"key": "members", "href": "/office/members", "icon": "users", "label": "위원"},
        {"key": "badges", "href": "/office/badges", "icon": "award", "label": "인증"},
        {"key": "records", "href": "/office/report", "icon": "doc", "label": "기록"},
    ],
    # 슈퍼 관리자의 탭이 하나인 것은 할 일이 하나뿐이기 때문이다 — 협의체를 만들고
    # 열어 주는 것. 탭을 늘리고 싶어질 때마다 그게 협의체 안을 들여다보는 화면이
    # 아닌지 먼저 물을 것.
    Role.SUPER: [
        {"key": "councils", "href": "/super", "icon": "compass", "label": "협의체"},
    ],
}

# 매니저 전용 탭. 매니저는 위원 중 한 명이라(안건 14) 위원 탭 뒤에 붙인다.
MANAGER_TAB = {"key": "manage", "href": "/member/manage", "icon": "shield", "label": "매니저"}


def tabs_for(user: User) -> list[dict[str, str]]:
    tabs = list(TABS[user.role])
    if is_manager(user):
        tabs.append(MANAGER_TAB)
    return tabs


HOME: dict[Role, str] = {
    Role.DONOR: "/donor",
    Role.MEMBER: "/member",
    Role.OFFICE: "/office",
    Role.SUPER: "/super",
}


def dong_of(user: "User | None") -> str:
    """화면에 띄울 동 이름.

    협의체가 여러 개가 되면서 "선부3동" 은 설정값이 아니라 그 사람이 속한 협의체의
    속성이 됐다. settings.dong 으로 남겨 두면 선부2동 위원 화면에 선부3동이 적힌다.

    로그인하지 않은 화면(로그인·가입)은 아직 협의체를 알 수 없어 설정값으로 떨어진다.
    협의체별 전용 주소(/c/<slug>/)가 붙으면 그 주소에서 읽는다.
    """
    council = getattr(user, "council", None)
    return council.dong if council is not None else settings.dong


def render(
    request: Request, template: str, user: User, active_tab: str, **ctx: Any
):
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(
        request,
        template,
        {
            "user": user,
            "council": getattr(user, "council", None),
            "dong": dong_of(user),
            "tabs": tabs_for(user),
            "active_tab": active_tab,
            "flash": flash,
            **ctx,
        },
    )


def flash(request: Request, message: str) -> None:
    request.session["flash"] = message
