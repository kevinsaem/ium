"""폼 입력 파싱.

브라우저가 보낸 값이라고 믿지 않는다. select/radio 값이 어긋나는 건 뒤로가기,
중복 제출, 오래 열어둔 탭에서 실제로 일어나고, 그때 사용자에게 500 을 보여줄 이유는 없다.
"""
from __future__ import annotations

import enum
from typing import TypeVar

from fastapi import HTTPException, status

E = TypeVar("E", bound=enum.Enum)

# 입력 범위는 여기 한 곳에만 둔다. 화면의 min/max 도 이 값을 받아 그린다 —
# 두 곳에 적으면 한쪽만 고쳐져 브라우저는 통과시키고 서버가 막는 일이 생긴다.
WALK_MINUTES = (1, 60)
HOUSEHOLD_SIZE = (1, 20)


def parse_optional_int(
    raw: str, field_label: str, bounds: tuple[int, int]
) -> int | None:
    """빈 칸이면 None. 숫자가 아니거나 범위를 벗어나면 400.

    조용히 None 으로 넘기지 않는 이유: 위원은 '4명'이라고 적었다고 생각하는데 저장은 안 된다.
    빈 칸은 '모른다'는 뜻이라 그대로 두지만, 적은 값이 사라지는 것은 다른 일이다.
    """
    text = raw.strip()
    if not text:
        return None

    low, high = bounds
    try:
        value = int(text)
    except ValueError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"{field_label} 값은 숫자만 입력해 주세요. (예: {low})",
        ) from None
    if not low <= value <= high:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"{field_label} 값은 {low}에서 {high} 사이로 입력해 주세요.",
        )
    return value


def parse_enum(enum_cls: type[E], raw: str, field_label: str) -> E:
    """폼 값을 Enum 으로 바꾼다. 목록에 없는 값이면 400."""
    try:
        return enum_cls(raw)
    except ValueError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"{field_label} 값이 올바르지 않습니다. 다시 선택해 주세요.",
        ) from None
