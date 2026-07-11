"""
Diff 검증 (Phase 3)

원본 텍스트 vs Claude 변환 결과 비교.
선지 누락, 텍스트 변형 감지.
"""

from typing import List, Dict, Any
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass
class DiffIssue:
    """Diff 검증 이슈."""
    issue_type: str  # OPTION_MISSING | TEXT_SIMILARITY_LOW | ...
    question_id: int
    severity: str    # ERROR | WARNING
    detail: str
    option_num: str  # 해당 선지 번호 (선택적)
    similarity: float  # 유사도 점수


class DiffValidator:
    """
    원본-결과 Diff 분석.
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
        original_text: str,
        claude_output: Dict[str, Any]
    ) -> List[DiffIssue]:
        """
        원본-결과 Diff 분석.

        검증 항목:
        1. 원본 선지 개수 vs 결과 선지 개수
        2. 선지 텍스트 길이 급격한 변화 (삭제 의심)
        3. 원본에 있는데 결과에 없는 주요 키워드
        4. 유사도 임계값 이하 선지 (변형 의심)

        알고리즘:
        - SequenceMatcher 기반 유사도
        - 편집 거리(Levenshtein 근사)

        Args:
            original_text: 원본 청크 텍스트
            claude_output: Claude JSON 파싱 결과

        Returns:
            List[DiffIssue]: 발견된 이슈 목록
        """
        pass

    def calculate_similarity(self, text1: str, text2: str) -> float:
        """
        SequenceMatcher 기반 유사도 계산.

        Args:
            text1: 원본 텍스트
            text2: 비교 텍스트

        Returns:
            float: 유사도 (0.0~1.0)
        """
        pass

    def detect_missing_options(
        self,
        original: str,
        result: Dict[str, Any]
    ) -> List[DiffIssue]:
        """
        원본 대비 누락된 선지 감지.

        Args:
            original: 원본 텍스트
            result: Claude 결과 (questions 포함)

        Returns:
            List[DiffIssue]: 누락 의심 이슈 목록
        """
        pass

    def detect_keyword_loss(
        self,
        original: str,
        result: Dict[str, Any]
    ) -> List[DiffIssue]:
        """
        주요 키워드 손실 감지.

        3자 이상의 단어가 원본에는 있는데 결과에 없는 경우.

        Args:
            original: 원본 텍스트
            result: Claude 결과

        Returns:
            List[DiffIssue]: 키워드 손실 이슈 목록
        """
        pass

    def detect_length_anomalies(
        self,
        result: Dict[str, Any]
    ) -> List[DiffIssue]:
        """
        선지 텍스트 길이의 급격한 변화 감지.

        같은 문제의 모든 선지는 비슷한 길이를 가져야 함.

        Args:
            result: Claude 결과

        Returns:
            List[DiffIssue]: 길이 이상 이슈 목록
        """
        pass
