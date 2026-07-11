"""
텍스트 지표 측정 (객관적만)

품질 '평가'가 아닌 객관적 '측정'만 수행한다.
OCR/추출 상태를 Claude 프롬프트에 정보로 제공하는 용도이며,
여기서 "품질 점수"를 만들어 판단을 대신하지 않는다(그 역할은 검증
모듈(structure/diff/term validator)과 confidence_scorer가 담당).
"""

import re
from typing import Dict

from schemas import TextMetricsData

# 스캔/OCR 실패 시 흔히 등장하는 대체(placeholder) 문자
_BROKEN_CHARS = set("□■○●◆▲△▽◇☆★�")

# 영한 혼합 감지: 한글 음절과 라틴 문자가 같은 토큰(공백 없는 연속 문자열)에
# 함께 나타나는 경우 (숫자/기호가 섞인 것은 정상 표기이므로 대상 아님)
_HANGUL_RE = re.compile(r"[가-힣]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_DIGIT_RE = re.compile(r"[0-9]")
_TOKEN_RE = re.compile(r"\S+")


class TextMetrics:
    """
    객관적 텍스트 지표 측정.

    의도적으로 품질 점수는 제공하지 않는다.
    """

    def measure(self, text: str) -> Dict[str, object]:
        """
        객관적 텍스트 지표 측정.

        Args:
            text: 측정할 텍스트

        Returns:
            Dict: 측정 결과 (TextMetricsData.to_dict() 형식)
                {
                    'broken_char_ratio': 0.03,
                    'excessive_space_ratio': 0.05,
                    'mixed_encoding_ratio': 0.01,
                    'avg_line_length': 42.0,
                    'empty_lines_ratio': 0.15,
                    'total_chars': 3580,
                    'unique_chars': 890,
                    'hangul_ratio': 0.70,
                    'digit_ratio': 0.05,
                    'special_char_ratio': 0.10
                }
        """
        total_chars = len(text)
        if total_chars == 0:
            return TextMetricsData().to_dict()

        avg_line_length, empty_lines_ratio = self._calculate_line_stats(text)
        char_ratios = self._character_ratios(text)

        data = TextMetricsData(
            broken_char_ratio=self._count_broken_chars(text),
            excessive_space_ratio=self._count_excessive_spaces(text),
            mixed_encoding_ratio=self._detect_mixed_encoding(text),
            avg_line_length=avg_line_length,
            empty_lines_ratio=empty_lines_ratio,
            total_chars=total_chars,
            unique_chars=len(set(text)),
            hangul_ratio=char_ratios["hangul_ratio"],
            digit_ratio=char_ratios["digit_ratio"],
            special_char_ratio=char_ratios["special_char_ratio"],
        )
        return data.to_dict()

    def _count_broken_chars(self, text: str) -> float:
        """
        깨진 문자(□■○●◆▲△▽◇☆★, U+FFFD) 비율 계산.

        Args:
            text: 텍스트

        Returns:
            float: 비율 (0.0~1.0)
        """
        if not text:
            return 0.0
        count = sum(1 for ch in text if ch in _BROKEN_CHARS)
        return round(count / len(text), 4)

    def _count_excessive_spaces(self, text: str) -> float:
        """
        과도한 공백(연속 2개 이상) 비율 계산.

        공백 런(run)에 속한 문자 수 / 전체 문자 수로 계산한다.

        Args:
            text: 텍스트

        Returns:
            float: 비율 (0.0~1.0)
        """
        if not text:
            return 0.0
        excessive_chars = sum(len(m.group(0)) for m in re.finditer(r" {2,}", text))
        return round(excessive_chars / len(text), 4)

    def _detect_mixed_encoding(self, text: str) -> float:
        """
        영한 혼합(동일 토큰 내 한글+라틴 문자 공존) 비율 계산.

        예: "계a약" 처럼 OCR이 한글 자소를 라틴 문자로 잘못 인식해 같은
        단어 안에 섞인 경우를 흔한 OCR 오염 신호로 본다.

        Args:
            text: 텍스트

        Returns:
            float: 전체 토큰 대비 혼합 토큰 비율 (0.0~1.0)
        """
        tokens = _TOKEN_RE.findall(text)
        if not tokens:
            return 0.0
        mixed = sum(
            1 for t in tokens if _HANGUL_RE.search(t) and _LATIN_RE.search(t)
        )
        return round(mixed / len(tokens), 4)

    def _calculate_line_stats(self, text: str) -> tuple:
        """
        줄 길이 통계 계산.

        Args:
            text: 텍스트

        Returns:
            Tuple[float, float]: (평균 줄 길이(공백 아닌 줄 기준), 빈 줄 비율)
        """
        lines = text.split("\n")
        if not lines:
            return 0.0, 0.0
        non_empty = [line for line in lines if line.strip()]
        avg_len = round(sum(len(line) for line in non_empty) / len(non_empty), 1) if non_empty else 0.0
        empty_ratio = round((len(lines) - len(non_empty)) / len(lines), 4)
        return avg_len, empty_ratio

    def _character_ratios(self, text: str) -> Dict[str, float]:
        """
        문자 유형별 비율 계산 (한글, 숫자, 특수문자).

        특수문자 = 한글도 숫자도 영문도 공백도 아닌 문자.

        Args:
            text: 텍스트

        Returns:
            Dict: {'hangul_ratio': ..., 'digit_ratio': ..., 'special_char_ratio': ...}
        """
        total = len(text)
        if total == 0:
            return {"hangul_ratio": 0.0, "digit_ratio": 0.0, "special_char_ratio": 0.0}

        hangul = len(_HANGUL_RE.findall(text))
        digit = len(_DIGIT_RE.findall(text))
        latin = len(_LATIN_RE.findall(text))
        whitespace = sum(1 for ch in text if ch.isspace())
        special = total - hangul - digit - latin - whitespace

        return {
            "hangul_ratio": round(hangul / total, 4),
            "digit_ratio": round(digit / total, 4),
            "special_char_ratio": round(max(special, 0) / total, 4),
        }
