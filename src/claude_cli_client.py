"""
Claude CLI 클라이언트 (v6 핵심 - Phase 2)

Claude Code CLI를 서브프로세스로 호출해 청크를 JSON으로 변환.
OCR 프로젝트의 run_ocr() 패턴을 배치용으로 일반화.

핵심 원칙:
1. 프롬프트는 임시 파일에 UTF-8로 저장해 전달 (쉘 이스케이프 회피)
2. stdout은 bytes로 수신 후 명시적 UTF-8 디코딩
3. 8가지 오류 유형 분류 + 재시도 정책
4. PAUSED_LIMIT 상태로 Pro 사용량 한도 대응
"""

import subprocess
import tempfile
import json
import logging
import time
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class CliErrorType(Enum):
    """CLI 서브프로세스 오류 분류."""
    OK = "ok"                          # 성공
    TIMEOUT = "timeout"                # 타임아웃
    ENCODING = "encoding"              # 인코딩 오염
    AUTH = "auth"                      # 인증 오류
    RATE_LIMIT = "rate_limit"         # 사용량 한도
    NONZERO_EXIT = "nonzero_exit"     # 비정상 종료 (기타)


@dataclass
class CliResult:
    """Claude CLI 서브프로세스 실행 결과."""

    success: bool
    stdout: Optional[str]              # JSON 응답 (성공 시)
    stderr: Optional[str]              # 오류 메시지
    exit_code: int
    duration_seconds: float
    error_type: CliErrorType
    retry_attempt: int                 # 재시도 횟수
    temp_prompt_file: Optional[Path]   # 임시 프롬프트 파일 (정리되어야 함)


class ClaudeCliClient:
    """
    Claude Code CLI 서브프로세스 호출 및 재시도 관리.

    v6 Phase 2 핵심 모듈.
    """

    def __init__(self, config: Dict[str, Any], logger: logging.Logger):
        """
        초기화.

        Args:
            config: config.yaml 로드 결과 (cli 섹션)
            logger: 로거 인스턴스
        """
        pass

    def convert_chunk(self, chunk: Dict[str, Any]) -> CliResult:
        """
        단일 청크를 JSON으로 변환 (1회 시도).

        단계:
        1. build_prompt(chunk) → 프롬프트 조립
        2. _write_temp_prompt(prompt) → temp/에 UTF-8 저장
        3. _invoke_cli(prompt_path) → subprocess 실행
        4. _decode_stdout(raw_bytes) → UTF-8 디코딩 + 검증
        5. finally: 임시 파일 삭제

        Args:
            chunk: 청크 데이터
                {
                    'chunk_id': 'chunk_001',
                    'text': '...',
                    'hint': {...},
                    'metrics': {...},
                }

        Returns:
            CliResult: 실행 결과
        """
        pass

    def run_with_retry(self, chunk: Dict[str, Any]) -> Tuple[bool, Optional[CliResult]]:
        """
        재시도 정책을 포함한 청크 변환.

        오류 분류표:
        - TIMEOUT: 재시도 (지수 백오프), 반복 시 청크 이분할
        - ENCODING: 재시도 (UTF-8 재설정)
        - JSON 앞뒤 잡음: 재추출 → 재시도 프롬프트
        - 출력 잘림(JSON 미종결): 부분 복구 + 나머지만 재요청
        - RATE_LIMIT: PAUSED_LIMIT 상태 반환 (재시도 아님)
        - AUTH: 즉시 중단 (재시도 아님)

        최대 3회 재시도, 지수 백오프 (5s → 15s → 45s).

        Args:
            chunk: 청크 데이터

        Returns:
            Tuple[bool, CliResult|None]: (성공 여부, 결과 또는 None)
        """
        pass

    def build_prompt(self, chunk: Dict[str, Any]) -> str:
        """
        청크별 Claude 프롬프트 생성.

        prompts/prompt_template.md 로드 후 {변수} 치환.

        Args:
            chunk: 청크 데이터

        Returns:
            str: 생성된 프롬프트
        """
        pass

    def _write_temp_prompt(self, prompt: str) -> Path:
        """
        프롬프트를 임시 파일에 UTF-8로 저장.

        파일명: temp/prompt_{chunk_id}_{uuid}.txt
        인코딩: UTF-8 (Windows cp949 회피)

        Args:
            prompt: 프롬프트 텍스트

        Returns:
            Path: 임시 파일 경로

        Raises:
            IOError: 파일 쓰기 실패
        """
        pass

    def _invoke_cli(
        self,
        prompt_path: Path,
        stdin_method: str = "auto"
    ) -> Tuple[bytes, Optional[str], int, float]:
        """
        `claude -p` 서브프로세스 호출.

        stdin 전달 방식 (우선순위):
        1. subprocess.run(..., stdin=file, shell=False)
        2. PowerShell 경유 (Windows 폴백)

        Args:
            prompt_path: 프롬프트 파일 경로
            stdin_method: 전달 방식 ("subprocess" | "powershell" | "auto")

        Returns:
            Tuple[bytes, str|None, int, float]:
                - stdout (bytes)
                - stderr (str or None)
                - exit_code
                - duration_seconds

        Raises:
            TimeoutExpired: timeout 초과
            FileNotFoundError: claude 명령 없음
        """
        pass

    def _decode_stdout(self, raw_bytes: bytes) -> Tuple[str, float]:
        """
        stdout을 UTF-8로 디코딩.

        오염 감지: replacement char(U+FFFD) 비율 > 임계값(0.5%) → 인코딩 오류

        Args:
            raw_bytes: 원시 바이트

        Returns:
            Tuple[str, float]: (디코딩된 텍스트, 오염 비율)

        Raises:
            UnicodeDecodeError: 복구 불가능한 인코딩 오류
        """
        pass

    def _classify_error(self, result: CliResult) -> CliErrorType:
        """
        CLI 실행 결과에서 오류 유형 분류.

        Args:
            result: CliResult

        Returns:
            CliErrorType: 분류된 오류 유형

        감지 대상:
        - TimeoutExpired → TIMEOUT
        - exit_code != 0 → stderr 패턴 매칭:
          - "rate limit" / "usage limit" → RATE_LIMIT
          - "auth" / "unauthenticated" → AUTH
          - 그 외 → NONZERO_EXIT
        - 인코딩 오염 비율 > 임계값 → ENCODING
        - 기타 → OK
        """
        pass

    def _create_retry_prompt(
        self,
        chunk: Dict[str, Any],
        error_detail: str
    ) -> str:
        """
        재시도용 프롬프트 생성.

        오류 내용을 첨부해 더 엄격한 형식 요청.

        Args:
            chunk: 청크 데이터
            error_detail: 오류 상세 (파싱 오류, 잘림 위치 등)

        Returns:
            str: 재시도 프롬프트
        """
        pass
