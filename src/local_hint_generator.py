"""
로컬 힌트 생성

PDF 구조 분석 결과를 Claude 프롬프트에 제공할 힌트로 변환.
문제 번호 형식, 선지 기호, 페이지 정보 등을 JSON으로 인코딩.
"""

from typing import Dict, List, Any
import json


class LocalHintGenerator:
    """
    청크별 로컬 힌트 생성.

    Claude에게 PDF 구조 정보를 제공하여 변환 정확도 향상.
    """

    def generate_hint(
        self,
        chunk_text: str,
        patterns: List[Dict[str, Any]],
        option_symbols: str,
        metrics: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        청크별 힌트 생성.

        Args:
            chunk_text: 청크 텍스트
            patterns: PDF에서 감지된 문제 번호 패턴
            option_symbols: 선지 기호 유형 ("circled" | "korean" | "numeric")
            metrics: TextMetrics.measure() 결과

        Returns:
            Dict: 구조 힌트 JSON
                {
                    'question_range': {'start': 1, 'end': 10},
                    'question_pattern': '문{N}.',
                    'option_symbols': 'circled',
                    'options_per_question': 5,
                    'has_explanation': True,
                    'explanation_marker': '[해설]',
                    'special_blocks': [
                        {'type': 'table', 'location': 'question_3'},
                        {'type': 'multi_page', 'location': 'question_7'}
                    ],
                    'text_metrics': {
                        'broken_char_ratio': 0.02,
                        'avg_line_length': 45,
                        'total_chars': 3500
                    }
                }
        """
        pass

    def save_hint(self, hint: Dict[str, Any], output_path: str) -> None:
        """
        힌트를 JSON 파일로 저장.

        Args:
            hint: 생성된 힌트
            output_path: 저장 경로 (chunks/hints/chunk_NNN_hint.json)
        """
        pass

    def load_hint(self, input_path: str) -> Dict[str, Any]:
        """
        저장된 힌트 파일 로드.

        Args:
            input_path: 힌트 파일 경로

        Returns:
            Dict: 로드된 힌트
        """
        pass

    def _detect_question_range(self, patterns: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        문제 번호 범위 추출.

        Args:
            patterns: 문제 패턴 리스트

        Returns:
            Dict: {'start': 1, 'end': 10}
        """
        pass

    def _detect_explanation_marker(self, chunk_text: str) -> str:
        """
        해설 구분자 감지.

        "[해설]", "[답]", "답:", "해설:" 등 다양한 형식 감지.

        Args:
            chunk_text: 청크 텍스트

        Returns:
            str: 감지된 마커 (없으면 "")
        """
        pass

    def _detect_special_blocks(self, chunk_text: str) -> List[Dict[str, str]]:
        """
        특이 구조 블록 감지 (표, 그림, 다중 페이지 등).

        Args:
            chunk_text: 청크 텍스트

        Returns:
            List[Dict]: 특이 블록 목록
                [
                    {'type': 'table', 'location': 'question_3'},
                    {'type': 'multi_page', 'location': 'question_7'}
                ]
        """
        pass
