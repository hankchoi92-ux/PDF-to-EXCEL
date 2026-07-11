"""
PDF 텍스트 추출 (PyMuPDF)

PDF에서 텍스트, 좌표, 레이아웃 정보 추출.
문제 번호/선지 기호 패턴 감지.
"""

import fitz  # PyMuPDF
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
import re


class PDFTextExtractor:
    """
    PyMuPDF 기반 PDF 텍스트 추출.
    """

    def __init__(self, pdf_path: str):
        """
        초기화.

        Args:
            pdf_path: PDF 파일 경로

        Raises:
            FileNotFoundError: PDF 파일 없음
            RuntimeError: PDF 손상
        """
        pass

    def extract_full_text(self) -> str:
        """
        전체 PDF 텍스트 추출.

        Returns:
            str: 전체 텍스트 (페이지 구분자 포함)
        """
        pass

    def extract_text_with_positions(self) -> List[Dict[str, Any]]:
        """
        블록별 텍스트 + 좌표 정보 추출.

        각 텍스트 블록의 위치(bbox), 폰트 크기 등 메타데이터 포함.
        로컬 힌트 생성 및 페이지별 구조 분석에 활용.

        Returns:
            List[Dict]: 텍스트 블록 목록
                [{
                    'page': 1,
                    'text': '문1. 계약의 성립요건...',
                    'bbox': (x1, y1, x2, y2),
                    'font_size': 10.5,
                    'block_id': 12
                }, ...]
        """
        pass

    def detect_question_patterns(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        문제 번호 패턴 감지.

        "문1.", "문 1.", "1.", "(1)", "①" 등 다양한 형식 감지.
        페이지별 문제 번호 매핑.

        Args:
            blocks: extract_text_with_positions() 결과

        Returns:
            List[Dict]: 감지된 문제 패턴
                [{
                    'format': '문{N}.',
                    'question_id': 1,
                    'page': 1,
                    'text': '문1. ...',
                }, ...]
        """
        pass

    def detect_option_symbols(self, blocks: List[Dict[str, Any]]) -> str:
        """
        선지 기호 유형 감지.

        ①②③④⑤ (circled)
        ㄱㄴㄷㄹㅁ (korean)
        1.2.3.4.5 (numeric)

        Args:
            blocks: extract_text_with_positions() 결과

        Returns:
            str: 감지된 기호 유형 ("circled" | "korean" | "numeric")
        """
        pass

    def extract_reference_image(self, page_num: int, dpi: int = 100) -> bytes:
        """
        참고용 저해상도 이미지 추출.

        청크당 첫 페이지 이미지를 PNG로 추출.
        Claude 프롬프트에서 참고 이미지로 사용 (선택적).

        Args:
            page_num: 페이지 번호 (0-indexed)
            dpi: 해상도 (기본 100)

        Returns:
            bytes: PNG 이미지 바이너리

        Raises:
            ValueError: 페이지 범위 초과
        """
        pass

    def get_page_count(self) -> int:
        """
        총 페이지 수 반환.

        Returns:
            int: 페이지 수
        """
        pass

    def close(self) -> None:
        """리소스 정리."""
        pass
