"""
JSON 응답 파싱 및 검증

Claude JSON 응답 추출, 스키마 검증, 정규화.
"""

import json
import re
from typing import Dict, List, Any, Tuple, Optional
from jsonschema import validate, ValidationError


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

    def __init__(self, logger=None):
        """
        초기화.

        Args:
            logger: 로거 인스턴스 (선택적)
        """
        pass

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
        pass

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
        pass

    def validate_schema(self, data: Dict[str, Any]) -> List[str]:
        """
        JSON 스키마 검증.

        Args:
            data: 파싱된 JSON 데이터

        Returns:
            List[str]: 오류 목록 (빈 리스트 = 통과)
        """
        pass

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
        pass

    def detect_truncation(self, text: str) -> bool:
        """
        출력 잘림 감지.

        마지막 `}` 누락, 닫히지 않은 배열/객체 감지.

        Args:
            text: JSON 텍스트

        Returns:
            bool: 잘림 여부
        """
        pass

    def recover_partial(self, text: str) -> Tuple[Optional[Dict[str, Any]], int]:
        """
        부분 잘림 복구 시도.

        마지막 완전한 question 객체까지만 추출.

        Args:
            text: 불완전한 JSON 텍스트

        Returns:
            Tuple[Dict|None, int]: (복구된 데이터, 복구된 문제 수), 또는 (None, 0)
        """
        pass
