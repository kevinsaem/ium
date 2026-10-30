"""권한 표.

여기 한 곳에 모아 두는 이유: 위원회와 행정복지센터에 "누가 무엇을 볼 수 있나" 를 설명할 때
코드를 뒤지지 않고 이 표 하나만 보여 주면 되게 하기 위해서다.

표의 기준을 역할에서 **행위자**로 바꿨다. 운영자 역할을 폐기하면서 그 일들이 관리자에게
왔는데, 관리자는 역할이 아니라 위원에게 주는 권한이다 (안건 14). 역할 기준 표로는
'관리자' 칸을 만들 수 없고, 억지로 역할을 하나 더 만들면 설명할 것이 늘어난다.

또 역할 기준 표로는 가장 중요한 선을 적을 수 없었다 — 식별정보를 읽는 사람은 '위원' 이
아니라 '그 가정의 담당 위원' 이다. 그 조건은 코드(app/identity_service.py)에 있었고 표에는
'위원' 으로만 적혀 있어, 표가 실제보다 넓게 보였다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.base import Role

if TYPE_CHECKING:
    from app.models.user import User

# 표에 등장하는 행위자. 역할 셋(후원자·위원·슈퍼)에 두 가지 조건부 자리가 더해진다.
DONOR = "donor"
MEMBER = "member"              # 위원 누구나
CASE_MEMBER = "case_member"    # 그 케이스의 담당 위원만
MANAGER = "manager"            # 관리자 권한이 있는 위원 (협의체당 한 사람)
SUPER = "super"                # 슈퍼 관리자 — 협의체 경계를 넘지만 안을 못 본다

ACTOR_LABELS = {
    DONOR: "후원자",
    MEMBER: "위원",
    CASE_MEMBER: "담당 위원",
    MANAGER: "관리자",
    SUPER: "슈퍼 관리자",
}

# 리소스별 (읽기 허용 행위자, 쓰기 허용 행위자)
MATRIX: dict[str, dict[str, tuple[str, ...]]] = {
    "offer":          {"read": (DONOR, MEMBER),       "write": (DONOR,)},
    "shop":           {"read": (DONOR, MEMBER),       "write": (DONOR,)},
    # 가게 인증 배지는 '관공서 신뢰 보증'의 실체다. 그래서 위원 누구나가 아니라 관리자가 준다.
    "shop_cert":      {"read": (DONOR, MEMBER),       "write": (MANAGER,)},
    "case":           {"read": (MEMBER,),             "write": (MEMBER,)},
    # 담당 배정은 '누가 그 가정을 맡는가' 라는 운영 결정이라 관리자 몫이다.
    # 배정을 바꿔도 관리자가 케이스 내용이나 식별정보를 읽게 되는 것은 아니다.
    "case_assignment": {"read": (MEMBER,),            "write": (MANAGER,)},
    # 🔴 이 한 줄이 이 앱의 중심이다. 관리자도, 슈퍼 관리자도 읽지 못한다.
    "case_identity":  {"read": (CASE_MEMBER,),        "write": (CASE_MEMBER,)},
    # 보관 기한이 지난 식별정보를 지우는 권한. 읽기가 아니다 — 관리자는 내용을 열지 않고
    # 파기만 집행하고, 누가 언제 했는지 기록에 남는다 (안건 01, 2026-10-24 결정).
    "identity_retention": {"read": (MANAGER,),        "write": (MANAGER,)},
    "match":          {"read": (MEMBER,),             "write": (MEMBER,)},
    # 위원 계정을 들이고 거두는 일. 초대 코드 발급·승인·거절·위촉 해제가 여기 들어간다.
    "user_admin":     {"read": (MANAGER,),            "write": (MANAGER,)},
    # 비밀번호 초기화는 그 계정으로 들어갈 수 있게 만드는 일이라, account_log 에 누가·
    # 언제·누구의 비밀번호를 건드렸는지 남는다.
    "account":        {"read": (MANAGER,),            "write": (MANAGER,)},
    "account_log":    {"read": (MANAGER,),            "write": ()},
    "audit_log":      {"read": (MANAGER,),            "write": ()},
    "donor_approval": {"read": (MEMBER,),             "write": (MANAGER,)},
    "account_unlock": {"read": (MANAGER,),            "write": (MANAGER,)},
    "team_contact":   {"read": (DONOR, MEMBER),       "write": (MANAGER,)},
    # 협의체 개설·승인·전용 주소. 협의체 경계를 넘는 유일한 권한이다 (2026-10-24 결정).
    "council":        {"read": (SUPER,),              "write": (SUPER,)},
}

# 🔴 슈퍼 관리자가 협의체 안을 들여다보지 못한다는 것이 이 표의 핵심이다.
#
# 시스템 전체를 관리하는 사람이 당연히 다 볼 수 있다고 생각하기 쉬운데, 이음에서는 아니다.
# 협의체를 늘리는 권한과 그 안을 들여다보는 권한은 다른 권한이다.
_SUPER_NEVER = (
    "case", "case_identity", "match", "offer", "shop",
    "account_log", "audit_log", "donor_approval",
)
assert all(
    SUPER not in MATRIX[r]["read"] and SUPER not in MATRIX[r]["write"] for r in _SUPER_NEVER
), "슈퍼 관리자에게 협의체 내부 자료를 주면 안 됩니다."

# 🔴 식별정보를 읽는 자리는 담당 위원 하나뿐이다.
assert MATRIX["case_identity"]["read"] == (CASE_MEMBER,), (
    "식별정보 열람은 담당 위원만입니다. 넓히려면 위원회 결정과 사전 승인이 필요합니다."
)

# 관리자만 하는 일. 화면에서 버튼을 가릴 때 쓴다.
MANAGER_RESOURCES = {
    resource: resource
    for resource, actions in MATRIX.items()
    if MANAGER in actions.get("write", ()) or MANAGER in actions.get("read", ())
}


def is_manager(user: "User") -> bool:
    """관리자는 위촉 중인 위원이어야 한다. 해제된 위원의 권한은 함께 멈춘다."""
    return user.role is Role.MEMBER and bool(user.is_manager) and bool(user.is_active)


def actors_of(user: "User") -> tuple[str, ...]:
    """이 사람이 표에서 어느 줄에 해당하는가.

    한 사람이 여러 자리를 겸한다. 관리자는 위원이기도 하고, 담당 위원은 위원이기도 하다.
    CASE_MEMBER 는 케이스가 정해져야 알 수 있으므로 여기서 주지 않는다 —
    app/identity_service.py 가 case.member_id 를 보고 따로 확인한다.
    """
    if user.role is Role.SUPER:
        return (SUPER,)
    if user.role is Role.DONOR:
        return (DONOR,)
    if user.role is Role.MEMBER:
        return (MEMBER, MANAGER) if is_manager(user) else (MEMBER,)
    # 역할이 셋뿐이라 여기 닿을 수 없다. 역할을 늘리면 여기서 걸려 — 새 역할이 아무
    # 권한도 없는 상태로 조용히 지나가지 않는다.
    raise AssertionError(f"권한 표에 없는 역할입니다: {user.role}")


def can(user_or_actor, resource: str, action: str = "read") -> bool:
    """표를 그대로 묻는다. 사람을 넘겨도 되고 행위자 이름을 넘겨도 된다."""
    entry = MATRIX.get(resource)
    if not entry:
        return False
    allowed = entry.get(action, ())
    if isinstance(user_or_actor, str):
        return user_or_actor in allowed
    return any(a in allowed for a in actors_of(user_or_actor))


def manager_can(user: "User", resource: str) -> bool:
    return resource in MANAGER_RESOURCES and is_manager(user)


def describe() -> list[dict[str, str]]:
    """화면에 그대로 렌더링하는, 사람이 읽는 표."""
    return [
        {
            "resource": resource,
            "read": ", ".join(ACTOR_LABELS[a] for a in actions.get("read", ())) or "—",
            "write": ", ".join(ACTOR_LABELS[a] for a in actions.get("write", ())) or "—",
        }
        for resource, actions in MATRIX.items()
    ]
