# Claude 프롬프트 템플릿 (v6)

이 파일은 청크 변환 시 사용할 프롬프트 템플릿입니다.
각 `{...}` 부분은 실행 시 동적으로 치환됩니다.

---

## 템플릿

```
다음 법학 문제 텍스트를 JSON으로 변환해주세요.

### 구조 정보

- **문제 범위**: {question_range}
- **선지 기호**: {option_symbols}
- **문제당 선지 수**: {options_per_question}
- **해설 구분자**: {explanation_marker}

### 텍스트 상태

- **깨진 문자 비율**: {broken_char_ratio}%
- **과도한 공백 비율**: {excessive_space_ratio}%
- **전체 문자 수**: {total_chars}
- **특이사항**: {special_blocks}

### 로컬 힌트 정보

다음은 PDF 구조 분석으로 감지된 패턴입니다. 변환 시 참고하세요:

{hint_json_pretty}

### 변환할 텍스트

{chunk_text}

---

## 변환 규칙

### 1. 원문 우선
- 명백한 OCR 오류만 수정 (한자·영문 혼용, 맥락상 분명한 오류)
- 불확실하면 `[의심:추정값]` 형태로 표시
- 원본 형식(띄어쓰기, 줄바꿈)을 최대한 유지

### 2. 법률 용어 보정
- 법학 문맥에 맞게 교정 (예: "게약" → "계약")
- 사전에 없는 용어는 보정하지 말 것

### 3. 해설 처리
- 해설이 있으면 `explanation` 필드에 포함
- 해설이 없으면 빈 문자열 `""`

### 4. 선지 텍스트 정규화
- **첫 번째 선지**: 완전한 문제 텍스트 포함
- **2~5번째 선지**: 문제 텍스트를 `"동일"` 으로 표기
- 예외: 각 선지가 완전히 독립적이면 (예: "A국", "B국") 각각 전문 작성

### 5. 정오표 / 답 표기
- `correct` 필드: `true`(O) 또는 `false`(X)만 사용
- 다른 값(숫자, 문자) 금지

---

## 출력 형식 (필수)

반드시 아래 JSON 형식으로 **JSON 외 다른 텍스트 없이** 응답하세요:

```json
{
  "questions": [
    {
      "id": 1,
      "text": "문제 내용 (첫 선지에만 전체 문제 텍스트)",
      "options": [
        {
          "num": "①",
          "text": "선지 내용",
          "correct": true,
          "explanation": "해설 내용"
        },
        {
          "num": "②",
          "text": "동일",
          "correct": false,
          "explanation": ""
        }
      ]
    },
    {
      "id": 2,
      "text": "다음 중 계약의 성립요건으로 옳지 않은 것은?",
      "options": [
        {
          "num": "①",
          "text": "청약",
          "correct": false,
          "explanation": "청약은 성립요건이 아님"
        }
      ]
    }
  ]
}
```

---

## 주의사항

1. **JSON 포맷 엄격함**: 따옴표, 쉼표, 괄호 완벽히 일치
2. **문자열 이스케이프**: JSON 내부 개행은 `\n`, 따옴표는 `\"` 처리
3. **배열 완전성**: 모든 문제에 대해 `id`, `text`, `options` 필수
4. **선지 필수**: 5개 중 1~4개만 있으면 안 됨 (명시된 개수 모두 포함)
5. **빈 값 규칙**: 해설 없음 → `""` (null 금지)
6. **중복 방지**: 같은 문제 ID나 선지가 2회 이상 나오면 안 됨
7. **JSON 외 텍스트 금지**: 설명, 인사말, 마크다운 펜스(`'''`) 불포함

---

## 예제: 변환 전/후

### 입력 텍스트 (청크_001)

```
문1. 다음 중 계약의 성립 요건이 아닌 것은?
①청약
②승낙
③대가 지급
④상대방 의사능력
[해설]
정답은 ④. 대가 지급은 채권발생의 원인이지 계약의 성립요건이 아니다.

문2. 민법상 채권과 채권의 관계를 述述하시오.
①원물채권
②선택채권
③이중채권
④[의심: 부족문장]
[해설] 없음
```

### 출력 (Claude 응답)

```json
{
  "questions": [
    {
      "id": 1,
      "text": "다음 중 계약의 성립 요건이 아닌 것은?",
      "options": [
        {
          "num": "①",
          "text": "청약",
          "correct": false,
          "explanation": "정답은 아님"
        },
        {
          "num": "②",
          "text": "동일",
          "correct": false,
          "explanation": ""
        },
        {
          "num": "③",
          "text": "동일",
          "correct": false,
          "explanation": ""
        },
        {
          "num": "④",
          "text": "동일",
          "correct": true,
          "explanation": "대가 지급은 채권발생의 원인이지 계약의 성립요건이 아니다"
        }
      ]
    },
    {
      "id": 2,
      "text": "민법상 채권과 채권의 관계를 기술하시오.",
      "options": [
        {
          "num": "①",
          "text": "원물채권",
          "correct": false,
          "explanation": ""
        },
        {
          "num": "②",
          "text": "동일",
          "correct": false,
          "explanation": ""
        },
        {
          "num": "③",
          "text": "동일",
          "correct": false,
          "explanation": ""
        },
        {
          "num": "④",
          "text": "동일",
          "correct": false,
          "explanation": "[의심: 원문 부족]"
        }
      ]
    }
  ]
}
```

---

## 템플릿 변수 설명

| 변수 | 예시 | 설명 |
|------|------|------|
| `{question_range}` | "1~8" | 청크 내 문제 번호 범위 |
| `{option_symbols}` | "circled" | 선지 기호 유형 (circled / korean / numeric) |
| `{options_per_question}` | 5 | 문제당 선지 수 |
| `{explanation_marker}` | "[해설]" | 해설 구분자 |
| `{broken_char_ratio}` | 2.3 | 깨진 문자 비율(%) |
| `{excessive_space_ratio}` | 5.1 | 공백 과다 비율(%) |
| `{total_chars}` | 3580 | 전체 문자 수 |
| `{special_blocks}` | "문3에 표 포함" | 특이 구조 |
| `{hint_json_pretty}` | (JSON 포맷) | 로컬 힌트 (구조화된 JSON) |
| `{chunk_text}` | (원본 텍스트) | 실제 변환할 텍스트 |

---

**이 템플릿은 `src/claude_cli_client.py`에서 `{...}` 치환으로 런타임에 생성됩니다.**
