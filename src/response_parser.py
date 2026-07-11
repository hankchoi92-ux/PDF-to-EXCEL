"""
JSON 응답 파싱 및 검증

Claude JSON 응답 추출, 스키마 검증, 정규화.
"""

import json
import logging
import re
from typing import Dict, List, Any, Tuple, Optional
from jsonschema import validate, ValidationError

# ```json ... ``` 또는 ``` ... ``` 펜스 블록 추출용
_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL | re.IGNORECASE)


class ResponseParser:
    """
    Claude JSON 응답 검증 및 정규화.
    """

    # JSON 스키마 정의
    EXPECTED_SCHEMA = {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "text": {"type": "string"},
                        "options": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "num": {"type": "string"},
                                    "text": {"type": "string"},
                                    "correct": {"type": "boolean"},
                                    "explanation": {"type": "string"}
                                },
                                "required": ["num", "text", "correct"]
                            }
                        }
                    },
                    "required": ["id", "text", "options"]
                }
            }
        },
        "required": ["questions"]
    }

    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        초기화.

        Args:
            logger: 로거 인스턴스 (선택적)
        """
        self.logger = logger or logging.getLogger(__name__)

    def parse_and_validate(self, response_text: str) -> Tuple[bool, Optional[Dict[str, Any]], List[str]]:
        """
        JSON 파싱 및 스키마 검증.

        단계:
        1. 텍스트에서 JSON 블록 추출
        2. JSON 파싱
        3. 스키마 검증
        4. 데이터 정규화
        5. 부분 복구 모드 (출력 잘림 감지 시)

        Args:
            response_text: Claude 응답 텍스트

        Returns:
            Tuple[bool, Dict|None, List[str]]: (성공, 파싱된 데이터, 오류/경고 목록)
        """
        response_text = response_text or ""
        json_str = self.extract_json_from_text(response_text)
        if json_str is None:
            return False, None, ["응답에서 JSON 블록을 찾을 수 없음"]

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            if self.detect_truncation(json_str):
                recovered, count = self.recover_partial(json_str)
                if recovered is not None and count > 0:
                    errors = self.validate_schema(recovered)
                    if not errors:
                        normalized = self.normalize(recovered)
                        return True, normalized, [
                            f"출력 잘림 감지 → 부분 복구 성공 (문제 {count}개만 포함, JSON 오류: {e})"
                        ]
                    return False, None, [f"부분 복구된 데이터가 스키마와 불일치: {errors}"]
                return False, None, [f"출력 잘림 감지, 복구 가능한 문제 없음 (JSON 오류: {e})"]
            return False, None, [f"JSON 파싱 오류: {e}"]

        errors = self.validate_schema(data)
        if errors:
            return False, None, errors

        normalized = self.normalize(data)
        return True, normalized, []

    def extract_json_from_text(self, text: str) -> Optional[str]:
        """
        텍스트에서 JSON 블록 추출.

        우선순위:
        1. ```json ... ``` 펜스
        2. 첫 { ~ 마지막 } 추출

        Args:
            text: 텍스트

        Returns:
            str: 추출된 JSON 문자열, 또는 None (JSON 없음)
        """
        if not text:
            return None

        m = _FENCE_RE.search(text)
        if m:
            candidate = m.group(1).strip()
            if candidate:
                return candidate

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text[start:end + 1]
        return None

    def validate_schema(self, data: Dict[str, Any]) -> List[str]:
        """
        JSON 스키마 검증.

        Args:
            data: 파싱된 JSON 데이터

        Returns:
            List[str]: 오류 목록 (빈 리스트 = 통과)
        """
        try:
            validate(instance=data, schema=self.EXPECTED_SCHEMA)
        except ValidationError as e:
            return [f"스키마 검증 실패: {e.message} (경로: {'/'.join(str(p) for p in e.path)})"]
        return []

    def normalize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        데이터 정규화.

        작업:
        - correct: boolean → 그대로 유지 (클라이언트 해석용)
        - 빈 explanation → "해설 없음" 처리
        - 중복 question text → 2번째부터 "동일" 처리
        - 선지 text 정규화 (좌우 공백 제거)

        Args:
            data: 파싱된 JSON

        Returns:
            Dict: 정규화된 데이터
        """
        questions = data.get("questions", []) or []
        prev_text: Optional[str] = None
        normalized_questions: List[Dict[str, Any]] = []

        for q in questions:
            text = (q.get("text") or "").strip()
            if prev_text is not None and text and text == prev_text:
                text = "동일"
            else:
                prev_text = text if text else prev_text

            options = []
            for opt in q.get("options", []) or []:
                explanation = (opt.get("explanation") or "").strip()
                options.append({
                    "num": str(opt.get("num", "")).strip(),
                    "text": (opt.get("text") or "").strip(),
                    "correct": bool(opt.get("correct", False)),
                    "explanation": explanation if explanation else "해설 없음",
                })

            normalized_questions.append({
                "id": q.get("id"),
                "text": text,
                "options": options,
            })

        return {"questions": normalized_questions}

    def detect_truncation(self, text: str) -> bool:
        """
        출력 잘림 감지.

        마지막 `}` 누락, 닫히지 않은 배열/객체 감지.

        문자열 리터럴 내부의 괄호는 무시하도록 상태를 추적하며 스캔한다.

        Args:
            text: JSON 텍스트

        Returns:
            bool: 잘림 여부
        """
        if not text:
            return False

        depth = 0
        in_string = False
        escape = False
        for ch in text:
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch in "{[":
                depth += 1
            elif ch in "}]":
                depth -= 1

        if in_string:
            return True
        if depth != 0:
            return True
        return not text.rstrip().endswith(("}", "]"))

    def recover_partial(self, text: str) -> Tuple[Optional[Dict[str, Any]], int]:
        """
        부분 잘림 복구 시도.

        마지막 완전한 question 객체까지만 추출.

        "questions" 배열 시작 위치부터 문자열/이스케이프를 인식하는 스캐너로
        중첩 깊이가 배열 원소 최상위(깊이 1)로 돌아오는 지점마다 완전한
        question 객체 하나가 끝난 것으로 보고 개별적으로 재파싱한다.

        Args:
            text: 불완전한 JSON 텍스트

        Returns:
            Tuple[Dict|None, int]: (복구된 데이터, 복구된 문제 수), 또는 (None, 0)
        """
        marker = '"questions"'
        idx = text.find(marker)
        if idx == -1:
            return None, 0
        bracket_start = text.find("[", idx)
        if bracket_start == -1:
            return None, 0

        objects: List[str] = []
        depth = 0
        in_string = False
        escape = False
        obj_start: Optional[int] = None

        i = bracket_start + 1
        n = len(text)
        while i < n:
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                i += 1
                continue

            if ch == '"':
                in_string = True
            elif ch == "{":
                if depth == 0:
                    obj_start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and obj_start is not None:
                    objects.append(text[obj_start:i + 1])
                    obj_start = None
            elif ch == "]" and depth == 0:
                break
            i += 1

        recovered_questions: List[Dict[str, Any]] = []
        for obj_str in objects:
            try:
                recovered_questions.append(json.loads(obj_str))
            except json.JSONDecodeError:
                continue

        if not recovered_questions:
            return None, 0

        self.logger.warning(
            "출력 잘림으로 인해 %d개 문제만 부분 복구됨 (원본 objects: %d개)",
            len(recovered_questions), len(objects),
        )
        return {"questions": recovered_questions}, len(recovered_questions)
