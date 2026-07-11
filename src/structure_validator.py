"""
구조 검증 (Phase 3)

Claude 변환 결과의 구조적 무결성 검증.
"""

from typing import List, Dict, Any
from dataclasses import dataclass


@dataclass
class ValidationIssue:
    """검증 이슈."""
    issue_type: str  # MISSING_QUESTION | OPTION_COUNT_INCONSISTENT | ...
    severity: str    # ERROR | WARNING
    detail: str      # 상세 설명
    question_id: int  # 해당 문제 번호 (선택적)
    location: str    # 경로 (예: "questions[4]")


class StructureValidator:
    """
    변환 결과의 구조적 무결성 검증.
    """

    def __init__(self, logger=None):
        """
        초기화.

        Args:
            logger: 로거 인스턴스 (선택적)
        """
        pass

    def validate(
        self,
        chunk_data: Dict[str, Any],
        hint: Dict[str, Any]
    ) -> List[ValidationIssue]:
        """
        구조 검증 수행.

        검증 항목:
        1. 문제번호 연속성 (1,2,3... 빠짐 없이)
        2. 선지 개수 일관성 (모든 문제가 동일한 개수)
        3. 해설 존재 여부 (있어야 할 곳에 있는지)
        4. "동일" 처리 누락 (첫 선지에만 전체 텍스트, 2~5번째는 "동일")
        5. 정오표 유효성 (true/false만, 다른 값 없음)
        6. 빈 필드 검출 (text/num 필수)

        Args:
            chunk_data: Claude 파싱 결과 (questions 리스트 포함)
            hint: LocalHintGenerator 결과 (expected_options_per_question 등)

        Returns:
            List[ValidationIssue]: 발견된 이슈 목록 (빈 리스트 = 통과)
        """
        pass

    def _check_question_continuity(
        self,
        questions: List[Dict[str, Any]]
    ) -> List[ValidationIssue]:
        """
        문제 번호 연속성 검사.

        Args:
            questions: 문제 리스트

        Returns:
            List[ValidationIssue]: 이슈 목록
        """
        pass

    def _check_option_count_consistency(
        self,
        questions: List[Dict[str, Any]],
        expected_count: int
    ) -> List[ValidationIssue]:
        """
        선지 개수 일관성 검사.

        Args:
            questions: 문제 리스트
            expected_count: 예상 선지 개수

        Returns:
            List[ValidationIssue]: 이슈 목록
        """
        pass

    def _check_text_duplication(
        self,
        questions: List[Dict[str, Any]]
    ) -> List[ValidationIssue]:
        """
        "동일" 처리 누락 검사.

        Args:
            questions: 문제 리스트

        Returns:
            List[ValidationIssue]: 이슈 목록
        """
        pass

    def _check_correct_field(
        self,
        questions: List[Dict[str, Any]]
    ) -> List[ValidationIssue]:
        """
        correct 필드 유효성 검사 (true/false만).

        Args:
            questions: 문제 리스트

        Returns:
            List[ValidationIssue]: 이슈 목록
        """
        pass

    def _check_empty_fields(
        self,
        questions: List[Dict[str, Any]]
    ) -> List[ValidationIssue]:
        """
        빈 필드 검출.

        Args:
            questions: 문제 리스트

        Returns:
            List[ValidationIssue]: 이슈 목록
        """
        pass
