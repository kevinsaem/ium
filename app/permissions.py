"""권한 매트릭스.

여기 한 곳에 모아 두는 이유: 위원회에 "누가 무엇을 볼 수 있나"를 설명할 때
코드를 뒤지지 않고 이 표 하나만 보여주면 되게 하기 위해서다.
"""
from __future__ import annotations

from app.models.base import Role

# 리소스별 (읽기 허용 역할, 쓰기 허용 역할)
MATRIX: dict[str, dict[str, tuple[Role, ...]]] = {
    "offer":          {"read": (Role.DONOR, Role.MEMBER, Role.OFFICE), "write": (Role.DONOR,)},
    "shop":           {"read": (Role.DONOR, Role.MEMBER, Role.OFFICE), "write": (Role.DONOR,)},
    "shop_cert":      {"read": (Role.DONOR, Role.MEMBER, Role.OFFICE), "write": (Role.OFFICE,)},
    "case":           {"read": (Role.MEMBER, Role.OFFICE),             "write": (Role.MEMBER,)},
    # 담당 배정은 '누가 그 가정을 맡는가'라는 행정 결정이라 운영자 몫이다.
    # 배정을 바꿔도 운영자가 케이스 내용이나 식별정보를 읽게 되는 것은 아니다.
    "case_assignment": {"read": (Role.MEMBER, Role.OFFICE),            "write": (Role.OFFICE,)},
    # 🔴 식별정보는 위원만. 운영자도 읽을 수 없다.
    "case_identity":  {"read": (Role.MEMBER,),                          "write": (Role.MEMBER,)},
    "match":          {"read": (Role.MEMBER, Role.OFFICE),             "write": (Role.MEMBER,)},
    "match_approval": {"read": (Role.MEMBER, Role.OFFICE),             "write": (Role.MEMBER,)},
    "credit":         {"read": (Role.DONOR, Role.OFFICE),              "write": (Role.OFFICE,)},
    "user_admin":     {"read": (Role.OFFICE,),                          "write": (Role.OFFICE,)},
    "audit_log":      {"read": (Role.OFFICE,),                          "write": ()},
}


def can(role: Role, resource: str, action: str = "read") -> bool:
    entry = MATRIX.get(resource)
    if not entry:
        return False
    return role in entry.get(action, ())


def describe() -> list[dict[str, str]]:
    """운영자 화면에 그대로 렌더링하는 사람이 읽는 표."""
    rows = []
    for resource, actions in MATRIX.items():
        rows.append(
            {
                "resource": resource,
                "read": ", ".join(r.tag for r in actions.get("read", ())) or "—",
                "write": ", ".join(r.tag for r in actions.get("write", ())) or "—",
            }
        )
    return rows
