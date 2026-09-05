"""템플릿 렌더링 공통 설정 — 역할별 하단 탭 정의 포함."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.icons import icon
from app.models import Role, User

TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
templates.env.globals["icon"] = icon
templates.env.globals["settings"] = settings

TABS: dict[Role, list[dict[str, str]]] = {
    Role.DONOR: [
        {"key": "feed", "href": "/donor", "icon": "heart", "label": "나눔"},
        {"key": "post", "href": "/donor/post", "icon": "pen", "label": "나눔하기"},
        {"key": "mine", "href": "/donor/mine", "icon": "doc", "label": "내활동"},
    ],
    Role.MEMBER: [
        {"key": "cases", "href": "/member", "icon": "compass", "label": "케이스"},
        {"key": "match", "href": "/member/matches", "icon": "link", "label": "매칭"},
        {"key": "report", "href": "/member/report", "icon": "chart", "label": "활동기록"},
    ],
    Role.OFFICE: [
        {"key": "dash", "href": "/office", "icon": "building", "label": "현황"},
        {"key": "members", "href": "/office/members", "icon": "users", "label": "위원"},
        {"key": "badges", "href": "/office/badges", "icon": "award", "label": "인증"},
    ],
}

HOME: dict[Role, str] = {Role.DONOR: "/donor", Role.MEMBER: "/member", Role.OFFICE: "/office"}


def render(
    request: Request, template: str, user: User, active_tab: str, **ctx: Any
):
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(
        request,
        template,
        {
            "user": user,
            "tabs": TABS[user.role],
            "active_tab": active_tab,
            "flash": flash,
            **ctx,
        },
    )


def flash(request: Request, message: str) -> None:
    request.session["flash"] = message
