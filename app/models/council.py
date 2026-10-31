from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, text, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User

# 파일럿의 첫 협의체. 1차 구현은 선부3동 하나만 전제했고, 그 데이터를 이 협의체로 옮긴다.
DEFAULT_SLUG = "sunbu3"

# 초대 코드를 틀렸을 때의 대기 시간. 누적 실패가 쌓이면 늘어나지만, 영구히 잠기지는 않는다.
#
# 계정 잠금(안건 15)은 시간이 지나도 풀리지 않는다. 그 결정이 옳은 이유는 계정의 아이디가
# 전화번호여서다 — 추측할 수 있는 아이디를 시간으로 풀어 주면 공격자는 기다리기만 하면 된다.
#
# 초대 코드는 사정이 다르다. 31글자 8자리면 8,500억 가지이고 그중 쓸 수 있는 코드는 몇 개뿐
# 이라, 속도만 묶어도 추측이 성립하지 않는다. 그래서 영구 잠금을 쓰지 않는다.
#
# 영구 잠금으로 두었을 때의 대가가 컸다. 지나가는 사람이 아무 코드나 다섯 번 넣으면, 그 동의
# 위원 모집이 관리자가 손을 쓸 때까지 멈췄다. 위원 가입은 1년에 몇 번 있는 일이라 한 시간쯤
# 늦는 것은 거의 피해가 없지만, 아무도 모르는 사이에 멈춰 있는 것은 피해다.
JOIN_BACKOFF: tuple[tuple[int, timedelta], ...] = (
    (5, timedelta(minutes=1)),
    (10, timedelta(minutes=5)),
    (20, timedelta(minutes=30)),
    (40, timedelta(hours=1)),   # 상한. 더 쌓여도 이 이상 기다리게 하지 않는다.
)

# 조용히 지나가면 실패 기록을 잊는다. 남의 오타 네 번이 반년 뒤의 가입을 늦추지 않게.
JOIN_DECAY = timedelta(hours=24)


def join_wait(attempts: int) -> timedelta | None:
    """누적 실패 횟수에 걸리는 대기 시간. 아직 걸리는 단계가 아니면 None."""
    wait = None
    for threshold, window in JOIN_BACKOFF:
        if attempts >= threshold:
            wait = window
    return wait


def _aware(value: datetime | None) -> datetime | None:
    """SQLite 는 시간대를 떼고 돌려준다. 비교 전에 UTC 로 붙여 준다."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class Council(Base, TimestampMixin):
    """동 지역사회보장협의체 — 테넌트 경계.

    안산시의 여러 동이, 나아가 다른 시의 협의체가 같은 시스템 위에서 각자 독립적으로
    활동한다. 선부3동의 나눔글이 선부2동 위원에게 보이지 않고, 지표와 월간보고서도
    동 단위로 집계된다. 식별정보는 말할 것도 없다.

    경계를 '조회할 때 조건을 꼭 넣자'는 약속으로 두지 않는다 — 언젠가 깨진다.
    app/tenancy.py 의 한 통로를 거치게 하고, 빠뜨리면 테스트가 깨지게 고정한다.

    행정구역 기준 데이터는 적재하지 않는다 (2026-10-24 결정: "일단 사용할 동만 수집입력").
    전국 226개 시·군·구를 미리 넣는 대신 쓰는 동만 등록한다. region 을 코드가 아니라
    이름으로 두는 것도 그래서다 — 나중에 행안부 코드로 바꿀 자리는 region_code 다.
    """

    __tablename__ = "council"

    id: Mapped[int] = mapped_column(primary_key=True)

    # 후원자에게 전달하는 전용 주소의 조각. 한 번 배포되면 바꾸기 어려우므로
    # 관리자가 임의로 정하게 두지 않고 슈퍼 관리자가 승인한다.
    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True)

    region: Mapped[str] = mapped_column(String(60))   # 시·군·구 이름 — 예: "안산시 단원구"
    dong: Mapped[str] = mapped_column(String(40))     # 동 이름 — 예: "선부3동"
    # 행안부 행정구역 코드. 지금은 비어 있고, 기준 데이터를 적재할 때 채운다.
    region_code: Mapped[str | None] = mapped_column(String(20), default=None)

    # 실재하지 않는 협의체·사칭 개설을 막는다. 승인 전에는 아무도 쓸 수 없다.
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

    # 초대 코드를 틀린 횟수와 마지막으로 틀린 시각. 둘을 합쳐 '언제까지 기다려야 하는가'
    # 를 계산한다 (JOIN_BACKOFF). 잠긴 시각이 아니라 마지막 실패 시각인 것이 중요하다 —
    # 실패가 또 들어오면 대기가 그 시점부터 다시 시작되고, 한동안 조용하면 기록이
    # 잊힌다 (JOIN_DECAY).
    join_failed_attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    join_last_failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    approved_by: Mapped["User | None"] = relationship(foreign_keys=[approved_by_id])
    members: Mapped[list["User"]] = relationship(
        back_populates="council", foreign_keys="User.council_id"
    )

    @property
    def label(self) -> str:
        return f"{self.region} {self.dong}"

    @property
    def is_approved(self) -> bool:
        return self.approved_at is not None

    @property
    def join_failures_are_stale(self) -> bool:
        """마지막 실패가 오래돼 기록을 잊을 때가 됐는가."""
        last = _aware(self.join_last_failed_at)
        return last is None or (datetime.now(timezone.utc) - last) > JOIN_DECAY

    @property
    def join_locked_until(self) -> datetime | None:
        """가입을 다시 시도할 수 있는 시각. 기다릴 필요가 없으면 None."""
        last = _aware(self.join_last_failed_at)
        if last is None:
            return None
        wait = join_wait(self.join_failed_attempts or 0)
        return None if wait is None else last + wait

    @property
    def join_is_locked(self) -> bool:
        until = self.join_locked_until
        return until is not None and until > datetime.now(timezone.utc)

    @property
    def join_seconds_left(self) -> int:
        """남은 대기 시간(초). 잠겨 있지 않으면 0."""
        until = self.join_locked_until
        if until is None:
            return 0
        left = (until - datetime.now(timezone.utc)).total_seconds()
        return max(0, int(left + 0.999))   # 0.4초 남았을 때 '0초' 라고 하지 않는다

    @property
    def join_wait_label(self) -> str:
        """사람에게 보여 줄 남은 시간. "3분" 처럼 읽히게 올림한다."""
        seconds = self.join_seconds_left
        if seconds <= 0:
            return ""
        if seconds < 60:
            return f"{seconds}초"
        minutes = -(-seconds // 60)
        if minutes < 60:
            return f"{minutes}분"
        return f"{-(-minutes // 60)}시간"

    def __repr__(self) -> str:
        return f"<Council {self.slug} {self.label}>"
