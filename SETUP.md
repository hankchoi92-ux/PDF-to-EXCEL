# 다른 컴퓨터에서 시작하기

## 1. 저장소 클론

```bash
git clone https://github.com/hankchoi92-ux/PDF-to-EXCEL.git
cd PDF-to-EXCEL
git checkout claude/phase-3-validation-modules-1w9oi2
```

## 2. Python 패키지 설치

```bash
pip install pymupdf jsonschema openpyxl PyYAML
```

## 3. 실행

```bash
# Windows (PowerShell)
chcp 65001
python src/main.py 변환할파일.pdf

# Mac / Linux
python3 src/main.py 변환할파일.pdf
```

---

## 주요 경로

| 항목 | 경로 |
|------|------|
| PDF 입력 | `sample/` 또는 `input/` |
| 프롬프트 규칙 | `prompts/prompt_template.md` |
| 결과 Excel | `output/최종_문제집.xlsx` |
| 파이프라인 재실행 | `state/pipeline_state.json` 삭제 후 실행 |

---

## 변환 규칙 요약 (prompt_template.md 기준)

- **ㄱㄴㄷ 조합선택형**: ①~⑤ 대신 ㄱ/ㄴ/ㄷ/ㄹ/ㅁ을 선지번호로, 각 지문 내용을 전문 작성
- **불완전 문제**: 텍스트 잘림·선지 누락 시 해당 문제 삭제
- **선지 텍스트**: 10자 초과 or 완전한 문장이면 `"동일"` 사용 금지, 전문 작성
