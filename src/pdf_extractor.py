"""
PDF 텍스트 추출 (PyMuPDF)

PDF에서 텍스트, 좌표, 레이아웃 정보 추출.
문제 번호/선지 기호 패턴 감지.

단방향 의존 원칙: 이 모듈은 chunk_manager/local_hint_generator 등
하위 단계를 import하지 않는다 (전처리 → 클라이언트 → 검증 → 생성).
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF

from exceptions import (
    PageRangeError,
    PDFCorruptedError,
    PDFEmptyError,
    PDFEncryptedError,
    PDFNotFoundError,
)
from schemas import OptionSymbolType

# 문제 번호 패턴 후보 (우선순위 순). 그룹 1은 반드시 숫자를 캡처해야 함.
# 정규식은 줄 시작(^, MULTILINE)에서만 매칭해 본문 중간의 우연한 숫자를 배제한다.
QUESTION_PATTERNS: List[Tuple[str, str, str]] = [
    ("question_dot", r"(?m)^[ \t]*문[ \t]?(\d{1,3})[ \t]*[.)][ \t]+", "문{N}."),
    ("bracket", r"(?m)^[ \t]*【[ \t]*(\d{1,3})[ \t]*】[ \t]*", "【{N}】"),
    ("paren", r"(?m)^[ \t]*\([ \t]*(\d{1,3})[ \t]*\)[ \t]+", "({N})"),
    ("bare_dot", r"(?m)^[ \t]*(\d{1,3})[ \t]*\.[ \t]+", "{N}."),
]

# 선지 기호 감지용 정규식
_OPTION_REGEX: Dict[str, str] = {
    OptionSymbolType.CIRCLED.value: r"[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮]",
    OptionSymbolType.KOREAN.value: r"(?m)^[ \t]*[ㄱㄴㄷㄹㅁ][ \t]*[.)]",
    OptionSymbolType.NUMERIC.value: r"(?m)^[ \t]*[1-5][ \t]*[.)][ \t]",
}


class PDFTextExtractor:
    """
    PyMuPDF 기반 PDF 텍스트 추출.

    블록 추출 결과와 전체 텍스트는 최초 호출 시 캐시되며,
    detect_question_patterns / detect_option_symbols는 캐시와 무관하게
    전달받은 blocks 인자만으로 순수하게 동작한다(테스트 용이성 확보).
    """

    def __init__(self, pdf_path: str):
        """
        초기화.

        Args:
            pdf_path: PDF 파일 경로

        Raises:
            PDFNotFoundError: 파일 없음
            PDFCorruptedError: PDF 손상 또는 페이지 0개
            PDFEncryptedError: 암호화되어 있고 빈 비밀번호로 해제 불가
        """
        self.pdf_path = Path(pdf_path)
        if not self.pdf_path.exists():
            raise PDFNotFoundError(f"PDF 파일을 찾을 수 없습니다: {self.pdf_path}")

        try:
            self.doc = fitz.open(str(self.pdf_path))
        except Exception as e:  # PyMuPDF는 다양한 예외를 던짐 (경계에서 통합 처리)
            raise PDFCorruptedError(
                f"PDF를 열 수 없습니다 (손상 의심): {self.pdf_path} ({e})"
            ) from e

        if self.doc.is_encrypted:
            if not self.doc.authenticate(""):
                self.doc.close()
                raise PDFEncryptedError(
                    f"PDF가 암호화되어 있어 열 수 없습니다: {self.pdf_path}"
                )

        if self.doc.page_count == 0:
            self.doc.close()
            raise PDFCorruptedError(f"PDF에 페이지가 없습니다: {self.pdf_path}")

        self._blocks_cache: Optional[List[Dict[str, Any]]] = None
        self._full_text_cache: Optional[str] = None

    def __enter__(self) -> "PDFTextExtractor":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # 추출
    # ------------------------------------------------------------------

    def extract_text_with_positions(self) -> List[Dict[str, Any]]:
        """
        블록별 텍스트 + 좌표 정보 추출 (결과는 캐시됨).

        PyMuPDF의 page.get_text("dict")를 사용해 페이지별로 텍스트 블록을
        읽고, 각 블록의 bbox·평균 폰트 크기·페이지 번호를 기록한다.
        이미지 전용 블록(type != 0)은 제외한다.

        Returns:
            List[Dict]: 텍스트 블록 목록 (읽기 순서, char_start/char_end 포함)
                [{
                    'page': 0,
                    'text': '문1. 계약의 성립요건...',
                    'bbox': (x1, y1, x2, y2),
                    'font_size': 10.5,
                    'block_id': 12,
                    'char_start': 0,
                    'char_end': 42,
                }]

        Raises:
            PDFEmptyError: 추출 가능한 텍스트가 전혀 없음
        """
        if self._blocks_cache is not None:
            return self._blocks_cache

        blocks_out: List[Dict[str, Any]] = []
        block_id = 0

        for page_index in range(self.doc.page_count):
            page = self.doc[page_index]
            raw = page.get_text("dict")
            for blk in raw.get("blocks", []):
                if blk.get("type") != 0:  # 0 = 텍스트 블록, 1 = 이미지
                    continue
                lines = blk.get("lines", [])
                if not lines:
                    continue

                line_texts: List[str] = []
                font_sizes: List[float] = []
                for line in lines:
                    spans = line.get("spans", [])
                    line_str = "".join(span.get("text", "") for span in spans)
                    if not line_str.strip():
                        continue
                    line_texts.append(line_str)
                    font_sizes.extend(
                        span.get("size", 0.0) for span in spans
                        if span.get("text", "").strip()
                    )

                text = "\n".join(line_texts).strip()
                if not text:
                    continue

                avg_font = round(sum(font_sizes) / len(font_sizes), 1) if font_sizes else 0.0
                blocks_out.append({
                    "page": page_index,
                    "text": text,
                    "bbox": tuple(blk.get("bbox", (0.0, 0.0, 0.0, 0.0))),
                    "font_size": avg_font,
                    "block_id": block_id,
                })
                block_id += 1

        if not blocks_out:
            raise PDFEmptyError(
                f"PDF에서 추출 가능한 텍스트가 없습니다 (스캔 이미지 전용 PDF일 수 있음): "
                f"{self.pdf_path}"
            )

        full_text, ranges = self._join_blocks(blocks_out)
        for (start, end, _page), block in zip(ranges, blocks_out):
            block["char_start"] = start
            block["char_end"] = end

        self._blocks_cache = blocks_out
        self._full_text_cache = full_text
        return blocks_out

    def extract_full_text(self) -> str:
        """
        전체 PDF 텍스트 추출 (블록을 "\\n\\n"으로 이어붙인 결과, 캐시됨).

        Returns:
            str: 전체 텍스트
        """
        if self._full_text_cache is None:
            self.extract_text_with_positions()
        return self._full_text_cache or ""

    # ------------------------------------------------------------------
    # 패턴 감지
    # ------------------------------------------------------------------

    def detect_question_patterns(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        문제 번호 패턴 감지.

        블록들을 "\\n\\n"으로 이어붙인 텍스트에 QUESTION_PATTERNS를 순서대로
        시도하고, 감지된 번호가 "대체로 증가하는 수열"(오탐 배제 휴리스틱)을
        이루는 패턴 중 매칭 개수가 가장 많은 것을 채택한다.

        Args:
            blocks: extract_text_with_positions() 결과 (또는 동일 구조의 리스트)

        Returns:
            List[Dict]: 감지된 문제 패턴 (char_start 오름차순)
                [{
                    'question_id': 1,
                    'format': '문{N}.',
                    'page': 0,
                    'text': '문1.',
                    'char_start': 120,
                    'char_end': 124,
                }, ...]
                패턴을 하나도 찾지 못하면 빈 리스트.
        """
        if not blocks:
            return []

        full_text, ranges = self._join_blocks(blocks)
        best: Optional[Tuple[int, str, List[re.Match], List[int]]] = None

        for _name, regex, template in QUESTION_PATTERNS:
            matches = list(re.finditer(regex, full_text))
            if len(matches) < 2:
                continue
            numbers = [int(m.group(1)) for m in matches]
            if not self._is_monotonic_sequence(numbers):
                continue
            score = len(matches)
            if best is None or score > best[0]:
                best = (score, template, matches, numbers)

        if best is None:
            return []

        _score, template, matches, numbers = best
        patterns: List[Dict[str, Any]] = []
        for m, qid in zip(matches, numbers):
            char_start, char_end = m.start(), m.end()
            patterns.append({
                "question_id": qid,
                "format": template,
                "page": self._page_for_offset(char_start, ranges),
                "text": m.group(0).strip(),
                "char_start": char_start,
                "char_end": char_end,
            })
        return patterns

    def detect_option_symbols(self, blocks: List[Dict[str, Any]]) -> str:
        """
        선지 기호 유형 감지.

        ①②③④⑤ (circled) / ㄱㄴㄷㄹㅁ (korean) / 1) 2) 3) (numeric) 각각의
        출현 빈도를 세어 가장 많이 나온 유형을 채택한다.

        Args:
            blocks: extract_text_with_positions() 결과

        Returns:
            str: "circled" | "korean" | "numeric" | "unknown"
        """
        if not blocks:
            return OptionSymbolType.UNKNOWN.value

        full_text, _ranges = self._join_blocks(blocks)
        counts = {
            symbol_type: len(re.findall(regex, full_text))
            for symbol_type, regex in _OPTION_REGEX.items()
        }
        best_type, best_count = max(counts.items(), key=lambda kv: kv[1])
        return best_type if best_count > 0 else OptionSymbolType.UNKNOWN.value

    # ------------------------------------------------------------------
    # 이미지 / 메타
    # ------------------------------------------------------------------

    def extract_reference_image(self, page_num: int, dpi: int = 100) -> bytes:
        """
        참고용 저해상도 이미지 추출.

        Args:
            page_num: 페이지 번호 (0-indexed)
            dpi: 해상도 (기본 100)

        Returns:
            bytes: PNG 이미지 바이너리

        Raises:
            PageRangeError: 페이지 범위 초과
        """
        if not (0 <= page_num < self.doc.page_count):
            raise PageRangeError(
                f"페이지 범위 초과: {page_num} (전체 {self.doc.page_count}페이지)"
            )
        page = self.doc[page_num]
        pix = page.get_pixmap(dpi=dpi)
        return pix.tobytes("png")

    def get_page_count(self) -> int:
        """
        총 페이지 수 반환.

        Returns:
            int: 페이지 수
        """
        return self.doc.page_count

    def close(self) -> None:
        """리소스 정리."""
        if getattr(self, "doc", None) is not None:
            self.doc.close()
            self.doc = None

    # ------------------------------------------------------------------
    # 내부 유틸리티
    # ------------------------------------------------------------------

    @staticmethod
    def _join_blocks(
        blocks: List[Dict[str, Any]]
    ) -> Tuple[str, List[Tuple[int, int, int]]]:
        """
        블록 리스트를 "\\n\\n" 구분자로 이어붙여 전체 텍스트와 오프셋 범위를 생성.

        extract_text_with_positions()가 캐시를 만들 때와 detect_question_patterns
        /detect_option_symbols가 순수 함수로 동작할 때 모두 이 메서드를 사용해
        오프셋 계산 방식을 일치시킨다.

        Args:
            blocks: 'text', 'page' 키를 가진 블록 리스트

        Returns:
            Tuple[str, List[Tuple[int,int,int]]]: (전체 텍스트, [(char_start, char_end, page), ...])
        """
        parts: List[str] = []
        ranges: List[Tuple[int, int, int]] = []
        cursor = 0
        for block in blocks:
            text = block.get("text", "")
            page = block.get("page", 0)
            start = cursor
            parts.append(text)
            cursor += len(text)
            ranges.append((start, cursor, page))
            parts.append("\n\n")
            cursor += 2
        return "".join(parts), ranges

    @staticmethod
    def _page_for_offset(offset: int, ranges: List[Tuple[int, int, int]]) -> int:
        """
        전체 텍스트 내 offset이 속한 블록의 페이지 번호를 찾는다.

        offset이 블록 사이 구분자("\\n\\n") 안에 떨어지면 직전 블록의
        페이지를 사용한다 (문제 헤더가 블록 경계 근처에 있을 때의 근사 처리).

        Args:
            offset: 전체 텍스트 내 문자 오프셋
            ranges: _join_blocks()가 반환한 (start, end, page) 목록

        Returns:
            int: 페이지 번호 (0-indexed), ranges가 비어 있으면 0
        """
        if not ranges:
            return 0
        last_page = ranges[0][2]
        for start, end, page in ranges:
            if start <= offset < end:
                return page
            if start <= offset:
                last_page = page
            else:
                break
        return last_page

    @staticmethod
    def _is_monotonic_sequence(numbers: List[int]) -> bool:
        """
        번호 목록이 "대체로 증가하는 수열"인지 판정 (오탐 패턴 배제용 휴리스틱).

        본문 중간에 우연히 나타난 숫자열(예: 조문 번호, 페이지 표기)이
        문제 번호로 오인되는 것을 막기 위해, 연속 쌍의 70% 이상이
        증가해야 하고 첫 번호가 3 이하로 시작해야 한다.

        Args:
            numbers: 감지된 번호 목록 (매칭 순서)

        Returns:
            bool: 문제 번호 수열로 볼 수 있으면 True
        """
        if len(numbers) < 2:
            return False
        increasing_pairs = sum(
            1 for i in range(1, len(numbers)) if numbers[i] > numbers[i - 1]
        )
        ratio = increasing_pairs / (len(numbers) - 1)
        return ratio >= 0.7 and numbers[0] <= 3
