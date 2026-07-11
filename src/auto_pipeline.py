"""
자동 파이프라인 (v6 - Phase 0~4 통합 실행)

PDF 입력 → 완전 자동 처리 → Excel 출력

Phase별 담당:
- Phase 0: 프리플라이트 (CLI 설치/인증/인코딩 확인) [preflight.py]
- Phase 1: PDF 전처리 + 동적 청킹 [pdf_extractor.py, chunk_manager.py, ...]
- Phase 2: Claude CLI 서브프로세스 자동 호출 [claude_cli_client.py]
- Phase 3: 검증 + 신뢰도 점수 [structure_validator.py, diff_validator.py, ...]
- Phase 4: Excel 생성 [excel_builder.py]
"""

import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import json

from preflight import Preflight
from state_manager import StateManager
from pdf_extractor import PDFTextExtractor
from local_hint_generator import LocalHintGenerator
from chunk_manager import ChunkManager
from text_metrics import TextMetrics
from local_corrector import LocalCorrector
from claude_cli_client import ClaudeCliClient
from response_parser import ResponseParser
from structure_validator import StructureValidator
from diff_validator import DiffValidator
from term_validator import TermValidator
from confidence_scorer import ConfidenceScorer
from excel_builder import ExcelBuilder


@dataclass
class PipelineResult:
    """파이프라인 실행 결과."""
    success: bool
    phase: str  # PREFLIGHT | PHASE_1 | PHASE_2 | PHASE_3 | PHASE_4
    total_problems: int
    auto_confirmed: int
    human_review: int
    output_files: Dict[str, Path]
    error_summary: Optional[str] = None


class AutoPipeline:
    """
    v6 자동 파이프라인 통합 실행기.

    사용자 개입: PDF 파일 경로만 입력 → 나머지 완전 자동화.
    """

    def __init__(
        self,
        pdf_path: str,
        config: Dict[str, Any],
        logger: logging.Logger
    ):
        """
        초기화.

        Args:
            pdf_path: 입력 PDF 파일 경로
            config: config.yaml 로드 결과
            logger: 로거 인스턴스
        """
        pass

    def run(self) -> PipelineResult:
        """
        Phase 0~4 전체 실행.

        Returns:
            PipelineResult: 파이프라인 실행 결과

        Raises:
            Exception: 각 Phase의 실패 (상세 로깅됨)
        """
        pass

    def _phase_0_preflight(self) -> bool:
        """
        Phase 0: 프리플라이트 검증.

        Claude CLI 설치/인증/인코딩 사전 점검.
        실패 시 즉시 중단 (청크 생성 전 낭비 방지).

        Returns:
            bool: 통과 여부

        Raises:
            RuntimeError: 필수 조건 불만족
        """
        pass

    def _phase_1_preprocess(self) -> List[Dict[str, Any]]:
        """
        Phase 1: PDF 전처리 + 동적 청킹.

        - PyMuPDF로 텍스트 추출
        - 문제 번호/선지 기호 패턴 감지
        - 로컬 힌트 생성
        - 토큰 추정 기반 동적 청킹
        - 텍스트 지표 측정
        - 1차 경량 보정

        Returns:
            List[Dict]: 청크 목록
                [{
                    'chunk_id': 'chunk_001',
                    'text': '...',
                    'hint': {...},
                    'metrics': {...},
                    ...
                }]
        """
        pass

    def _phase_2_convert(self, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Phase 2: Claude CLI 서브프로세스 자동 호출 (v6 핵심).

        청크별 순차 처리:
        1. 프롬프트 조립
        2. 임시 UTF-8 파일에 저장
        3. `claude -p` 서브프로세스 호출
        4. stdout UTF-8 디코딩
        5. JSON 파싱
        6. 자동 재시도 (최대 3회)
        7. 임시 파일 정리

        상태 전이: CHUNK_READY → SENT → RESPONDED → PARSED

        Args:
            chunks: Phase 1 결과 청크 목록

        Returns:
            Dict: {
                'success': True/False,
                'parsed_chunks': [{...}, ...],
                'failed_chunks': [{...}, ...],
                'total_problems': int,
            }
        """
        pass

    def _phase_3_validate(
        self,
        parsed_data: Dict[str, Any],
        chunks: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Phase 3: 검증 및 신뢰도 점수 부여.

        다층 검증:
        - 구조 검증 (문제번호 연속성, 선지 개수 일관성)
        - Diff 검증 (원본 대비 누락 감지)
        - 법률 용어 2차 검증
        - 신뢰도 점수 계산

        분류: AUTO (≥95%) | HUMAN_REVIEW (<95%)

        Args:
            parsed_data: Phase 2 결과
            chunks: Phase 1 청크 (원본 비교용)

        Returns:
            Dict: {
                'all_questions': [...],
                'auto_confirmed': [...],
                'human_review': [...],
                'statistics': {...},
            }
        """
        pass

    def _phase_4_excel(self, validation_result: Dict[str, Any]) -> Dict[str, Path]:
        """
        Phase 4: Excel 생성.

        4개 시트:
        1. 전체 문제
        2. 검토 필요
        3. 단원별
        4. 변환 통계

        Args:
            validation_result: Phase 3 결과

        Returns:
            Dict[str, Path]: 생성된 Excel 파일 경로
                {
                    'main': Path('output/최종_문제집.xlsx'),
                    'review': Path('output/검토_필요_목록.xlsx'),
                    ...
                }
        """
        pass

    def _update_state(self, chunk_id: str, state: str, metadata: Optional[Dict] = None) -> None:
        """
        상태 머신 업데이트.

        Args:
            chunk_id: 청크 ID
            state: 새로운 상태 (PREPARED | TEXT_EXTRACTED | ... | PAUSED_LIMIT | ...)
            metadata: 추가 정보 (오류, 소요시간, 재시도 횟수 등)
        """
        pass
