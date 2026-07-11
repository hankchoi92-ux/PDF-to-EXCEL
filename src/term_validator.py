"""
법률 용어 검증 (Phase 3)

Claude 변환 결과의 법률 용어 정확도 검증.
사전 기반 2차 검증.
"""

import json
from pathlib import Path
from typing import List, Dict, Any
from dataclasses import dataclass


@dataclass
class TermIssue:
    """법률 용어 검증 이슈."""
    issue_type: str  # UNKNOWN_TERM | TYPO_NOT_CORRECTED | ...
    severity: str    # ERROR | WARNING | INFO
    term: str        # 해당 용어
    location: str    # 위치 (예: "question_3, option_②")
    suggestion: str  # 제안 (선택적)


class TermValidator:
    """
    법률 용어 정확도 검증.
    """

    def __init__(self, dictionary_path: str, logger=None):
        """
        초기화 및 사전 로드.

        Args:
            dictionary_path: legal_terms.json 경로
            logger: 로거 인스턴스 (선택적)

        Raises:
            FileNotFoundError: 사전 파일 없음
        """
        pass

    def load_dictionary(self, path: str) -> Dict[str, Any]:
        """
        법률 용어 사전 로드.

        Args:
            path: 사전 파일 경로

        Returns:
            Dict: 로드된 사전
        """
        pass

    def verify(self, parsed_data: Dict[str, Any]) -> List[TermIssue]:
        """
        Claude 변환 결과의 법률 용어 검증.

        단계:
        1. questions 배열에서 텍스트 추출 (text, option.text, explanation)
        2. 사전에 있는 정확한 용어 추출
        3. 사전에 없는 용어 플래깅
        4. 오타 패턴과 불일치 감지

        Args:
            parsed_data: Claude JSON 파싱 결과

        Returns:
            List[TermIssue]: 발견된 이슈 목록
        """
        pass

    def _extract_legal_terms(self, text: str) -> List[str]:
        """
        텍스트에서 법률 용어 후보 추출.

        Args:
            text: 텍스트

        Returns:
            List[str]: 추출된 용어 목록
        """
        pass

    def _validate_term(self, term: str) -> tuple:
        """
        단일 용어 검증.

        Args:
            term: 검증할 용어

        Returns:
            Tuple[bool, str, str]: (valid, correction_if_invalid, confidence_level)
                - valid: 사전 정확도
                - correction_if_invalid: 교정 제안 (유효하지 않으면)
                - confidence_level: 제안의 신뢰도
        """
        pass

    def _find_correction(self, term: str) -> tuple:
        """
        용어의 교정 후보 찾기.

        Args:
            term: 용어

        Returns:
            Tuple[str|None, str]: (교정된 용어, 신뢰도)
                - 교정 불가능하면 (None, "low")
        """
        pass
