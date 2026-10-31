"""위원 초대 코드 — 발급, 사용, 무효화.

위원 계정이 생기는 두 길 중 하나다 (다른 하나는 관리자가 대신 등록하는 길,
app/accounts.py 의 issue_member).

코드로 들어온 계정은 승인 대기 상태로 선다. 코드에 유효기간·사용 횟수 한도·무효화를
붙여 새는 범위를 줄이고, 승인 대기로 새어도 막는다. 왜 그렇게까지 하는지는
app/models/invite.py 의 MemberInvite 설명에 적어 두었다.

코드를 틀린 횟수는 협의체에 쌓이고, 쌓일수록 다음 시도까지 기다려야 하는 시간이 늘어난다
(app/models/council.py 의 JOIN_BACKOFF). 영구히 잠기지는 않는다 — 그 이유와, 계정 잠금
(안건 15)과 다르게 둔 이유를 그 표 위에 적어 두었다.

관리자는 기다리지 않고 바로 풀 수 있다. 안건 15 가 정한 '관리자가 푼다' 는 그대로 남아
있고, 달라진 것은 '관리자가 풀어 주지 않으면 아무도 못 들어온다' 가 아니게 된 것이다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import permissions
from app.models import Council, MemberInvite, Role, User
from app.models.council import JOIN_BACKOFF
from app.models.invite import (
    DEFAULT_DAYS,
    DEFAULT_MAX_USES,
    MAX_DAYS,
    MAX_USES_LIMIT,
    generate_code,
)

# 처음 대기가 걸리는 횟수. 계정 잠금과 같은 숫자를 쓴다 — 다르게 두면 "다섯 번 틀리면" 이
# 자리마다 다른 뜻이 된다. 이 뒤로는 JOIN_BACKOFF 의 단계를 따라 대기가 늘어난다.
MAX_FAILED_CODES = JOIN_BACKOFF[0][0]


class InviteError(ValueError):
    """사람에게 그대로 보여 줄 수 있는 문장을 담는다."""


def _parse_int(raw, field: str, default: int, limit: int) -> int:
    text = str(raw or "").strip()
    if not text:
        return default
    try:
        value = int(text)
    except ValueError:
        raise InviteError(f"{field}는 숫자로 입력해 주세요.") from None
    if not 1 <= value <= limit:
        raise InviteError(f"{field}는 1에서 {limit} 사이로 정해 주세요.")
    return value


def normalize(raw: str | None) -> str:
    """사람이 받아 적은 코드를 맞춰 준다.

    소문자로 적거나 하이픈·공백을 넣어 보내는 일이 흔하다. 코드를 틀렸다고 돌려보내면
    본인은 맞게 적었다고 생각하므로, 모양만 다른 입력은 같은 코드로 읽는다.
    """
    return "".join(ch for ch in (raw or "").upper() if ch.isalnum())


def create(
    db: Session,
    manager: User,
    *,
    days: str | int = DEFAULT_DAYS,
    max_uses: str | int = DEFAULT_MAX_USES,
    note: str = "",
) -> MemberInvite:
    """초대 코드를 발급한다 — 매니저만."""
    if not permissions.is_manager(manager):
        raise InviteError("위원 초대 코드는 매니저 권한이 있는 위원만 발급할 수 있습니다.")
    if manager.council_id is None:
        raise InviteError("소속 협의체가 없는 계정입니다.")

    day_count = _parse_int(days, "유효기간", DEFAULT_DAYS, MAX_DAYS)
    use_count = _parse_int(max_uses, "사용 횟수", DEFAULT_MAX_USES, MAX_USES_LIMIT)

    invite = MemberInvite(
        council_id=manager.council_id,
        code=generate_code(),
        created_by_id=manager.id,
        expires_at=MemberInvite.deadline(day_count),
        max_uses=use_count,
        note=(note or "").strip() or None,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite


def revoke(db: Session, manager: User, invite: MemberInvite) -> MemberInvite:
    """코드를 거둔다. 지우지 않고 표시한다 — 누가 그 코드로 들어왔는지 설명해야 한다."""
    if not permissions.is_manager(manager):
        raise InviteError("코드 무효화는 매니저 권한이 있는 위원만 할 수 있습니다.")
    if invite.is_revoked:
        raise InviteError("이미 무효화된 코드입니다.")

    invite.revoked_at = datetime.now(timezone.utc)
    invite.revoked_by_id = manager.id
    db.commit()
    db.refresh(invite)
    return invite


def listing(db: Session, council_id: int) -> list[MemberInvite]:
    """쓸 수 있는 코드가 위로. 아래는 왜 못 쓰는지 보이는 기록이다."""
    rows = list(
        db.scalars(
            select(MemberInvite)
            .where(MemberInvite.council_id == council_id)
            .order_by(MemberInvite.created_at.desc())
        ).all()
    )
    return sorted(rows, key=lambda i: (not i.is_usable, -i.id))


def _record_failure(db: Session, council: Council) -> int:
    """틀린 횟수를 쌓고, 아직 대기가 걸리지 않았다면 남은 횟수를 돌려준다.

    0 이면 방금 대기가 걸렸다 (council.join_wait_label 에 남은 시간이 있다).

    한동안 조용했으면 먼저 기록을 잊는다. 그러지 않으면 작년에 누군가 네 번 틀린 협의체는
    이번에 한 번만 틀려도 바로 대기에 걸린다.
    """
    if council.join_failures_are_stale:
        council.join_failed_attempts = 0

    council.join_failed_attempts = (council.join_failed_attempts or 0) + 1
    council.join_last_failed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(council)

    left = MAX_FAILED_CODES - council.join_failed_attempts
    return max(0, left)


def unlock_join(db: Session, manager: User, council: Council) -> Council:
    """대기를 즉시 풀어 준다 — 관리자만.

    대기는 시간이 지나면 저절로 풀린다. 그래도 이 버튼을 남겨 두는 이유는, 위원이 지금
    가입하려고 기다리고 있을 때 관리자가 "조금만 기다려 주세요" 말고 할 수 있는 일이
    있어야 하기 때문이다.
    """
    if not permissions.is_manager(manager):
        raise InviteError("가입 대기 해제는 매니저 권한이 있는 위원만 할 수 있습니다.")
    council.join_failed_attempts = 0
    council.join_last_failed_at = None
    db.commit()
    db.refresh(council)
    return council


def find(db: Session, council: Council, raw_code: str) -> MemberInvite | None:
    code = normalize(raw_code)
    if not code:
        return None
    return db.scalar(
        select(MemberInvite).where(
            MemberInvite.code == code, MemberInvite.council_id == council.id
        )
    )


def redeem(
    db: Session,
    council: Council,
    *,
    code: str,
    name: str,
    email: str,
    password: str,
    confirm: str,
) -> User:
    """코드로 위원 계정을 만든다 — 승인 대기 상태로.

    비밀번호를 본인이 정한다. 임시 비밀번호를 만들어 전달하는 길을 또 두지 않으려는
    것이다. 코드로 가입하는 사람은 지금 화면 앞에 있고, 임시 비밀번호는 전달하는
    순간이 늘 약한 고리다.

    계정이 서도 바로 쓰지 못한다. 관리자가 승인해야 열린다.
    """
    from app import accounts

    if council.join_is_locked:
        raise InviteError(
            f"초대 코드를 여러 번 잘못 입력했습니다. {council.join_wait_label} 뒤에 "
            "다시 시도해 주세요. 급하시면 협의체 관리자에게 문의해 주세요."
        )

    invite = find(db, council, code)
    if invite is None:
        left = _record_failure(db, council)
        if left == 0:
            raise InviteError(
                f"초대 코드를 여러 번 잘못 입력했습니다. {council.join_wait_label} 뒤에 "
                "다시 시도해 주세요. 급하시면 협의체 관리자에게 문의해 주세요."
            )
        raise InviteError(f"초대 코드가 올바르지 않습니다. ({left}번 남음)")

    # 코드 자체는 맞았다. 쓸 수 없는 이유는 그대로 알려 준다 — 틀린 코드와 달리 이쪽은
    # 추측으로 알아낸 정보가 아니고, 본인은 "왜 안 되는지" 를 알아야 관리자에게 말할 수 있다.
    if invite.is_revoked:
        raise InviteError("무효화된 초대 코드입니다. 협의체 관리자에게 새 코드를 받아 주세요.")
    if invite.is_expired:
        raise InviteError("초대 코드의 유효기간이 지났습니다. 관리자에게 새 코드를 받아 주세요.")
    if invite.is_used_up:
        raise InviteError("이미 사용 횟수를 모두 쓴 초대 코드입니다.")

    if password != confirm:
        raise InviteError("비밀번호 두 칸이 서로 다릅니다.")

    member = accounts.create_pending_member(
        db,
        council_id=council.id,
        name=name,
        email=email,
        password=password,
        note=f"초대 코드 {invite.code}",
    )

    invite.used_count += 1
    # 제대로 들어온 가입이 있으면 틀린 횟수를 지운다. 남의 오타가 쌓여 뒤에 오는 분의
    # 가입이 늦어지는 일을 줄인다.
    council.join_failed_attempts = 0
    council.join_last_failed_at = None
    db.commit()
    db.refresh(member)
    return member


def pending_members(db: Session, council_id: int) -> list[User]:
    """승인 대기 위원 — 관리자 화면에 띄운다."""
    return list(
        db.scalars(
            select(User)
            .where(
                User.council_id == council_id,
                User.role == Role.MEMBER,
                User.approved_at.is_(None),
                User.is_active.is_(True),
            )
            .order_by(User.created_at)
        ).all()
    )
