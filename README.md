# 이음(理音) — 선부3동 지역사회보장협의체 나눔 매칭

> 도움이 필요한 사람이 직접 나서지 않아도, 동네의 선의가 닿게 하는 앱

[kevinsaem/ium](https://github.com/kevinsaem/ium) 의 기획·프로토타입을 실제로 돌아가는
FastAPI 애플리케이션으로 구현한 것입니다. 화면 구조와 디자인 토큰은 프로토타입
(`자료실/ieum_prototype_mono.html`)을 그대로 계승했습니다.

## 빠르게 실행

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # macOS/Linux: .venv/bin/pip
cp .env.example .env                            # 그리고 아래 '키 생성' 참고
.venv/Scripts/python seed.py                    # 마이그레이션 + 개발용 데이터 생성
.venv/Scripts/python -m uvicorn app.main:app --reload
```

`.env` 의 `IUM_IDENTITY_KEY` 는 비워 두면 개발용 고정키가 쓰이고 경고가 뜹니다 (`IUM_ENV=production` 에서는 경고가 아니라 **시작 거부**). 새로 뽑으려면:

```bash
.venv/Scripts/python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
```

> ⚠️ 이 키를 바꾸면 **기존에 저장된 식별정보는 복호화할 수 없습니다.** 개발 중이라면
> `python seed.py --reset` 으로 다시 만드세요.

http://127.0.0.1:8000 — 비밀번호는 모두 `ium1234`

| 역할 | 계정 |
|---|---|
| 협의체 운영자 | `office@ium.test` |
| 협의체 위원 | `member1@ium.test` · `member2@ium.test` |
| 후원자 | `happy@ium.test` 외 4명 |

데이터를 갈아엎으려면 `python seed.py --reset`.

## 설계에서 가장 중요한 것: 식별정보 격리

기획문서의 리스크 1번(*"개인정보 설계는 초기 DB 단계부터 들어가야 한다. 나중에 붙이면
전부 재설계"*)을 스키마 레벨에서 강제한 구조입니다.

```
case                       ← 비식별. code("선부3동 A가정") · 필요 · 긴급여부만
  └─ case_identity         ← 🔴 실명·연락처·주소. Fernet 암호문으로만 저장
       └─ identity_access_log   ← 누가·언제·왜 열었는지 전부 기록
```

- **매칭·통계·월간보고서는 `case` 만으로 동작합니다.** 실명을 한 번도 건드리지 않습니다.
- 식별정보는 [app/identity_service.py](app/identity_service.py) 를 통해서만 읽고 씁니다.
  직접 쿼리하면 암호문만 나옵니다.
- 열람에는 **사유 입력이 필수**입니다. 사유 없는 로그는 로그가 아니기 때문입니다.
- **운영자도 식별정보를 볼 수 없습니다.** 운영자 대시보드에는 "누가 열람했다"는 사실만
  보이고 열람된 내용은 오지 않습니다.
- 담당이 아닌 위원도 볼 수 없습니다. 동네 전체 위원이 모든 가정을 열람하는 걸 막습니다.
- 케이스 종결 후 `purge_identity()` 로 식별정보만 파기하면, 비식별 케이스와 통계는
  그대로 남습니다.

권한 매트릭스는 [app/permissions.py](app/permissions.py) 한 곳에 모아 두었고, 운영자
현황 화면에 표로 렌더링됩니다. 위원회에 "누가 무엇을 볼 수 있나"를 설명할 때
코드를 뒤질 필요 없이 그 화면만 보여주면 됩니다.

## 위원회 미정 안건이 코드에 반영된 방식

프리젠테이션 슬라이드 6의 논의 안건 중 스키마·로직에 영향을 주는 두 개는 결정을
기다리지 않고 **설정으로 바꿀 수 있게** 만들어 두었습니다.

| 안건 | 반영 위치 |
|---|---|
| ⑤ 매칭 승인 프로세스 | `.env` 의 `IUM_MATCH_APPROVAL_MODE` — `member`(위원 단독) / `committee`(공동 결정, 기본 2인). 로직은 [app/matching.py](app/matching.py) 한 파일에만 있습니다 |
| ④ 파일럿 성공 지표 | [app/routers/office.py](app/routers/office.py) 의 `PILOT_GOALS` — 인증가게 10곳 · 매칭 20건 · 활동위원 8명 (초안값) |

어느 모드든 `match_approval` 테이블에 승인 기록이 남는 건 동일하므로, 결정이 바뀌어도
마이그레이션이 필요 없습니다.

## 알려진 제약 — 의도적으로 자동화하지 않은 것

- **기부금 영수증은 자동 발급하지 않습니다.** 법정기부금단체만 발급할 수 있고 협의체가
  발급 주체가 될 수 있는지 미확인입니다. 앱은 *신청 접수*까지만 하고 운영자가 수기로
  판단합니다. 요건이 확인되기 전까지 이 흐름을 자동화하지 마세요.
- **1365 자원봉사 연계는 API가 아니라 행정 절차입니다.** 실적 시간은 신청 시점의
  스냅샷일 뿐이고, 발급 근거는 운영자가 다시 확인합니다.

## 마이그레이션 (Alembic)

스키마는 Alembic 이 관리합니다. 앱은 시작할 때 `alembic_version` 테이블이 없으면
**테이블을 만들지 않고 기동을 거부합니다.** 조용히 `create_all` 을 하면 마이그레이션과
실제 DB가 어긋나도 아무도 모르게 되기 때문입니다.

```bash
.venv/Scripts/python -m alembic upgrade head                  # 최신 스키마 적용
.venv/Scripts/python -m alembic revision --autogenerate -m "설명"   # 모델 변경 후
.venv/Scripts/python -m alembic current                       # 현재 리비전 확인
.venv/Scripts/python -m alembic downgrade -1                  # 한 단계 되돌리기
```

`tests/test_migrations.py` 가 **모델과 마이그레이션의 drift 를 감지**합니다. 모델에
컬럼을 추가하고 리비전 생성을 깜빡하면 이 테스트가 먼저 깨집니다.

주의할 점 두 가지:

- **`alembic.ini` 는 ASCII 로만 유지하세요.** Alembic 이 이 파일을 `encoding="locale"`
  로 읽어서, 한국어 Windows(cp949)에서 UTF-8 주석이 있으면 파싱이 실패합니다.
  한글 설명은 `migrations/env.py` 에 적으세요.
- 초기 리비전은 SQLite 를 대상으로 autogenerate 되어 `server_default` 등 일부 표현이
  SQLite 색이 남아 있습니다. Postgres 전환 시 리비전을 한 번 검토하세요.

DB URL 은 `alembic.ini` 가 아니라 `migrations/env.py` 가 `app.config.settings` 에서
읽습니다. 운영 접속정보가 커밋될 일이 없습니다.

## 구조

```
app/
  models/
    base.py        Enum · 공통 믹스인
    user.py        User(후원자·위원·운영자) · Shop(나눔가게, 인증배지)
    offer.py       Offer(나눔글)
    case.py        Case — ⚠️ 식별정보 금지 구역
    identity.py    🔴 CaseIdentity · IdentityAccessLog
    match.py       Match · MatchApproval
    credit.py      Credit(증빙) · ThanksMessage(익명 감사)
  identity_service.py   식별정보 접근의 유일한 통로
  accounts.py           계정 발급 · 비밀번호 (운영 계정이 생기는 유일한 길)
  create_office.py      첫 운영자 만들기 — python -m app.create_office
  reporting.py          월간 보고서 계산 (위원 · 동 전체 공용)
  timeutil.py           저장은 UTC, 화면과 '이번 달'은 한국 시간
  permissions.py        권한 매트릭스
  matching.py           매칭 승인 규칙
  security.py           scrypt 해시 · Fernet 암복호화
  routers/       auth · account · donor · member · office
  templates/     Jinja2 (9개 화면, 프로토타입 구조 그대로)
migrations/      Alembic 리비전
tests/
  test_privacy.py     개인정보 격리 불변식
  test_matching.py    승인·전달·취소 흐름
  test_migrations.py  모델 ↔ 마이그레이션 drift 감지
```

대상자(도움받는 분)는 `User` 테이블에 **존재하지 않습니다.** 계정이 없는 것이 설계
원칙입니다.

## 테스트

```bash
.venv/Scripts/python -m pytest tests -q
```

`test_privacy.py` 가 깨지면 기능이 아니라 설계 원칙이 깨진 것입니다. 기능을 추가할
때마다 여기부터 돌려보세요.

## 운영 배포 전 체크리스트

`IUM_ENV=production` 으로 띄우면 ①② 가 개발용 값일 때 **서버가 시작하지 않습니다.** 저장소가
공개되어 있어 소스에 적힌 개발용 키는 비밀이 아니기 때문입니다 — 그 키로 운영이 한 번 돌면 그 사이
저장된 식별정보는 공개 키로 잠긴 셈입니다. 같은 모드에서 로그인 화면의 계정 목록이 숨겨지고,
세션 쿠키가 HTTPS 전용이 되고, `seed.py` 실행이 거부됩니다.

- [ ] `IUM_ENV=production`
- [ ] ① `IUM_IDENTITY_KEY` 새로 생성 — `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"`
      (키를 잃으면 기존 식별정보는 영구 복호화 불가)
- [ ] ② `IUM_SECRET_KEY` 교체 (32자 이상) — `python -c "import secrets;print(secrets.token_urlsafe(48))"`
- [x] ~~Alembic 마이그레이션 도입~~
- [ ] SQLite → PostgreSQL 전환 (초기 리비전 검토 필요)
- [ ] HTTPS 적용 (세션 쿠키는 production 모드에서 자동으로 `secure`)
- [ ] 시·행정복지센터의 개인정보 처리 사전 승인
- [ ] 운영 DB 에 `seed.py` 를 돌린 적이 없는지 확인 (production 모드에서는 실행 자체가 거부됨)
- [ ] 첫 운영자 계정 만들기 (아래)

### 운영 계정 만들기

운영 모드에서는 `seed.py` 가 막혀 있어 계정이 생기는 길은 두 개뿐입니다.

```bash
python -m alembic upgrade head
python -m app.create_office --email office@example.kr --name "협의체 사무국"
```

비밀번호는 명령줄 인자로 받지 않습니다 — 셸 기록과 프로세스 목록에 남기 때문입니다.
화면에 보이지 않게 두 번 입력받습니다.

위원 계정은 이 운영자가 **위원 관리** 화면에서 발급합니다. 임시 비밀번호가 화면에 한 번만
표시되고, 위원은 첫 로그인에서 새 비밀번호를 정해야 다른 화면을 쓸 수 있습니다. 발급·초기화·
위촉 해제는 모두 같은 화면의 **계정 기록**에 남습니다 — 비밀번호를 초기화하면 운영자가 그
계정으로 들어갈 수 있게 되므로, 조용히 일어나지 않게 하기 위해서입니다.

후원자 계정은 위원회 안건 07(계정 발급 방식)이 정해진 뒤에 만듭니다.
