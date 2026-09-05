"""폼 입력 파싱.

브라우저가 보낸 값이라고 믿지 않는다. select/radio 값이 어긋나는 건 뒤로가기,
중복 제출, 오래 열어둔 탭에서 실제로 일어나고, 그때 사용자에게 500 을 보여줄 이유는 없다.
"""
from __future__ import annotations

import enum
from typing import TypeVar

from fastapi import HTTPException, status

E = TypeVar("E", bound=enum.Enum)


def parse_enum(enum_cls: type[E], raw: str, field_label: str) -> E:
    """폼 값을 Enum 으로 바꾼다. 목록에 없는 값이면 400."""
    try:
        return enum_cls(raw)
    except ValueError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"{field_label} 값이 올바르지 않습니다. 다시 선택해 주세요.",
        ) from None
