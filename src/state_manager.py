"""
상태 머신 관리 (v6 신설)

파이프라인 상태 추적, 중단 후 재개, 오류 복구.
PAUSED_LIMIT 상태로 Pro 사용량 한도 대응.
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from enum import Enum


class PipelineState(Enum):
    """파이프라인 상태 정의."""
    PREPARED = "PREPARED"                   # 초기 상태
    TEXT_EXTRACTED = "TEXT_EXTRACTED"       # PDF 텍스트 추출 완료
    HINTS_GENERATED = "HINTS_GENERATED"     # 로컬 힌트 생성 완료
    CHUNKS_CREATED = "CHUNKS_CREATED"       # 청크 생성 완료
    CHUNK_READY = "CHUNK_READY"             # Claude 입력 준비 완료
    SENT = "SENT"                           # Claude 전송 완료
    RESPONDED = "RESPONDED"                 # 응답 수신 완료
    PARSED = "PARSED"                       # JSON 파싱 완료
    VALIDATED = "VALIDATED"                 # 검증 완료
    COMPLETED = "COMPLETED"                 # 청크별 최종 완료
    FAILED = "FAILED"                       # 실패
    PAUSED_LIMIT = "PAUSED_LIMIT"           # ★ v6 신설: Pro 사용량 한도 일시정지 (재개 가능)
    SKIPPED = "SKIPPED"                     # 건너뜀


class StateTransitionError(Exception):
    """상태 전이 오류."""
    pass


class StateManager:
    """
    파이프라인 상태 머신 관리.

    상태 저장/로드, 전이 검증, 중단/재개 지원.
    """

    # 허용되는 상태 전이
    TRANSITIONS = {
        PipelineState.PREPARED: [PipelineState.TEXT_EXTRACTED],
        PipelineState.TEXT_EXTRACTED: [PipelineState.HINTS_GENERATED],
        PipelineState.HINTS_GENERATED: [PipelineState.CHUNKS_CREATED],
        PipelineState.CHUNKS_CREATED: [PipelineState.CHUNK_READY],
        PipelineState.CHUNK_READY: [PipelineState.SENT, PipelineState.SKIPPED],
        PipelineState.SENT: [PipelineState.RESPONDED, PipelineState.PAUSED_LIMIT, PipelineState.FAILED],
        PipelineState.RESPONDED: [PipelineState.PARSED, PipelineState.FAILED],
        PipelineState.PARSED: [PipelineState.VALIDATED, PipelineState.FAILED],
        PipelineState.VALIDATED: [PipelineState.COMPLETED, PipelineState.FAILED],
        PipelineState.PAUSED_LIMIT: [PipelineState.CHUNK_READY],  # 재개 시
        PipelineState.FAILED: [PipelineState.CHUNK_READY],  # 재시도 시
    }

    def __init__(self, state_file: str, logger=None):
        """
        초기화.

        Args:
            state_file: 상태 저장 파일 경로 (state/pipeline_state.json)
            logger: 로거 인스턴스 (선택적)
        """
        pass

    def load_state(self) -> Dict[str, Any]:
        """
        상태 파일 로드.

        파일이 없으면 초기 상태 생성.

        Returns:
            Dict: 로드된 상태
                {
                    'pdf_path': '...',
                    'created_at': '2026-07-11T10:00:00',
                    'last_updated': '2026-07-11T10:05:00',
                    'chunks': {
                        'chunk_001': {
                            'state': 'COMPLETED',
                            'timestamp': '...',
                            'retry_count': 0,
                            'error_type': None,
                            'duration_seconds': 42.5,
                            'cli_method': 'subprocess',
                        },
                        'chunk_002': {...},
                    },
                    'global_state': 'PHASE_2',
                    'progress': {
                        'completed': 1,
                        'total': 8,
                        'paused': 0,
                    }
                }
        """
        pass

    def transition(
        self,
        chunk_id: str,
        new_state: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        상태 전이.

        단계:
        1. 전이 유효성 검증
        2. 메타데이터 기록 (시간, 오류, retry_count, cli_method 등)
        3. 상태 파일 저장

        Args:
            chunk_id: 청크 ID (또는 "global" 전역 상태)
            new_state: 새로운 상태 (문자열 또는 PipelineState enum)
            metadata: 추가 정보
                {
                    'error_type': 'TIMEOUT',
                    'error_message': '...',
                    'retry_count': 1,
                    'duration_seconds': 42.5,
                    'cli_method': 'subprocess',  # CLI 실행 방식
                }

        Raises:
            StateTransitionError: 유효하지 않은 전이
        """
        pass

    def get_resumable_chunks(self) -> List[str]:
        """
        중단 후 재개 가능한 청크 ID 목록 반환.

        상태: PAUSED_LIMIT, FAILED, CHUNK_READY 등 재시도 가능 상태.

        Returns:
            List[str]: 청크 ID 목록
        """
        pass

    def get_progress(self) -> Dict[str, Any]:
        """
        전체 진행률 반환.

        Returns:
            Dict: 진행 현황
                {
                    'completed': 5,
                    'total': 8,
                    'percentage': 62.5,
                    'paused': 1,
                    'failed': 0,
                    'remaining': 3,
                    'eta_seconds': 120,  # 예상 남은 시간 (평균 기반)
                }
        """
        pass

    def save_state(self) -> None:
        """현재 상태를 파일로 저장."""
        pass

    def validate_transition(
        self,
        current_state: str,
        new_state: str
    ) -> bool:
        """
        상태 전이 유효성 검증.

        Args:
            current_state: 현재 상태
            new_state: 새로운 상태

        Returns:
            bool: 전이 가능 여부
        """
        pass
