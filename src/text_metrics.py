"""
텍스트 지표 측정 (객관적만)

품질 '평가'가 아닌 객관적 '측정'만 수행.
OCR 상태를 Claude에 정보로 제공.
"""

from typing import Dict, Any
import re


class TextMetrics:
    """
    객관적 텍스트 지표 측정.

    의도적으로 품질 점수는 제공하지 않음.
    Claude와 검증 모듈이 평가를 담당.
    """

    def measure(self, text: str) -> Dict[str, Any]:
        """
        객관적 텍스트 지표 측정.

        Args:
            text: 측정할 텍스트

        Returns:
            Dict: 측정 결과
                {
                    'broken_char_ratio': 0.03,          # 깨진 문자(□■○●) 비율
                    'excessive_space_ratio': 0.05,      # 과도한 공백 비율
                    'mixed_encoding_ratio': 0.01,       # 영한 혼합 비율
                    'avg_line_length': 42,              # 평균 줄 길이
                    'empty_lines_ratio': 0.15,          # 빈 줄 비율
                    'total_chars': 3580,                # 전체 문자 수
                    'unique_chars': 890,                # 고유 문자 수
                    'hangul_ratio': 0.70,               # 한글 비율
                    'digit_ratio': 0.05,                # 숫자 비율
                    'special_char_ratio': 0.10          # 특수문자 비율
                }
        """
        pass

    def _count_broken_chars(self, text: str) -> float:
        """
        깨진 문자(□■○●) 비율 계산.

        Args:
            text: 텍스트

        Returns:
            float: 비율 (0.0~1.0)
        """
        pass

    def _count_excessive_spaces(self, text: str) -> float:
        """
        과도한 공백(연속 2개 이상) 비율 계산.

        Args:
            text: 텍스트

        Returns:
            float: 비율 (0.0~1.0)
        """
        pass

    def _detect_mixed_encoding(self, text: str) -> float:
        """
        영한 혼합(동일 단어 내) 비율 계산.

        Args:
            text: 텍스트

        Returns:
            float: 비율 (0.0~1.0)
        """
        pass

    def _calculate_line_stats(self, text: str) -> tuple:
        """
        줄 길이 통계 계산.

        Args:
            text: 텍스트

        Returns:
            Tuple[float, float]: (평균 줄 길이, 빈 줄 비율)
        """
        pass

    def _character_ratios(self, text: str) -> Dict[str, float]:
        """
        문자 유형별 비율 계산 (한글, 숫자, 특수문자).

        Args:
            text: 텍스트

        Returns:
            Dict: {'hangul_ratio': ..., 'digit_ratio': ..., ...}
        """
        pass
