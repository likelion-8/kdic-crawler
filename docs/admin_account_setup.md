# 관리자 계정 만들기 · 비밀번호 바꾸기

관리자 화면(AD-000 로그인)에 쓸 계정을 손으로 넣는 절차다. **계정 관리 API가 아직 없어서**
(AD-010은 목 유지) 지금은 이게 유일한 수단이다.

- 대상 테이블: `admin_accounts` (`src/schema_admin.py`)
- 비밀번호는 bcrypt 해시로만 저장한다. **평문을 넣으면 로그인이 안 된다** —
  `api/routers/admin_auth.py` 의 `bcrypt.checkpw()` 가 해시 형식을 기대한다.

---

## 0. 준비 — bcrypt 설치

`requirements.txt` 에 고정돼 있지만 venv 에 안 깔려 있을 수 있다(2026-08-10 기준 팀 전원 미설치였다).

```bash
./.venv/Scripts/python.exe -m pip install -r requirements.txt
```

---

## 1. 방법 A — 스크립트 (권장)

**손으로 타이핑하는 값이 이메일·이름뿐**이라 오타로 깨질 여지가 적다. 비밀번호는 `getpass` 로
받으므로 셸 히스토리에도 남지 않는다.

```bash
./.venv/Scripts/python.exe -c "
import sys; sys.path.insert(0, 'src')
import bcrypt, getpass
from db import get_session
from sqlalchemy import text

email = input('이메일: ').strip()
name  = input('이름: ').strip()
pw    = getpass.getpass('비밀번호(10자 이상, ASCII): ')

h = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
with get_session() as s:
    s.execute(text('''
        INSERT INTO admin_accounts (email, name, password_hash, role, status)
        VALUES (:e, :n, :h, 'ADMIN', '활성')
        ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash
    '''), {'e': email, 'n': name, 'h': h})
print('완료:', email)
"
```

- `role`·`status` 를 **코드가 박는다** — 이 두 값은 손으로 치면 안 되는 값이다(아래 3절).
- `ON CONFLICT` 가 걸려 있어 **여러 번 돌려도 안전하고, 같은 명령이 곧 비밀번호 변경**이다.
- 역할을 `EDITOR`·`OPERATOR`·`VIEWER` 로 만들려면 SQL 의 `'ADMIN'` 만 바꾼다.

### 비밀번호만 바꿀 때

위 명령을 같은 이메일로 다시 돌리면 된다(`ON CONFLICT ... DO UPDATE`). 기존에 로그인해 둔
세션은 그대로 살아 있으므로, 끊고 싶으면 `admin_sessions` 의 해당 계정 행에 `revoked_at` 을
채운다.

---

## 2. 방법 B — Supabase 대시보드

스크립트를 못 돌리는 상황(파이썬 환경 없음 등)에서만 쓴다. **해시 만드는 단계는 여전히 필요하다.**

```bash
./.venv/Scripts/python.exe -c "
import bcrypt, getpass
print(bcrypt.hashpw(getpass.getpass('비밀번호: ').encode(), bcrypt.gensalt()).decode())
"
```

출력된 `$2b$12$...`(60자)를 들고 Table Editor → `admin_accounts` → Insert row:

| 컬럼 | 값 |
|---|---|
| `id` | **비워둔다** (`gen_random_uuid()`) |
| `email` | 로그인 ID |
| `name` | 화면에 표시할 이름 |
| `password_hash` | 위에서 나온 60자 **통째로** |
| `role` | `ADMIN` \| `EDITOR` \| `OPERATOR` \| `VIEWER` |
| `status` | `활성` (비워두면 기본값 `활성`) |
| `last_login_at` | **비워둔다** |
| `created_at` | **비워둔다** (`now()`) |

---

## 3. 🔴 손으로 칠 때 깨지는 값 두 개

이 문서가 스크립트를 권하는 이유다.

| 컬럼 | 허용 값 | 틀리면 |
|---|---|---|
| `status` | `활성` · `비활성` · `초대됨` · `잠김` | **로그인은 되는데 그다음 요청부터 전부 401.** 인증 의존성이 `status != '활성'` 이면 세션을 거부하는데, 로그인 자체는 통과하므로 원인을 찾기 어렵다. 앞뒤 공백 하나로도 재현된다 |
| `role` | `VIEWER` · `OPERATOR` · `EDITOR` · `ADMIN` | 화면의 역할 배지·메뉴 노출이 통째로 어긋난다(`web/src/lib/codes.ts` 가 닫힌 union 이라 목록에 없는 값은 조회가 undefined 가 된다) |

값의 정본은 `src/schema_admin.py` 주석과 `web/src/lib/codes.ts` 다.

---

## 4. 확인

넣은 뒤 이걸로 검증한다. **비밀번호까지 실제로 대조**하므로 해시 복사 실수도 여기서 걸린다.

```bash
./.venv/Scripts/python.exe -c "
import sys; sys.path.insert(0, 'src')
import bcrypt, getpass
from db import get_session
from sqlalchemy import text

email = input('이메일: ').strip()
with get_session() as s:
    r = s.execute(text('select name, role, status, password_hash from admin_accounts where email=:e'),
                  {'e': email}).first()
if r is None:
    print('그런 계정이 없다')
else:
    print('name  :', r.name)
    print('role  :', r.role)
    print('status:', repr(r.status), '/ 활성인가:', r.status == '활성')
    print('비밀번호 검증:', bcrypt.checkpw(getpass.getpass('비밀번호: ').encode(), r.password_hash.encode()))
"
```

`활성인가: True` · `비밀번호 검증: True` 둘 다 나와야 한다.

서버까지 확인하려면(백엔드가 떠 있을 때):

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8000/api/admin/login \
  -H 'Content-Type: application/json' -d '{"email":"admin@demo","password":"..."}'
```

`200` 이면 끝. `403` 은 이메일·비밀번호 불일치이거나 `status` 가 `활성` 이 아니라는 뜻이다
(둘을 같은 응답으로 묶어 뒀다 — 계정 존재 여부를 탐색당하지 않기 위해서다).

---

## 5. 지켜야 할 것

- **비밀번호를 코드에 박아 커밋하지 않는다.** 해시라도 마찬가지다. `.env` 는 gitignore 지만
  이 문서의 명령들은 어디서 실행하든 히스토리에 남을 수 있으므로 `getpass` 형태를 쓴다.
- **비밀번호는 ASCII 로만.** `b'...'` 바이트 리터럴에 한글을 넣으면 실행 전에
  `SyntaxError: bytes can only contain ASCII literal characters` 가 난다.
- **팀 공용 Supabase다.** 계정 하나가 팀 전체의 관리자 권한이다. 데모용 약한 비밀번호를
  그대로 배포까지 끌고 가지 않는다.
- **이 절차는 활동 로그(`admin_activity_logs`)에 남지 않는다.** 계정 생성은 원래 감사 대상이지만
  대시보드·스크립트 직접 조작은 API 를 거치지 않기 때문이다. 누구를 언제 만들었는지는
  사람이 따로 공유해야 한다.

---

## 6. 이 문서가 폐기되는 시점

아래 중 하나라도 해당되면 이 절차를 그만두고 그쪽으로 옮긴다.

| 조건 | 대신 쓸 것 |
|---|---|
| 계정 관리 API(`POST /api/admin/accounts`)를 구현했다 | 관리자 화면 AD-010. 활동 로그도 자동으로 남는다 |
| 배포 환경이 생겼다 | Supabase 대시보드 접근이 없는 사람도 계정을 만들어야 하므로 `scripts/` 에 정식 스크립트로 옮긴다 |
| 계정이 5개를 넘었다 | 손으로 관리할 규모가 아니다 |
