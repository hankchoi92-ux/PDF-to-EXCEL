"""
로컬 힌트 생성

PDF 구조 분석 결과를 Claude 프롬프트에 제공할 힌트로 변환한다.
문제 번호 형식, 선지 기호, 페이지 정보 등을 JSON으로 인코딩.

호출 계약: patterns 인자는 "이 청크에 포함된" 문제 패턴만 전달되어야
한다(전체 문서 패턴이 아님) — chunk_manager가 만든 청크의 question_range에
해당하는 부분집합을 caller가 필터링해서 넘긴다.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from exceptions import HintGenerationError
from schemas import HintData, OptionSymbolType

# 해설 구분자 후보 (우선순위 순)
_EXPLANATION_MARKERS = ["[해설]", "[정답]", "[답]", "해설:", "정답:", "답:"]

# 표 구조 의심 패턴 (파이프/탭 구분자가 여러 줄 반복).
# pdf_extractor.py에도 동일 상수가 있으나, 단방향 의존성(전처리 내부에서도
# fitz에 의존하는 pdf_extractor를 힌트 생성기가 임포트하지 않도록) 원칙에
# 따라 의도적으로 중복 정의한다 - 둘 다 순수 정규식이라 유지 비용이 낮다.
_TABLE_LINE_RE = re.compile(r"(?m)^.*(?:\||\t).*(?:\||\t).*$")

# 줄 시작 위치에서만 매칭 - "[해설] 정답은 ④." 처럼 해설 문장 중간에
# 정답 번호가 다시 언급되는 경우를 선지로 잘못 세지 않기 위함
# (detect_option_symbols의 전체 유형 판별용 정규식과 달리, 여기서는
# 문제당 선지 "개수"를 정확히 세야 하므로 더 엄격한 앵커링이 필요하다).
_OPTION_COUNT_REGEX: Dict[str, str] = {
    OptionSymbolType.CIRCLED.value: r"(?m)^[ \t]*[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮][ \t]",
    OptionSymbolType.KOREAN.value: r"(?m)^[ \t]*[ㄱㄴㄷㄹㅁ][ \t]*[.)]",
    OptionSymbolType.NUMERIC.value: r"(?m)^[ \t]*[1-5][ \t]*[.)][ \t]",
}

# 기호 유형을 알 수 없을 때 기본 선지 수 (법학 객관식 표준 5지선다 가정)
_DEFAULT_OPTIONS_PER_QUESTION = 5


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
            patterns: 이 청크에 포함된 문제 번호 패턴 (question_id, page, format 포함)
            option_symbols: 선지 기호 유형 ("circled" | "korean" | "numeric" | "unknown")
            metrics: TextMetrics.measure() 결과

        Returns:
            Dict: 구조 힌트 (HintData.to_dict() 형식)
                {
                    'question_range': {'start': 1, 'end': 10},
                    'question_pattern': '문{N}.',
                    'option_symbols': 'circled',
                    'options_per_question': 5,
                    'has_explanation': True,
                    'explanation_marker': '[해설]',
                    'special_blocks': [...],
                    'text_metrics': {...},
                    'pages': [0, 1],
                }
        """
        if patterns:
            ids = [p["question_id"] for p in patterns]
            question_range = {"start": min(ids), "end": max(ids)}
            question_pattern = patterns[0].get("format", "unknown")
            pages = sorted({p.get("page", 0) for p in patterns})
        else:
            question_range = {"start": 0, "end": 0}
            question_pattern = "unknown"
            pages = []

        explanation_marker = self._detect_explanation_marker(chunk_text)
        has_explanation = bool(explanation_marker)
        question_count = len(patterns) if patterns else 0
        options_per_question = self._count_options_per_question(
            chunk_text, option_symbols, question_count
        )

        special_blocks = self._detect_special_blocks(chunk_text)
        if len(pages) > 1:
            special_blocks.append({
                "type": "multi_page",
                "location": f"questions_{question_range['start']}-{question_range['end']}",
            })

        hint = HintData(
            question_range=question_range,
            question_pattern=question_pattern,
            option_symbols=option_symbols,
            options_per_question=options_per_question,
            has_explanation=has_explanation,
            explanation_marker=explanation_marker,
            special_blocks=special_blocks,
            text_metrics=dict(metrics or {}),
            pages=pages,
        )
        return hint.to_dict()

    def save_hint(self, hint: Dict[str, Any], output_path: str) -> None:
        """
        힌트를 JSON 파일로 저장 (v6 경로: chunks/hints/chunk_NNN_hint.json).

        Args:
            hint: 생성된 힌트
            output_path: 저장 경로

        Raises:
            HintGenerationError: 저장 실패
        """
        try:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(hint, f, ensure_ascii=False, indent=2)
        except OSError as e:
            raise HintGenerationError(f"힌트 저장 실패: {output_path} ({e})") from e

    def load_hint(self, input_path: str) -> Dict[str, Any]:
        """
        저장된 힌트 파일 로드.

        Args:
            input_path: 힌트 파일 경로

        Returns:
            Dict: 로드된 힌트

        Raises:
            HintGenerationError: 로드 실패
        """
        try:
            with open(input_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            raise HintGenerationError(f"힌트 로드 실패: {input_path} ({e})") from e

    def _detect_question_range(self, patterns: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        문제 번호 범위 추출.

        Args:
            patterns: 문제 패턴 리스트

        Returns:
            Dict: {'start': 1, 'end': 10} (patterns가 비면 {'start':0,'end':0})
        """
        if not patterns:
            return {"start": 0, "end": 0}
        ids = [p["question_id"] for p in patterns]
        return {"start": min(ids), "end": max(ids)}

    def _detect_explanation_marker(self, chunk_text: str) -> str:
        """
        해설 구분자 감지.

        "[해설]", "[답]", "답:", "해설:" 등 다양한 형식을 우선순위대로 탐색.

        Args:
            chunk_text: 청크 텍스트

        Returns:
            str: 감지된 마커 (없으면 "")
        """
        for marker in _EXPLANATION_MARKERS:
            if marker in chunk_text:
                return marker
        return ""

    def _detect_special_blocks(self, chunk_text: str) -> List[Dict[str, str]]:
        """
        특이 구조 블록 감지 (표 등, 텍스트만으로 판별 가능한 것).

        페이지 분할(multi_page)은 patterns의 page 정보가 필요해
        generate_hint()에서 별도로 병합한다.

        Args:
            chunk_text: 청크 텍스트

        Returns:
            List[Dict]: 특이 블록 목록 (예: [{'type': 'table', 'location': 'chunk'}])
        """
        if len(_TABLE_LINE_RE.findall(chunk_text)) >= 2:
            return [{"type": "table", "location": "chunk"}]
        return []

    def _count_options_per_question(
        self, chunk_text: str, option_symbols: str, question_count: int
    ) -> int:
        """
        청크 내 선지 기호 총 출현 횟수를 문제 수로 나눠 문제당 평균 선지 수 추정.

        기호 유형을 알 수 없으면 법학 객관식 표준인 5지선다를 기본값으로 사용.

        Args:
            chunk_text: 청크 텍스트
            option_symbols: 선지 기호 유형
            question_count: 청크 내 문제 개수

        Returns:
            int: 문제당 선지 수 (최소 1)
        """
        if question_count <= 0:
            return 0
        regex = _OPTION_COUNT_REGEX.get(option_symbols)
        if not regex:
            return _DEFAULT_OPTIONS_PER_QUESTION
        count = len(re.findall(regex, chunk_text))
        if count == 0:
            return _DEFAULT_OPTIONS_PER_QUESTION
        return max(1, round(count / question_count))
