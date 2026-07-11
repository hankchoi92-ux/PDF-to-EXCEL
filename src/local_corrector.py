"""
로컬 보정 (사전 기반 1차/2차 보정)

법률 용어 사전 기반 명백한 오타만 수정.
Claude 변환 전후에 각각 1회씩 수행.
"""

import json
from pathlib import Path
from typing import Dict, List, Tuple, Any


class LocalCorrector:
    """
    사전 기반 로컬 보정.

    과도한 보정 금지 (확실하지 않으면 원본 유지).
    """

    def __init__(self, dictionary_path: str, config: Dict[str, Any] = None):
        """
        초기화 및 사전 로드.

        Args:
            dictionary_path: legal_terms.json 경로
            config: config.yaml 로드 결과 (선택적)

        Raises:
            FileNotFoundError: 사전 파일 없음
            json.JSONDecodeError: 사전 형식 오류
        """
        pass

    def load_dictionary(self, path: str) -> Dict[str, Any]:
        """
        법률 용어 사전 로드.

        형식:
        {
            "정확한용어": {
                "patterns": ["자주틀리는패턴1", "패턴2"],
                "category": "민법총칙",
                ...
            }
        }

        Args:
            path: 사전 파일 경로

        Returns:
            Dict: 파싱된 사전

        Raises:
            FileNotFoundError: 파일 없음
            json.JSONDecodeError: JSON 형식 오류
        """
        pass

    def pre_correct(self, text: str) -> Tuple[str, List[Dict[str, str]]]:
        """
        Claude 전송 전 1차 보정 (Phase 1 후).

        사전에 있는 명백한 패턴만 수정.
        확실하지 않으면 원본 유지.
        수정 내역 로깅.

        Args:
            text: 원본 텍스트

        Returns:
            Tuple[str, List]: (보정된 텍스트, 수정 목록)
                - 수정 목록: [
                    {
                        'original': '게약',
                        'corrected': '계약',
                        'location': 'line 5, col 10',
                        'confidence': 'high'
                    }
                ]
        """
        pass

    def post_verify(self, parsed_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Claude 응답 후 2차 검증 (Phase 2 후).

        JSON 내 텍스트에서 법률 용어 추출.
        사전과 불일치하는 용어 검출.
        의심 항목 플래깅.

        Args:
            parsed_data: Claude JSON 응답 파싱 결과
                {
                    'questions': [
                        {
                            'id': 1,
                            'text': '...',
                            'options': [...]
                        }
                    ]
                }

        Returns:
            List[Dict]: 의심 항목 목록
                [{
                    'question_id': 3,
                    'field': 'option_text',
                    'found': '게약',
                    'expected_candidates': ['계약'],
                    'severity': 'high'  # high | medium | low
                }, ...]
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

    def _find_correction_candidates(self, term: str) -> List[str]:
        """
        용어에 대한 교정 후보 찾기.

        Args:
            term: 찾을 용어

        Returns:
            List[str]: 교정 후보 목록 (없으면 [])
        """
        pass

    def _is_obvious_typo(self, original: str, expected: str) -> bool:
        """
        명백한 오타인지 판단.

        자신감 기준:
        - 오자가 1자리만 → True
        - 자음/모음 혼동만 → True
        - 길이 차이 3자리 이상 → False

        Args:
            original: 원본
            expected: 예상 정정값

        Returns:
            bool: 명백한 오타 여부
        """
        pass
