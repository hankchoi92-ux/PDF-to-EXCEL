# 법학 문제집 PDF → Excel 변환 자동화 아키텍처 (v6 Draft)

> v5 설계의 Phase 2(Claude 변환)를 "Claude Pro 웹에 수동 붙여넣기" 방식에서
> **Claude Code CLI 서브프로세스 자동 호출** 방식으로 대체한 통합 설계 초안.
> 근거: `로스쿨 OCR-검수-Notion 프로젝트 — 설계 개요.md`에서 실전 검증된 CLI 호출 패턴.

---

## 0. v5 → v6 변경 요약

### 0.1 v5의 치명적 모순 (해결 대상)

v5는 §1.1에서 "**사용자 개입: PDF 파일 지정만 수동, 이후 모든 과정 자동화**"를 표방하지만,
실제 설계는 이를 충족하지 못한다:

| 위치 | v5 실제 내용 | 모순 |
|------|-------------|------|
| §3.6 `claude_client.py` docstring | "우선은 **텍스트 생성하여 사용자가 Claude Pro에 입력**하는 방식. 추후 API 사용 가능 시 자동화로 전환" | Phase 2가 사실상 수동 |
| §5 `auto_pipeline.run()` | `print("N개 청크를 Claude Pro에서 처리하세요")` 후 `_wait_for_responses()` 로 사용자가 responses/ 폴더에 응답을 저장할 때까지 대기 | 청크 수(6~80개)만큼 복사-붙여넣기 노동 발생 |
| §1.3 변경 표 | "자동화 수준: 반자동 → **PDF 지정 후 완전 자동**" | 선언과 구현 불일치 |

100문제 = 6~8회, 1000문제 = 60~80회의 수동 붙여넣기가 필요하므로
"완전 자동"은 성립하지 않고, 상태 머신의 `SENT` → `RESPONDED` 전이도 사람 손에 의존한다.

### 0.2 해결책: CLI 서브프로세스 호출 (OCR 프로젝트 검증 패턴 이식)

OCR-검수-Notion 프로젝트에서 이미 검증된 사실:

- 로컬에 설치된 **Claude Code CLI**를 `claude -p` 헤드리스 모드로 서브프로세스 호출하면,
  API 키·추가 비용 없이(Pro 구독 내에서) 프로그램이 Claude 응답을 직접 수신할 수 있다.
- Windows 환경 필수 노하우 3가지가 이미 확보되어 있다:
  1. **프롬프트는 임시 파일 경유 전달** (PowerShell/cmd 쉘 이스케이프·한글 인코딩 문제 회피)
  2. **인코딩은 모든 경계에서 UTF-8 명시** (Windows 기본 cp949가 한글을 깨뜨림)
  3. **`--allowedTools` 최소 권한 + `timeout` 필수**

→ v5의 `claude_client.py`(입력 텍스트 생성기)를 `claude_cli_client.py`(서브프로세스 실행기)로
교체하면 Phase 2가 진짜 자동화되고, v5의 나머지 설계(청킹·힌트·검증·상태 머신·Excel 생성)는
**그대로 유효**하다.

### 0.3 v5 → v6 변경 표

| 항목 | v5 | v6 | 사유 |
|------|-----|-----|------|
| Claude 연동 | Claude Pro 웹 수동 입력 | **CLI 서브프로세스 자동 호출** | 완전 자동화 실현 |
| Phase 2 상태 전이 | 사용자가 responses/ 저장 시 진행 | **프로그램이 stdout 수신 즉시 진행** | 상태 머신 자동 구동 |
| `claude_project/` (Project Knowledge) | Claude Pro Project 설정 | **폐지** — 내용을 프롬프트 템플릿에 통합 | 웹 UI 미사용 |
| 프롬프트 전달 | (미정의) | **임시 UTF-8 파일 경유** | 쉘 이스케이프/인코딩 회피 |
| 참고 이미지 전송 | 청크당 1장 웹 업로드 | `--allowedTools Read` + 이미지 경로를 프롬프트에 명시 | CLI 멀티모달 Read 활용 |
| 실패 유형 | 파싱 실패 중심 | **+ 타임아웃, 인코딩, 사용량 한도, 인증 만료** | 서브프로세스 특유 실패 모드 |
| 상태 머신 | 12개 상태 | **+ `PAUSED_LIMIT`** (사용량 한도 대기) | Pro 5시간 윈도우 대응 |
| 사전 점검 | 없음 | **Phase 0 프리플라이트** (CLI 설치/인증/버전 확인) | 조기 실패(fail-fast) |

v5의 유지 항목: JSON 출력, 토큰 기반 동적 청킹, 로컬 힌트, 다층 검증(구조+Diff+용어),
신뢰도 점수, 법률 용어 사전, Excel 4시트 구성 — 전부 그대로.

---

## 1. 전체 파이프라인 (v6)

```
[입력] PDF 파일 (사용자가 경로 지정)  ← 유일한 수동 개입
    ↓
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Phase 0] 프리플라이트 (로컬, 토큰 0)  ★ v6 신설
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ├─ claude CLI 설치 확인 (claude --version)
    ├─ 인증 상태 확인 (초소형 프롬프트 1회 실행 → 정상 응답 확인)
    ├─ 사전 파일(legal_terms.json) 존재 확인
    └─ 실패 시 즉시 중단 + 원인 안내 (청크 생성 후 실패하는 낭비 방지)
    ↓
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Phase 1] PDF 전처리 (로컬, 토큰 0)  — v5와 동일
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ├─ PyMuPDF로 텍스트 + 좌표 추출
    ├─ 문제 번호/선지 기호 패턴 감지 → 로컬 힌트 생성
    ├─ 토큰 추정 기반 동적 청킹
    ├─ 객관적 텍스트 지표 측정
    └─ 법률 용어 사전 기반 1차 경량 보정
    ↓
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Phase 2] Claude CLI 자동 변환 (서브프로세스, 토큰 사용)  ★ v6 핵심 변경
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    청크별 루프 (기본 순차 실행):
    ├─ ① 프롬프트 조립 (템플릿 + 로컬 힌트 + 보정된 텍스트)
    ├─ ② 임시 UTF-8 파일로 저장 (temp/prompt_{chunk_id}_{uuid}.txt)
    ├─ ③ subprocess 로 `claude -p` 실행
    │      - stdin 또는 파일 경유로 프롬프트 전달 (쉘 이스케이프 회피)
    │      - --allowedTools 'Read' (참고 이미지 필요 시) 또는 무권한
    │      - timeout=300s (config 조정 가능)
    ├─ ④ stdout 을 UTF-8 로 명시 디코딩 → responses/chunk_NNN.json 저장
    ├─ ⑤ JSON 추출·파싱·스키마 검증 (response_parser)
    ├─ ⑥ 실패 시 자동 재시도 (최대 3회, 지수 백오프)
    │      - 파싱 실패 반복 → 청크 이분할 후 재시도
    │      - 사용량 한도 감지 → PAUSED_LIMIT 상태로 대기/중단 후 재개
    ├─ ⑦ 임시 프롬프트 파일 finally 삭제
    └─ 상태 머신: CHUNK_READY → SENT → RESPONDED → PARSED (전부 자동 전이)
    ↓
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Phase 3] 검증 및 보정 (로컬, 토큰 0)  — v5와 동일
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ├─ 구조 검증 / Diff 검증 / 법률 용어 2차 검증
    ├─ 신뢰도 점수 부여 → AUTO / HUMAN_REVIEW 분류
    └─ (검토 필요 항목은 Excel "검토 필요" 시트로 — 파이프라인은 멈추지 않음)
    ↓
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Phase 4] Excel 생성 (로컬, 토큰 0)  — v5와 동일
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    └─ 전체 문제 / 검토 필요 / 단원별 / 변환 통계 시트
    ↓
[출력] Excel 파일 + 검토 리포트
```

**핵심 차이**: v5에서 Phase 2는 "사용자가 Claude Pro에 붙여넣고 응답을 저장할 때까지 대기"였다.
v6에서는 ③~⑤가 프로그램 내부에서 완결되므로, PDF 지정 후 Excel 산출까지
**사람 개입 지점이 0**이 된다 (검수는 Excel 산출 이후의 후속 작업).

---

## 2. CLI 서브프로세스 호출: 잠재 문제점과 대응 전략

OCR 프로젝트에서 실제 겪었거나, 규모 확대(단건 이미지 → 수십 개 청크 배치) 시
새로 예상되는 문제를 정리한다. **(A)~(C)는 OCR 프로젝트에서 검증된 회피책 이식,
(D)~(I)는 배치 규모에서 새로 대비할 항목.**

### (A) 한글 인코딩 깨짐 — 발생 확률 높음, Windows 필연

- **원인**: Windows 콘솔/파이프 기본 인코딩이 cp949. 프롬프트 전달·stdout 수신 양쪽에서 깨질 수 있음.
- **전략**:
  1. 프롬프트는 **반드시 임시 파일에 UTF-8로 저장** 후 전달 (명령줄 인자로 한글 직접 전달 금지).
  2. `subprocess.run(..., capture_output=True)`로 **bytes 수신 후 명시적으로
     `stdout.decode('utf-8', errors='replace')`** — `text=True`(locale 의존 디코딩) 금지.
  3. 자식 프로세스 환경변수에 `PYTHONIOENCODING=utf-8` 주입.
  4. **디버깅 훅**: 디코딩 후 `�`(replacement char) 비율을 측정해 임계값(예: 0.5%) 초과 시
     인코딩 오류로 분류·재시도. 원시 bytes를 `logs/raw/`에 보존해 사후 분석 가능하게 함.

### (B) 쉘 이스케이프 — 프롬프트에 따옴표·백틱·`$` 포함 시 명령 파괴

- **원인**: 법학 지문에는 따옴표·특수문자가 흔함. 쉘 경유 시 인자 파싱이 깨짐.
- **전략** (우선순위 순):
  1. **1안: stdin 파이프** — `subprocess.run(['claude', '-p', ...], stdin=프롬프트파일핸들)`.
     쉘을 아예 통과하지 않으므로 이스케이프 문제가 원천 차단됨. `shell=False` 유지.
     (Windows에서 `claude`가 `.cmd` shim인 경우 전체 경로 확인 또는 `shutil.which('claude')` 선행.)
  2. **2안(폴백): OCR 프로젝트 검증 패턴** — PowerShell 경유
     `[IO.File]::ReadAllText(임시파일, UTF8)` → `claude -p $p`. 이미 동작이 확인된 방식.
  - 구현 시 1안 → 실패 시 2안 폴백 구조로 하고, 프리플라이트에서 어느 쪽이 동작하는지 1회 판정.

### (C) 타임아웃 / 프로세스 행(hang)

- **원인**: 긴 청크, 네트워크 지연, CLI 내부 오류로 응답이 영원히 안 올 수 있음.
- **전략**:
  1. `subprocess.run(..., timeout=config.cli.timeout)` (기본 300s) — OCR 프로젝트와 동일.
  2. `TimeoutExpired` 시 프로세스 강제 종료 확인 후 상태 `FAILED` 기록, 재시도 큐로.
  3. **2회 연속 타임아웃 → 청크 이분할 후 재시도** (긴 청크가 원인일 가능성).
  4. 청크별 소요 시간을 `chunk_manifest`에 누적 기록 → 평균 대비 이상치 모니터링,
     남은 시간 예측(ETA) 표시에 활용.

### (D) 청크 크기 한계 / 출력 잘림(truncation)

- **원인**: 입력이 커지면 출력 JSON도 커지는데, 출력이 중간에 잘리면 JSON 파싱이 실패한다.
  잘림은 "닫는 괄호 누락"으로 나타나므로 **파싱 오류와 구분해 진단해야 함**.
- **전략**:
  1. v5의 토큰 기반 청킹(기본 3,500토큰) 유지 — 입력뿐 아니라 **예상 출력 토큰**
     (해설 포함 문제는 출력이 입력의 1.5~2배)을 기준으로 상한 설정.
  2. 파싱 실패 시 원인 분류: (a) JSON 앞뒤 잡음 → 재추출, (b) 끝부분 잘림 → **청크 축소 후 재시도**,
     (c) 구조 오류 → 재시도 프롬프트(오류 상세 첨부).
  3. `response_parser`에 "마지막 완전한 question 객체까지 부분 복구" 모드를 두어,
     재시도 시 이미 성공한 문제는 제외하고 나머지만 요청 (토큰 절약).

### (E) JSON 앞뒤 잡음 (인사말·마크다운 펜스)

- **원인**: 프롬프트로 금지해도 모델이 ```json 펜스나 설명 문장을 붙일 수 있음.
- **전략**:
  1. v5 `extract_json_from_text()` 유지: 펜스 블록 우선 추출 → 실패 시 첫 `{`~마지막 `}` 추출.
  2. 프롬프트 말미에 "JSON 외 텍스트 출력 금지" 규칙 유지 (OCR 프로젝트의 "결과 텍스트만 출력" 규칙과 동일 패턴).
  3. CLI의 `--output-format json` 옵션(결과를 JSON 봉투로 감싸 stdout 반환) 사용을 검토 —
     봉투 파싱이 한 겹 추가되지만 stdout 오염 대비가 확실해짐. 프리플라이트에서 지원 여부 확인.

### (F) 사용량 한도 (Pro 구독 5시간 윈도우) — 대량 배치의 최대 병목

- **원인**: 1000문제 = 60~80청크를 연속 호출하면 Pro 사용량 한도에 걸릴 수 있음.
  v5도 "2~3회 세션"을 예상했으나 수동 방식이라 사람이 자연히 끊어 갔음. 자동화하면 프로그램이 이를 감지해야 함.
- **전략**:
  1. stderr/stdout에서 한도 초과 패턴(rate limit / usage limit 문구, 특정 exit code) 감지 →
     **`PAUSED_LIMIT` 상태로 전이** (v6 신설 상태).
  2. config의 `on_limit: wait | stop` 선택: `wait`면 지정 간격(예: 30분)마다 소형 프롬프트로 재확인 후 재개,
     `stop`이면 상태 저장 후 종료 — **어느 쪽이든 v5 상태 머신의 재개(resume) 능력으로 이어서 처리**.
  3. 청크 사이 `inter_chunk_delay`(기본 수 초) 삽입으로 버스트 완화.

### (G) 인증 만료 / CLI 미설치·버전 변경

- **원인**: CLI 로그인 세션 만료, 미설치 환경, CLI 업데이트로 플래그 명세 변경.
- **전략**: **Phase 0 프리플라이트**에서 일괄 검사.
  `claude --version` 확인 → 초소형 테스트 프롬프트 1회 실행해 정상 응답·인코딩·소요시간 기준선 확보.
  실패 시 청크 생성 전에 즉시 중단하고 원인별 안내 메시지 출력.
  본 실행 중 인증 오류 감지 시에도 `FAILED(auth)`로 분류해 재시도 낭비 방지.

### (H) 세션 컨텍스트 오염 (CLAUDE.md 자동 로딩)

- **원인**: `claude -p`는 실행 디렉토리의 CLAUDE.md 등 프로젝트 컨텍스트를 자동 로딩한다.
  무관한 프로젝트 규칙이 변환 프롬프트에 섞이면 출력 형식이 흔들릴 수 있음.
- **전략**:
  1. 서브프로세스의 `cwd`를 **본 프로젝트 루트로 고정**하고, 프로젝트 CLAUDE.md에는
     변환 규칙(v5 §4.1 Project Knowledge 내용)을 담아 **오히려 일관성 강화에 활용**.
  2. 프롬프트 템플릿과 CLAUDE.md 규칙을 일치시키는 OCR 프로젝트 패턴 준수
     (규칙 변경 시 두 곳 동시 갱신).

### (I) 임시 파일 잔존 / 동시 실행 충돌

- **원인**: 비정상 종료 시 temp 파일 잔존, (향후 병렬화 시) 파일명 충돌.
- **전략**:
  1. 임시 파일명에 `chunk_id + uuid` 포함, `finally`에서 삭제 (OCR 프로젝트 패턴).
  2. 시작 시 `temp/`에서 24시간 이상 지난 파일 청소.
  3. 병렬 실행은 **기본 비활성**(`max_parallel: 1`) — 사용량 한도·순서 보장 문제로
     순차가 안전. 병렬화는 v7 과제로 이연.

### 재시도 정책 종합 (Phase 2 오류 분류표)

| 오류 유형 | 감지 방법 | 1차 대응 | 반복 시 |
|-----------|----------|---------|--------|
| 타임아웃 | `TimeoutExpired` | 재시도 (백오프) | 청크 이분할 |
| 인코딩 오염 | `�` 비율 임계 초과 | 재시도 | 원시 bytes 보존 후 FAILED |
| JSON 잡음 | 파싱 실패 + 본문 존재 | 재추출 → 재시도 프롬프트 | 청크 이분할 |
| 출력 잘림 | JSON 미종결 | 부분 복구 + 나머지만 재요청 | 청크 축소 |
| 사용량 한도 | stderr 패턴/exit code | `PAUSED_LIMIT` 대기 또는 저장 후 종료 | (재시도 아님) |
| 인증 오류 | stderr 패턴 | 즉시 중단 + 안내 | (재시도 아님) |
| 기타 비정상 종료 | exit code ≠ 0 | stderr 로깅 후 재시도 | FAILED |

공통: 최대 재시도 3회, 지수 백오프(5s → 15s → 45s), 모든 시도를 `logs/conversion.log`에
청크 ID·시도 번호·소요시간·오류 유형과 함께 기록.

---

## 3. 디렉토리 구조 (v6)

```
law-quiz-excel/                     # 프로젝트 루트
├── CLAUDE.md                       # ★ 변환 규칙 (구 claude_project/project_knowledge.md 통합)
│                                   #    claude -p 서브프로세스가 자동 로딩 → 규칙 일관성 확보
├── config.yaml                     # 설정 (cli 섹션 신설)
├── requirements.txt                # pymupdf, openpyxl, pyyaml, jsonschema
├── README.md
├── input/                          # 사용자가 PDF 배치
├── chunks/                         # 자동 생성 (v5와 동일)
│   ├── texts/                      #   chunk_001.txt ...
│   ├── hints/                      #   chunk_001_hint.json ...
│   ├── images/                     #   chunk_001_layout.png ... (참고 이미지)
│   └── chunk_manifest.json
├── prompts/                        # ★ 구 claude_project/ 대체
│   └── prompt_template.md          #   프롬프트 템플릿 (v5 §4.2 계승)
├── temp/                           # ★ 신설: 임시 프롬프트 파일 (자동 생성·삭제)
├── responses/                      # Claude 응답 원문 저장 (v5와 동일)
├── dictionaries/
│   ├── legal_terms.json
│   └── correction_rules.yaml
├── state/
│   └── pipeline_state.json
├── logs/
│   ├── conversion.log
│   └── raw/                        # ★ 신설: 디코딩 실패 시 원시 bytes 보존 (사후 분석)
├── output/
│   ├── 최종_문제집.xlsx
│   ├── 검토_필요_목록.xlsx
│   └── 변환_통계.xlsx
└── src/
    ├── main.py                     # CLI 진입점
    ├── auto_pipeline.py            # ★ 수정: Phase 0 추가, Phase 2 대기 로직 삭제
    ├── preflight.py                # ★ 신설: CLI 설치/인증/인코딩 사전 점검
    ├── pdf_extractor.py            # (유지)
    ├── local_hint_generator.py     # (유지)
    ├── chunk_manager.py            # (유지)
    ├── text_metrics.py             # (유지)
    ├── local_corrector.py          # (유지)
    ├── claude_cli_client.py        # ★ 교체: 구 claude_client.py → 서브프로세스 실행기
    ├── response_parser.py          # ★ 보강: 부분 복구 모드, 오류 유형 분류
    ├── structure_validator.py      # (유지)
    ├── diff_validator.py           # (유지)
    ├── term_validator.py           # (유지)
    ├── confidence_scorer.py        # (유지)
    ├── state_manager.py            # ★ 보강: PAUSED_LIMIT 상태 추가
    └── excel_builder.py            # (유지)
```

v5 대비 삭제: `claude_project/` (Claude Pro 웹 Project 설정 — 더 이상 웹 UI를 쓰지 않음).
내용은 `CLAUDE.md`(역할·핵심 규칙)와 `prompts/prompt_template.md`(청크별 템플릿)로 분리 통합.

---

## 4. 핵심 모듈 변경 상세

### 4.1 `claude_cli_client.py` (신규 — v5 `claude_client.py` 대체)

```python
class ClaudeCliClient:
    """
    Claude Code CLI를 서브프로세스로 호출해 청크를 변환.
    OCR-검수-Notion 프로젝트의 run_ocr() 패턴을 배치용으로 일반화.
    """

    def __init__(self, config: dict):
        # config.cli: timeout, max_retries, allowed_tools, claude_cmd 등
        ...

    def convert_chunk(self, chunk: dict) -> CliResult:
        """
        1. build_prompt(chunk)           # 템플릿 + 힌트 + 텍스트 조립
        2. _write_temp_prompt(prompt)    # temp/에 UTF-8 저장 (uuid 포함)
        3. _invoke_cli(prompt_path)      # subprocess 실행 (stdin 우선, PS 폴백)
        4. _decode_stdout(raw_bytes)     # UTF-8 명시 디코딩 + � 비율 검사
        5. finally: 임시 파일 삭제
        반환: CliResult(stdout, stderr, exit_code, duration, error_type)
        """

    def _classify_error(self, result: CliResult) -> str:
        """TIMEOUT | ENCODING | AUTH | RATE_LIMIT | NONZERO_EXIT | OK"""

    def run_with_retry(self, chunk: dict) -> dict:
        """오류 분류표에 따른 재시도/이분할/일시정지 정책 실행"""
```

### 4.2 `preflight.py` (신규)

- `claude --version` 실행 가능 여부, 응답 파싱.
- 초소형 테스트 프롬프트("OK만 출력") 1회 실행 → 인증·인코딩·기준 응답시간 확인.
- stdin 전달 방식 동작 여부 판정 (1안/2안 선택 결과를 state에 기록).
- 사전 파일·디렉토리 존재 확인. 실패 항목별 해결 안내 메시지.

### 4.3 `state_manager.py` (보강)

```
상태 추가: PAUSED_LIMIT   # 사용량 한도로 일시정지 (재개 가능)
전이 추가: SENT → PAUSED_LIMIT → CHUNK_READY (재개 시)
메타데이터 추가: error_type, cli_duration, retry_count, split_from(이분할 이력)
```

### 4.4 `auto_pipeline.py` (수정)

- `_wait_for_responses()` **삭제** — 수동 대기 루프 제거.
- Phase 2를 `for chunk in chunks: claude_cli_client.run_with_retry(chunk)` 순차 루프로 교체.
- 진행률 출력: `[Phase 2/4] 청크 12/34 변환 중... (평균 42s/청크, 예상 잔여 15분)`.

### 4.5 `config.yaml` — `cli` 섹션 신설

```yaml
cli:
  claude_cmd: "claude"          # 또는 절대 경로
  timeout_seconds: 300
  max_retries: 3
  backoff_seconds: [5, 15, 45]
  allowed_tools: ["Read"]       # 참고 이미지 불필요 시 []
  inter_chunk_delay_seconds: 3
  max_parallel: 1               # v6에서는 순차 고정
  on_limit: "wait"              # wait | stop
  limit_recheck_minutes: 30
```

---

## 5. 남은 논점 (개발 계획 논의 시 결정)

1. **참고 이미지 전송 방식**: v5는 "청크당 1장 웹 업로드"였으나, v6에서는
   `--allowedTools Read` + 프롬프트에 이미지 경로 명시로 대체 가능.
   다만 토큰 비용이 커지므로 "텍스트 지표가 나쁠 때만 이미지 첨부" 조건부 방식 검토.
2. **`--output-format json` 채택 여부**: 프리플라이트에서 지원 확인 후 결정.
3. **v5 문서 말미 유실**: 원본 v5 파일이 §6 `config.yaml` 중간에서 잘려 있음.
   §6 이후에 있었을 설정 항목·개발 로드맵이 있다면 v6에 반영 필요 — 원본 확인 요망.
4. **Pro 사용량 한도의 실측**: 청크당 실제 소모량을 초기 실행에서 측정해
   1000문제 규모의 세션 분할 계획을 config 기본값에 반영.
