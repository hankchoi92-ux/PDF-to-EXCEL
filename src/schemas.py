"""
공유 데이터 스키마 (Phase 1 전처리 파이프라인)

pdf_extractor → chunk_manager → local_hint_generator → local_corrector 로
이어지는 단방향 데이터 흐름에서 모듈 간 전달되는 데이터를 dataclass로
명시해 필드 누락/오타로 인한 무결성 손상을 방지한다.

각 dataclass는 to_dict()를 제공해 JSON 직렬화(청크/힌트 파일 저장) 시
일관된 형식으로 변환할 수 있게 한다.
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class OptionSymbolType(str, Enum):
    """선지 기호 유형."""
    CIRCLED = "circled"    # ①②③④⑤
    KOREAN = "korean"      # ㄱㄴㄷㄹㅁ
    NUMERIC = "numeric"    # 1) 2) 3) 또는 1. 2. 3.
    UNKNOWN = "unknown"    # 감지 실패


@dataclass
class TextBlock:
    """
    PDF에서 추출한 텍스트 블록 1개.

    char_start/char_end는 PDFTextExtractor.extract_full_text()가
    블록들을 이어붙였을 때의 전체 텍스트 내 오프셋(문자 인덱스).
    문제 패턴 감지 결과를 원본 페이지로 역매핑하는 데 사용된다.
    """
    page: int                              # 0-indexed 페이지 번호
    text: str
    bbox: Tuple[float, float, float, float]  # (x1, y1, x2, y2)
    font_size: float
    block_id: int
    char_start: int = 0
    char_end: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class QuestionPattern:
    """
    감지된 문제 번호 1건.

    char_start/char_end는 전체 텍스트(extract_full_text 결과) 기준 오프셋.
    """
    question_id: int
    format: str                # 예: '문{N}.', '{N}.'
    page: int                  # 문제 헤더가 위치한 페이지
    text: str                  # 헤더 원문 (예: "문1.")
    char_start: int
    char_end: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SpecialBlock:
    """청크 내 특이 구조 (표, 페이지 분할 등)."""
    block_type: str            # table | multi_page | image_only | ...
    location: str              # 예: "question_3"

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


@dataclass
class TextMetricsData:
    """TextMetrics.measure() 결과 (객관적 지표만, 품질 평가 없음)."""
    broken_char_ratio: float = 0.0
    excessive_space_ratio: float = 0.0
    mixed_encoding_ratio: float = 0.0
    avg_line_length: float = 0.0
    empty_lines_ratio: float = 0.0
    total_chars: int = 0
    unique_chars: int = 0
    hangul_ratio: float = 0.0
    digit_ratio: float = 0.0
    special_char_ratio: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ChunkData:
    """
    ChunkManager.create_chunks()가 생성하는 청크 1개.

    문제 경계를 넘지 않도록 조정되며, pages는 해당 청크가 걸쳐 있는
    원본 PDF 페이지 목록(참고 이미지 추출/디버깅용)이다.
    """
    chunk_id: str
    question_range: Tuple[int, int]        # (시작 문제번호, 끝 문제번호)
    text: str
    estimated_tokens: int
    pages: List[int] = field(default_factory=list)
    question_count: int = 0
    start_char: int = 0
    end_char: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["question_range"] = list(self.question_range)
        return d


@dataclass
class HintData:
    """LocalHintGenerator.generate_hint() 결과 (Claude 프롬프트에 삽입)."""
    question_range: Dict[str, int]
    question_pattern: str
    option_symbols: str
    options_per_question: int
    has_explanation: bool
    explanation_marker: str
    special_blocks: List[Dict[str, str]] = field(default_factory=list)
    text_metrics: Dict[str, Any] = field(default_factory=dict)
    pages: List[int] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CorrectionRecord:
    """
    LocalCorrector가 사전 기반으로 수행한 단일 교정 이력.

    logs/corrections/ 하위에 청크별로 누적 기록되어, 어떤 용어가
    어디서 무엇으로 왜 바뀌었는지 사후 추적 가능하게 한다.
    """
    chunk_id: str
    original: str
    corrected: str
    canonical_term: str        # 사전상 정확한 용어 (예: "계약")
    location: str              # 원문 내 위치 설명 (예: "offset 120-122")
    confidence: str            # high | medium
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
