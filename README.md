# 법학 문제집 PDF → Excel 변환 자동화 (v6)

**한 번의 PDF 지정으로 완전 자동 변환** — Claude Code CLI 서브프로세스 기반

## 🎯 개요

법학 객관식 문제집 PDF를 구조화된 Excel로 변환합니다.

- **입력**: PDF 파일 (사용자가 `input/` 폴더에 배치)
- **출력**: Excel (전체 문제 / 검토 필요 / 단원별 / 통계)
- **자동화**: PDF 지정 후 **사용자 개입 0** (검수는 Excel 산출 후)

## 📋 주요 특징 (v6)

| 특징 | 설명 |
|------|------|
| **완전 자동화** | v5의 "Claude Pro 수동 붙여넣기" 제거, CLI 서브프로세스로 자동 호출 |
| **지능형 청킹** | 토큰 기반 동적 청크 + 문제 경계 인식 → 효율적 API 사용 |
| **다층 검증** | 구조 / Diff / 법률 용어 검증 + 신뢰도 점수 |
| **상태 머신** | 중단 후 재개 가능 (사용량 한도 대기 지원) |
| **Windows 호환** | 인코딩/쉘 이스케이프 문제 완전 해결 |

## 🚀 빠른 시작

### 1. 설치

```bash
# 저장소 클론
git clone https://github.com/hankchoi92-ux/PDF-to-EXCEL.git
cd PDF-to-EXCEL

# 의존성 설치
pip install -r requirements.txt

# Claude Code CLI 설치 (아직 없다면)
# https://claude.com/download 참고
```

### 2. PDF 준비

`input/` 폴더에 PDF 파일을 배치합니다.

```
input/
├── 문제집_1.pdf
├── 강의자료_2월.pdf
└── ...
```

### 3. 실행

```bash
python src/main.py --input input/문제집_1.pdf
```

자동으로 4단계를 거칩니다:
- **Phase 0**: 프리플라이트 (CLI 설치/인증 확인)
- **Phase 1**: PDF 전처리 + 동적 청킹
- **Phase 2**: Claude CLI 자동 변환 (핵심)
- **Phase 3**: 검증 및 신뢰도 점수
- **Phase 4**: Excel 생성

### 4. 결과 확인

```
output/
├── 최종_문제집.xlsx      # 전체 문제
├── 검토_필요_목록.xlsx   # 신뢰도 <95% 항목
└── 변환_통계.xlsx       # 처리 현황
```

## 📐 아키텍처

v6 설계 상세는 **`Architecture_v6_Draft.md`** 참고:
- 전체 파이프라인 흐름도
- CLI 서브프로세스 호출 시 8가지 잠재 문제점 & 대응 전략
- 상태 머신 설계 (PAUSED_LIMIT 상태 신설)
- 오류 분류표 및 재시도 정책

## ⚙️ 설정

`config.yaml`에서 조정 가능한 주요 항목:

```yaml
# CLI 타임아웃 (청크당 기본 300초)
cli:
  timeout_seconds: 300
  max_retries: 3

# 청크 크기 (기본 3500 토큰)
chunking:
  max_tokens_per_chunk: 3500

# 자동 확정 기준 (신뢰도 ≥95%)
validation:
  confidence_threshold: 0.95

# 사용량 한도 도달 시 동작
cli:
  on_limit: "wait"  # wait | stop
```

## 🔍 검증 규칙

### 자동 확정 (신뢰도 ≥95%)
- 구조 오류 없음
- 원본 대비 누락 감지 없음
- 법률 용어 불일치 없음

### 수동 검토 필요 (신뢰도 <95%)
- 열린 대괄호 미종결 선지
- 텍스트 급격한 길이 변화 (삭제 의심)
- 사전에 없는 법률 용어
→ **Excel "검토 필요" 시트**로 분류

## 📚 문서

- **CLAUDE.md**: 프로젝트 규칙 (변환 원칙, 용어 사전)
- **Architecture_v6_Draft.md**: 아키텍처 설계 (모듈, 오류 처리)
- **config.yaml**: 설정 명세
- **prompts/prompt_template.md**: Claude 프롬프트 템플릿

## 🐛 문제 해결

| 증상 | 원인 | 해결 |
|------|------|------|
| "claude not found" | CLI 미설치 | `claude --version` 확인 후 재설치 |
| 한글이 깨짐 | 인코딩 문제 | (v6에서 Windows UTF-8 처리함) |
| 타임아웃 반복 | 청크가 너무 큼 | config.yaml에서 `max_tokens_per_chunk` 감소 |
| "PAUSED_LIMIT" | Pro 사용량 한도 | 30분 대기 후 자동 재개 (또는 수동 재시작) |

## 📞 연락

이슈 또는 개선사항: https://github.com/hankchoi92-ux/PDF-to-EXCEL/issues

---

**Last updated**: 2026-07-11 | **v6 Draft**
