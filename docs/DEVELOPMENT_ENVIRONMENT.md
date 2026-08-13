# 개발환경 재현 안내

이 프로젝트는 운영 파이프라인이나 Docker를 실행하지 않고도 개발환경의 버전을 맞출 수 있도록 설치·검증 스크립트를 제공합니다.

## 기준 버전

| 항목 | 기준 |
|---|---|
| Python | 3.11.9 |
| Node.js | 22.13.0 (`web/.nvmrc`) |
| pnpm | 10.22.0 (`web/package.json`) |
| Python 의존성 | `requirements-lock-py311-windows.txt` (Windows 기준) |
| 프런트엔드 의존성 | `web/pnpm-lock.yaml` |

현재 검증된 백엔드 가상환경은 Python 3.11.9입니다. 이 PC의 Node.js는 26.7.0이어서 프로젝트 기준인 22.13.0과 다릅니다. 따라서 프런트엔드 결과를 재현하려면 Node 22.13.0을 설치해야 합니다.

## Windows

PowerShell에서 프로젝트 루트로 이동한 뒤 실행합니다.

```powershell
.\tools\setup_environment.ps1
.\tools\verify_environment.ps1
```

회사 PC 정책 등으로 `.ps1` 실행이 차단되면 현재 PowerShell 세션에만 허용하고 실행합니다.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\tools\setup_environment.ps1
.\tools\verify_environment.ps1
```

Python만 먼저 설치할 때는 다음처럼 실행할 수 있습니다.

```powershell
.\tools\setup_environment.ps1 -SkipFrontend
```

현재 Node 버전으로 단순 호환성만 확인할 때는 다음 옵션을 사용할 수 있지만, 재현 검증으로 간주하지 않습니다.

```powershell
.\tools\verify_environment.ps1 -AllowNodeMismatch
```

전체 테스트까지 실행하려면:

```powershell
.\tools\verify_environment.ps1 -RunTests -RunFrontendChecks
```

## macOS / Linux

```bash
chmod +x tools/setup_environment.sh tools/verify_environment.sh
./tools/setup_environment.sh
./tools/verify_environment.sh
```

macOS/Linux에서는 Windows 전용 lock 파일 대신 `requirements.txt`를 사용합니다. 운영체제별 native wheel 차이는 있을 수 있으므로 반드시 검증 스크립트를 실행합니다.

## 환경변수

설치 스크립트는 `.env`가 없으면 `.env.example`을 복사합니다. 실제 Supabase·외부 서비스 값은 팀원이 각자 안전한 방식으로 입력해야 하며, `.env`는 Git이나 공유 ZIP에 넣지 않습니다.

## 포함하지 않는 것

`.venv`, `node_modules`, 캐시, 실제 `.env`, 실행 중인 서비스는 포함하지 않습니다. 이 항목들은 운영체제와 개인 인증정보에 종속되므로 스크립트로 각자 생성합니다.
