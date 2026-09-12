from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.db import is_migrated
from app.routers import auth, donor, member, office


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # 스키마는 Alembic 이 관리한다. 여기서 조용히 테이블을 만들면 마이그레이션과
    # 실제 DB가 어긋나도 아무도 모르게 되므로, 만들지 않고 알린다.
    if not is_migrated():
        raise RuntimeError(
            "DB 마이그레이션이 적용되지 않았습니다. 먼저 실행하세요:\n"
            "  .venv/Scripts/python -m alembic upgrade head   (또는 python seed.py)"
        )
    yield


app = FastAPI(title="이음 · 지역사회보장협의체 나눔 매칭", docs_url="/api/docs", lifespan=lifespan)
# 운영에서는 HTTPS 로만 쿠키를 보낸다. 개발(http://127.0.0.1)에서 켜면 로그인이 안 되므로 모드로 가른다.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    same_site="lax",
    https_only=settings.is_production,
)
app.mount(
    "/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static"
)

app.include_router(auth.router)
app.include_router(donor.router)
app.include_router(member.router)
app.include_router(office.router)


def _back_to(request: Request) -> str:
    """돌아갈 화면 — 같은 사이트의 직전 화면, 없으면 역할별 홈("/" 이 알아서 보낸다).

    같은 호스트인지 확인하고 경로만 떼어 쓴다. Referer 를 그대로 믿으면 외부 사이트로
    튕겨내는 통로가 된다.
    """
    referer = request.headers.get("referer")
    if referer:
        parts = urlsplit(referer)
        if not parts.netloc or parts.netloc == request.url.netloc:
            return urlunsplit(("", "", parts.path or "/", parts.query, ""))
    return "/"


@app.exception_handler(HTTPException)
def http_exception_handler(request: Request, exc: HTTPException):
    """이 앱은 JSON API 가 아니라 화면이다. 오류도 화면으로 돌려준다.

    로그인이 필요하면 로그인 화면으로, 그 밖의 4xx 는 안내 문구를 남기고 직전 화면으로
    되돌린다. 예외를 다시 던지면 사용자에게 남는 건 detail 문구가 아니라 500 페이지다.
    """
    if exc.status_code == 401:
        return RedirectResponse("/login", status_code=303)
    if exc.status_code < 500:
        request.session["flash"] = exc.detail
        # 403 은 직전 화면 자체가 막힌 화면일 수 있으므로 홈으로 되돌린다.
        target = "/" if exc.status_code == 403 else _back_to(request)
        return RedirectResponse(target, status_code=303)
    raise exc
