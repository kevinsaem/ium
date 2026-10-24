"""권한 매트릭스.

여기 한 곳에 모아 두는 이유: 위원회에 "누가 무엇을 볼 수 있나"를 설명할 때
코드를 뒤지지 않고 이 표 하나만 보여주면 되게 하기 위해서다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.base import Role

if TYPE_CHECKING:
    from app.models.user import User

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
    # 보관 기한이 지난 식별정보를 지우는 권한. 읽기는 포함되지 않는다 —
    # 운영자는 내용을 보지 않고 파기만 집행한다 (위원회 결정, 안건 01).
    "identity_retention": {"read": (Role.OFFICE,),                      "write": (Role.OFFICE,)},
    "match":          {"read": (Role.MEMBER, Role.OFFICE),             "write": (Role.MEMBER,)},
    "user_admin":     {"read": (Role.OFFICE,),                          "write": (Role.OFFICE,)},
    # 계정 발급·비밀번호 초기화는 운영자 몫이다. 초기화하면 그 계정으로 들어갈 수 있으므로
    # account_log 에 누가·언제·누구의 비밀번호를 건드렸는지 남는다.
    "account":        {"read": (Role.OFFICE,),                          "write": (Role.OFFICE,)},
    "account_log":    {"read": (Role.OFFICE,),                          "write": ()},
    "audit_log":      {"read": (Role.OFFICE,),                          "write": ()},
    # 협의체 개설·승인·전용 주소. 협의체 경계를 넘는 유일한 권한이라 슈퍼 관리자만이다
    # (2026-10-24 결정). 운영자는 자기 협의체 안의 사람이므로 다른 동을 승인할 수 없다.
    "council":        {"read": (Role.SUPER,),                           "write": (Role.SUPER,)},
}

# 🔴 슈퍼 관리자가 식별정보에 없다는 것이 이 표의 핵심이다.
#
# 시스템 전체를 관리하는 사람이 당연히 다 볼 수 있다고 생각하기 쉬운데, 이음에서는 아니다.
# 식별정보를 읽는 사람은 그 가정을 직접 만나는 담당 위원뿐이고, 그 원칙은 협의체가 하나일
# 때나 백 개일 때나 같다. 협의체를 늘리는 권한과 그 안을 들여다보는 권한은 다른 권한이다.
_SUPER_NEVER = ("case", "case_identity", "match", "account_log", "audit_log")
assert all(Role.SUPER not in MATRIX[r]["read"] for r in _SUPER_NEVER), (
    "슈퍼 관리자에게 협의체 내부 자료 열람을 주면 안 됩니다."
)


# 매니저만 하는 일 (위원회 결정, 안건 10·14·15). 역할이 아니라 위원에게 주는 권한이라
# MATRIX 와 따로 둔다 — 같은 표에 섞으면 '위원'과 '매니저'가 한 칸에서 뒤섞인다.
MANAGER_RESOURCES = {
    "donor_approval": "후원자 승인",
    "account_unlock": "계정 잠금 해제",
    "team_contact": "운영팀 연락처 설정",
}


def is_manager(user: "User") -> bool:
    """매니저는 위촉 중인 위원이어야 한다. 해제된 위원의 권한은 함께 멈춘다."""
    return user.role is Role.MEMBER and bool(user.is_manager) and bool(user.is_active)


def manager_can(user: "User", resource: str) -> bool:
    return resource in MANAGER_RESOURCES and is_manager(user)


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
    for resource in MANAGER_RESOURCES:
        rows.append({"resource": resource, "read": "위원(매니저)", "write": "위원(매니저)"})
    return rows
