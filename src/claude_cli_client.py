"""
Claude CLI 클라이언트 (v6 핵심 - Phase 2)

Claude Code CLI를 서브프로세스로 호출해 청크를 JSON으로 변환.
OCR 프로젝트의 run_ocr() 패턴을 배치용으로 일반화.

핵심 원칙:
1. 프롬프트는 임시 파일에 UTF-8로 저장 후 stdin으로 전달 (쉘 이스케이프 회피)
2. stdout은 bytes로 수신 후 명시적 UTF-8 디코딩 (Windows cp949 회피)
3. 오류 유형 분류(타임아웃/인코딩/인증/사용량 한도/기타) + 유형별 재시도 정책
4. RATE_LIMIT은 재시도하지 않고 상위(파이프라인)로 넘겨 PAUSED_LIMIT 처리

호출 방식 2단 구조:
- 1안(subprocess): claude 실행 파일을 직접 호출, 프롬프트 파일 내용을 stdin으로 주입.
  쉘을 아예 거치지 않으므로 이스케이프 문제가 원천 차단됨.
- 2안(powershell): 1안이 실패하는 환경(.cmd shim 문제 등)을 위한 폴백.
  OCR 프로젝트에서 검증된 PowerShell 경유 패턴.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMP_DIR = PROJECT_ROOT / "temp"

# stdout 디코딩 시 U+FFFD(replacement char) 비율이 이 값을 넘으면 인코딩 오염으로 판정
REPLACEMENT_CHAR = "�"
ENCODING_CORRUPTION_THRESHOLD = 0.005  # 0.5%

# Rate Limit 감지: claude CLI는 한도 도달 시
# "Claude AI usage limit reached|<epoch>" 형태를 stdout으로 출력하는 것이 대표 패턴.
# 그 외 문구/HTTP 코드 변형도 함께 매칭한다.
RATE_LIMIT_RESET_RE = re.compile(r"usage\s+limit\s+reached\s*\|\s*(\d{9,13})", re.IGNORECASE)
RATE_LIMIT_PATTERNS = [
    "usage limit reached",
    "usage limit",
    "rate limit",
    "rate_limit",
    "too many requests",
    "429",
    "overloaded",
    "quota exceeded",
]
AUTH_ERROR_PATTERNS = [
    "not logged in",
    "please run /login",
    "please login",
    "invalid api key",
    "authentication",
    "unauthenticated",
    "unauthorized",
    "401",
    "oauth token",
]

# 프롬프트 템플릿 파일이 없거나 형식이 어긋날 때 사용하는 내장 기본 템플릿
DEFAULT_TEMPLATE = """다음 법학 문제 텍스트를 JSON으로 변환해주세요.

## 구조 정보
- 문제 범위: {question_range}
- 선지 기호: {option_symbols}
- 문제당 선지 수: {options_per_question}
- 해설 구분자: {explanation_marker}

## 텍스트 상태
- 깨진 문자 비율: {broken_char_ratio}%
- 특이사항: {special_blocks}

## 로컬 힌트
{hint_json_pretty}

## 변환할 텍스트
{chunk_text}

## 변환 규칙
1. 명백한 OCR 오류만 수정하고, 불확실하면 "[의심:추정값]" 형식으로 표시
2. 법률 용어는 법학 문맥에 맞게 교정 (예: "게약" → "계약")
3. 모든 선지를 누락 없이 포함
4. 첫 번째 선지의 text에만 문제 전문을 쓰고, 이후 선지의 문제 부분은 "동일"로 처리
5. correct는 true/false만 사용, 해설이 없으면 explanation은 빈 문자열 ""

## 출력 형식
반드시 아래 JSON 형식으로만 출력하세요. JSON 외 다른 텍스트(인사말, 설명, 마크다운 펜스)는 절대 출력하지 마세요.

{"questions": [{"id": 1, "text": "문제 내용", "options": [{"num": "①", "text": "선지 내용", "correct": false, "explanation": "해설"}]}]}
"""


class CliErrorType(Enum):
    """CLI 서브프로세스 오류 분류."""
    OK = "ok"                          # 성공
    TIMEOUT = "timeout"                # 타임아웃
    ENCODING = "encoding"              # 인코딩 오염
    AUTH = "auth"                      # 인증 오류 (재시도 무의미 → 즉시 중단)
    RATE_LIMIT = "rate_limit"          # 사용량 한도 (→ PAUSED_LIMIT)
    CLI_NOT_FOUND = "cli_not_found"    # claude 명령 없음 (재시도 무의미)
    NONZERO_EXIT = "nonzero_exit"      # 비정상 종료 (기타)


# 재시도해도 의미가 없는 오류 유형 (상위 계층에서 별도 처리)
NON_RETRYABLE = {CliErrorType.RATE_LIMIT, CliErrorType.AUTH, CliErrorType.CLI_NOT_FOUND}


@dataclass
class CliResult:
    """Claude CLI 서브프로세스 실행 결과."""
    success: bool = False
    stdout: Optional[str] = None               # 최종 텍스트 (output-format json이면 언랩된 result)
    raw_stdout: Optional[str] = None           # 디코딩 직후 원문 (언랩 전)
    stderr: Optional[str] = None
    exit_code: int = -1
    duration_seconds: float = 0.0
    error_type: CliErrorType = CliErrorType.NONZERO_EXIT
    retry_attempt: int = 0
    temp_prompt_file: Optional[Path] = None    # 정리 후 None
    corruption_ratio: float = 0.0              # U+FFFD 비율
    rate_limit_reset_at: Optional[float] = None  # 한도 리셋 시각 (epoch 초)


class ClaudeCliClient:
    """
    Claude Code CLI 서브프로세스 호출 및 재시도 관리.

    v6 Phase 2 핵심 모듈.
    """

    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        """
        초기화.

        Args:
            config: config.yaml 로드 결과 전체 (cli 섹션 참조)
            logger: 로거 인스턴스
        """
        self.config = config
        self.cli_cfg: Dict[str, Any] = config.get("cli", {})
        self.logger = logger or logging.getLogger(__name__)

        self.claude_cmd: str = self.cli_cfg.get("claude_cmd", "claude")
        self.timeout: int = int(self.cli_cfg.get("timeout_seconds", 300))
        self.max_retries: int = int(self.cli_cfg.get("max_retries", 3))
        self.backoff: List[float] = list(self.cli_cfg.get("backoff_seconds", [5, 15, 45]))
        self.allowed_tools: List[str] = list(self.cli_cfg.get("allowed_tools", []))
        self.temp_cleanup: bool = bool(self.cli_cfg.get("temp_prompt_cleanup", True))
        self.errors_handler: str = self.cli_cfg.get("errors_handler", "replace")

        # stdin 전달 방식: "auto"면 첫 호출에서 subprocess → powershell 순으로 판정
        self.stdin_method: str = self.cli_cfg.get("stdin_method", "auto")
        self._resolved_method: Optional[str] = (
            self.stdin_method if self.stdin_method in ("subprocess", "powershell") else None
        )

        self._template_cache: Optional[str] = None

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    @property
    def use_output_format_json(self) -> bool:
        """--output-format json 사용 여부 (preflight가 config를 갱신하면 즉시 반영)."""
        return bool(self.cli_cfg.get("use_output_format_json", False))

    def convert_chunk(self, chunk: Dict[str, Any],
                      prompt_override: Optional[str] = None,
                      retry_attempt: int = 0) -> CliResult:
        """
        단일 청크를 JSON으로 변환 (1회 시도).

        단계:
        1. build_prompt(chunk) → 프롬프트 조립 (prompt_override가 있으면 생략)
        2. _write_temp_prompt() → temp/에 UTF-8 저장
        3. _invoke_cli() → subprocess 실행 (stdin 파이프)
        4. _decode_stdout() → UTF-8 명시 디코딩 + 오염 비율 측정
        5. --output-format json 사용 시 result 필드 언랩
        6. _classify_error() → 오류 유형 분류
        7. finally: 임시 파일 삭제

        Args:
            chunk: 청크 데이터 ({'chunk_id', 'text', 'hint', 'metrics', ...})
            prompt_override: 재시도 등에서 사용할 대체 프롬프트
            retry_attempt: 현재 재시도 회차 (기록용)

        Returns:
            CliResult: 실행 결과
        """
        chunk_id = str(chunk.get("chunk_id", "unknown"))
        prompt = prompt_override if prompt_override is not None else self.build_prompt(chunk)
        temp_path: Optional[Path] = None
        start = time.monotonic()

        try:
            temp_path = self._write_temp_prompt(prompt, chunk_id)

            try:
                raw_stdout, stderr, exit_code, duration = self._invoke_cli(temp_path)
            except subprocess.TimeoutExpired:
                duration = time.monotonic() - start
                self.logger.error("[%s] CLI 타임아웃 (%ds 초과)", chunk_id, self.timeout)
                return CliResult(
                    success=False, stderr=f"timeout after {self.timeout}s",
                    exit_code=-1, duration_seconds=duration,
                    error_type=CliErrorType.TIMEOUT, retry_attempt=retry_attempt,
                )
            except FileNotFoundError as e:
                duration = time.monotonic() - start
                self.logger.error("[%s] claude 명령을 찾을 수 없음: %s", chunk_id, e)
                return CliResult(
                    success=False, stderr=str(e), exit_code=-1,
                    duration_seconds=duration,
                    error_type=CliErrorType.CLI_NOT_FOUND, retry_attempt=retry_attempt,
                )

            text, corruption = self._decode_stdout(raw_stdout, chunk_id)
            raw_text = text
            if self.use_output_format_json:
                unwrapped = self._unwrap_output_format_json(text)
                if unwrapped is not None:
                    text = unwrapped

            result = CliResult(
                success=False, stdout=text, raw_stdout=raw_text, stderr=stderr,
                exit_code=exit_code, duration_seconds=duration,
                error_type=CliErrorType.OK, retry_attempt=retry_attempt,
                temp_prompt_file=temp_path, corruption_ratio=corruption,
            )
            result.error_type = self._classify_error(result)
            result.success = (result.error_type == CliErrorType.OK)

            if result.success:
                self.logger.info("[%s] CLI 응답 수신 (%.1fs, %d자)",
                                 chunk_id, duration, len(text or ""))
            else:
                self.logger.warning("[%s] CLI 오류: %s (exit=%d)",
                                    chunk_id, result.error_type.value, exit_code)
            return result

        finally:
            if temp_path is not None and self.temp_cleanup:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError as e:
                    self.logger.warning("[%s] 임시 파일 삭제 실패: %s", chunk_id, e)

    def run_with_retry(self, chunk: Dict[str, Any],
                       prompt_override: Optional[str] = None
                       ) -> Tuple[bool, Optional[CliResult]]:
        """
        재시도 정책을 포함한 청크 변환.

        정책 (오류 분류표):
        - TIMEOUT / ENCODING / NONZERO_EXIT: 지수 백오프 후 재시도 (최대 max_retries회)
        - RATE_LIMIT: 즉시 반환 → 파이프라인이 state_manager.pause_for_limit() 호출
        - AUTH / CLI_NOT_FOUND: 즉시 반환 → 파이프라인이 실행 중단 및 안내
        - JSON 파싱 실패에 따른 재시도는 response_parser + 파이프라인 계층에서
          _create_retry_prompt()로 이 메서드를 다시 호출하는 방식으로 처리

        Args:
            chunk: 청크 데이터
            prompt_override: 대체 프롬프트 (파싱 실패 재시도 시)

        Returns:
            Tuple[bool, CliResult|None]: (성공 여부, 마지막 결과)
        """
        chunk_id = str(chunk.get("chunk_id", "unknown"))
        last_result: Optional[CliResult] = None

        for attempt in range(1, self.max_retries + 1):
            if attempt > 1:
                delay = self.backoff[min(attempt - 2, len(self.backoff) - 1)]
                self.logger.info("[%s] %.0f초 대기 후 재시도 (%d/%d)",
                                 chunk_id, delay, attempt, self.max_retries)
                time.sleep(delay)

            result = self.convert_chunk(chunk, prompt_override=prompt_override,
                                        retry_attempt=attempt)
            last_result = result

            if result.success:
                return True, result
            if result.error_type in NON_RETRYABLE:
                # 재시도 무의미: 사용량 한도/인증/미설치는 상위 계층에서 처리
                return False, result

        self.logger.error("[%s] %d회 시도 모두 실패 (마지막 오류: %s)",
                          chunk_id, self.max_retries,
                          last_result.error_type.value if last_result else "?")
        return False, last_result

    def build_prompt(self, chunk: Dict[str, Any]) -> str:
        """
        청크별 Claude 프롬프트 생성.

        prompts/prompt_template.md에서 템플릿을 추출해 {변수}를 치환.
        템플릿 파일이 없거나 {chunk_text} 마커가 없으면 내장 기본 템플릿 사용.
        str.format 대신 str.replace를 쓰는 이유: 템플릿에 포함된 JSON 예시의
        중괄호가 format 필드로 오인되는 것을 방지.

        Args:
            chunk: 청크 데이터

        Returns:
            str: 완성된 프롬프트
        """
        template = self._load_template()
        hint: Dict[str, Any] = chunk.get("hint", {}) or {}
        metrics: Dict[str, Any] = chunk.get("metrics", {}) or hint.get("text_metrics", {}) or {}

        qr = hint.get("question_range") or {}
        if isinstance(qr, dict) and qr:
            question_range = f"{qr.get('start', '?')}~{qr.get('end', '?')}"
        else:
            question_range = str(chunk.get("question_range", "알 수 없음"))

        special = hint.get("special_blocks") or []
        special_str = (
            ", ".join(f"{b.get('location', '?')}: {b.get('type', '?')}" for b in special)
            if special else "없음"
        )

        variables = {
            "{question_range}": question_range,
            "{option_symbols}": str(hint.get("option_symbols", "circled")),
            "{options_per_question}": str(hint.get("options_per_question", 5)),
            "{explanation_marker}": str(hint.get("explanation_marker", "[해설]")),
            "{broken_char_ratio}": str(round(float(metrics.get("broken_char_ratio", 0)) * 100, 1)),
            "{excessive_space_ratio}": str(round(float(metrics.get("excessive_space_ratio", 0)) * 100, 1)),
            "{total_chars}": str(metrics.get("total_chars", len(chunk.get("text", "")))),
            "{special_blocks}": special_str,
            "{hint_json_pretty}": json.dumps(hint, ensure_ascii=False, indent=2) if hint else "(없음)",
            "{chunk_text}": chunk.get("text", ""),
        }
        prompt = template
        for key, value in variables.items():
            prompt = prompt.replace(key, value)
        return prompt

    def _create_retry_prompt(self, chunk: Dict[str, Any], error_detail: str) -> str:
        """
        JSON 파싱 실패 시 재시도용 프롬프트 생성.

        기본 프롬프트 앞에 이전 오류 내용과 더 엄격한 형식 요구를 덧붙인다.

        Args:
            chunk: 청크 데이터
            error_detail: 오류 상세 (파싱 오류 메시지, 잘림 위치 등)

        Returns:
            str: 재시도 프롬프트
        """
        notice = (
            "⚠️ 이전 응답이 다음 오류로 처리에 실패했습니다:\n"
            f"    {error_detail}\n"
            "이번에는 반드시 다음을 지켜주세요:\n"
            "1. 응답 전체가 파싱 가능한 하나의 JSON 객체여야 합니다.\n"
            "2. JSON 앞뒤에 어떤 텍스트/마크다운 펜스도 붙이지 마세요.\n"
            "3. 모든 문자열의 따옴표와 괄호를 완전히 닫으세요.\n\n"
        )
        return notice + self.build_prompt(chunk)

    # ------------------------------------------------------------------
    # 내부 구현
    # ------------------------------------------------------------------

    def _load_template(self) -> str:
        """
        프롬프트 템플릿 로드 (캐시됨).

        prompts/prompt_template.md는 문서+템플릿 혼합 형식이므로,
        {chunk_text} 마커를 포함한 첫 번째 코드 펜스 블록을 템플릿으로 추출.
        실패 시 내장 DEFAULT_TEMPLATE 사용.
        """
        if self._template_cache is not None:
            return self._template_cache

        template = DEFAULT_TEMPLATE
        template_file = PROJECT_ROOT / self.config.get("prompt", {}).get(
            "template_file", "prompts/prompt_template.md")
        try:
            content = template_file.read_text(encoding="utf-8")
            # {chunk_text} 마커가 포함된 코드 펜스 블록 추출
            for m in re.finditer(r"```(?:\w*)\n(.*?)```", content, re.DOTALL):
                block = m.group(1)
                if "{chunk_text}" in block:
                    template = block
                    break
            else:
                if "{chunk_text}" in content and "```" not in content:
                    template = content  # 파일 전체가 순수 템플릿인 경우
                else:
                    self.logger.warning(
                        "%s에서 {chunk_text} 템플릿 블록을 찾지 못해 내장 템플릿 사용",
                        template_file.name)
        except OSError:
            self.logger.warning("템플릿 파일 없음(%s) → 내장 템플릿 사용", template_file)

        self._template_cache = template
        return template

    def _write_temp_prompt(self, prompt: str, chunk_id: str) -> Path:
        """
        프롬프트를 임시 파일에 UTF-8로 저장.

        파일명: temp/prompt_{chunk_id}_{uuid8}.txt
        (uuid 포함 → 향후 병렬화/중복 실행 시 충돌 방지)

        Args:
            prompt: 프롬프트 텍스트
            chunk_id: 청크 ID

        Returns:
            Path: 임시 파일 경로
        """
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        safe_id = re.sub(r"[^\w\-]", "_", chunk_id)
        path = TEMP_DIR / f"prompt_{safe_id}_{uuid.uuid4().hex[:8]}.txt"
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(prompt)
        return path

    def _build_claude_args(self) -> List[str]:
        """claude 명령 인자 목록 조립 (-p, --allowedTools, --output-format)."""
        args = ["-p"]
        if self.allowed_tools:
            args += ["--allowedTools", ",".join(self.allowed_tools)]
        if self.use_output_format_json:
            args += ["--output-format", "json"]
        return args

    def _invoke_cli(self, prompt_path: Path,
                    stdin_method: Optional[str] = None
                    ) -> Tuple[bytes, Optional[str], int, float]:
        """
        `claude -p` 서브프로세스 호출.

        방식이 "auto"면 subprocess 직접 호출을 먼저 시도하고,
        OS 수준 실행 실패(.cmd shim 문제 등) 시 PowerShell로 폴백.
        성공한 방식은 캐시되어 이후 호출에 재사용.

        Args:
            prompt_path: 프롬프트 파일 경로
            stdin_method: 강제 지정 시 "subprocess" | "powershell"

        Returns:
            Tuple: (stdout bytes, stderr str, exit_code, duration_seconds)

        Raises:
            subprocess.TimeoutExpired: 타임아웃
            FileNotFoundError: 어떤 방식으로도 claude 실행 불가
        """
        method = stdin_method or self._resolved_method

        if method == "powershell":
            return self._invoke_via_powershell(prompt_path)
        if method == "subprocess":
            return self._invoke_via_subprocess(prompt_path)

        # auto: subprocess 우선, 실행 자체가 불가능하면 powershell 폴백
        try:
            result = self._invoke_via_subprocess(prompt_path)
            self._resolved_method = "subprocess"
            return result
        except (FileNotFoundError, OSError) as e:
            self.logger.info("subprocess 직접 호출 실패(%s) → PowerShell 폴백", e)
            result = self._invoke_via_powershell(prompt_path)
            self._resolved_method = "powershell"
            return result

    def _invoke_via_subprocess(self, prompt_path: Path
                               ) -> Tuple[bytes, Optional[str], int, float]:
        """
        1안: claude 실행 파일 직접 호출 + stdin 파이프.

        shell=False로 쉘을 완전히 우회 → 이스케이프 문제 원천 차단.
        프롬프트는 파일에서 bytes로 읽어 stdin으로 주입 (명령줄 길이 제한 회피).
        """
        claude_exe = shutil.which(self.claude_cmd) or self.claude_cmd
        cmd = [claude_exe] + self._build_claude_args()

        prompt_bytes = prompt_path.read_bytes()
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        start = time.monotonic()
        proc = subprocess.run(
            cmd,
            input=prompt_bytes,
            capture_output=True,     # bytes 그대로 수신 (text=True 금지: locale 디코딩 회피)
            timeout=self.timeout,
            env=env,
            cwd=str(PROJECT_ROOT),   # CLAUDE.md(변환 규칙)가 로딩되는 위치를 고정
        )
        duration = time.monotonic() - start
        stderr = (proc.stderr.decode("utf-8", errors="replace").strip()
                  if proc.stderr else None)
        return proc.stdout, stderr, proc.returncode, duration

    def _invoke_via_powershell(self, prompt_path: Path
                               ) -> Tuple[bytes, Optional[str], int, float]:
        """
        2안(폴백): PowerShell 경유 호출 — OCR 프로젝트 검증 패턴.

        - 입출력 인코딩을 UTF-8로 강제 ([Console]::OutputEncoding / $OutputEncoding)
        - Get-Content -Raw -Encoding UTF8 로 프롬프트를 읽어 파이프로 전달
          (프롬프트가 명령줄 인자에 오르지 않으므로 이스케이프/길이 문제 없음)
        - exit $LASTEXITCODE 로 claude의 종료 코드를 그대로 전파
        """
        args_str = " ".join(self._build_claude_args_ps())
        script = "; ".join([
            "$ErrorActionPreference = 'Continue'",
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8",
            "$OutputEncoding = [System.Text.Encoding]::UTF8",
            f"Get-Content -LiteralPath '{prompt_path}' -Raw -Encoding UTF8"
            f" | & '{self.claude_cmd}' {args_str}",
            "exit $LASTEXITCODE",
        ])
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        start = time.monotonic()
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=self.timeout,
            env=env,
            cwd=str(PROJECT_ROOT),
        )
        duration = time.monotonic() - start
        stderr = (proc.stderr.decode("utf-8", errors="replace").strip()
                  if proc.stderr else None)
        return proc.stdout, stderr, proc.returncode, duration

    def _build_claude_args_ps(self) -> List[str]:
        """PowerShell 스크립트 내 claude 인자 (값을 단일 인용부호로 감쌈)."""
        args = ["-p"]
        if self.allowed_tools:
            args += ["--allowedTools", f"'{','.join(self.allowed_tools)}'"]
        if self.use_output_format_json:
            args += ["--output-format", "json"]
        return args

    def _decode_stdout(self, raw_bytes: bytes, chunk_id: str = "") -> Tuple[str, float]:
        """
        stdout을 UTF-8로 명시 디코딩하고 오염 비율을 측정.

        오염 비율 = U+FFFD(replacement char) 개수 / 전체 문자 수.
        임계값(0.5%) 초과 시 원시 bytes를 logs/raw/에 보존해 사후 분석 가능하게 함.

        Args:
            raw_bytes: 원시 stdout
            chunk_id: 로깅/보존 파일명용

        Returns:
            Tuple[str, float]: (디코딩된 텍스트, 오염 비율)
        """
        if not raw_bytes:
            return "", 0.0
        text = raw_bytes.decode("utf-8", errors=self.errors_handler)
        if not text:
            return "", 0.0
        corruption = text.count(REPLACEMENT_CHAR) / len(text)

        if corruption > ENCODING_CORRUPTION_THRESHOLD:
            raw_dir = PROJECT_ROOT / self.config.get("logging", {}).get(
                "raw_bytes_dir", "logs/raw")
            try:
                raw_dir.mkdir(parents=True, exist_ok=True)
                safe_id = re.sub(r"[^\w\-]", "_", chunk_id or "unknown")
                dump = raw_dir / f"{safe_id}_{uuid.uuid4().hex[:8]}.bin"
                dump.write_bytes(raw_bytes)
                self.logger.warning(
                    "[%s] 인코딩 오염 %.2f%% → 원시 bytes 보존: %s",
                    chunk_id, corruption * 100, dump.name)
            except OSError as e:
                self.logger.warning("[%s] 원시 bytes 보존 실패: %s", chunk_id, e)
        return text, corruption

    def _unwrap_output_format_json(self, text: str) -> Optional[str]:
        """
        --output-format json 봉투에서 result 필드 추출.

        claude CLI의 JSON 출력은 {"type": "result", "result": "...", ...} 형태.

        Args:
            text: stdout 텍스트

        Returns:
            str: result 필드 값, 봉투 파싱 실패 시 None (원문 유지)
        """
        try:
            envelope = json.loads(text.strip())
        except (json.JSONDecodeError, AttributeError):
            return None
        if isinstance(envelope, dict) and "result" in envelope:
            result = envelope["result"]
            return result if isinstance(result, str) else json.dumps(
                result, ensure_ascii=False)
        return None

    # ------------------------------------------------------------------
    # 오류 분류
    # ------------------------------------------------------------------

    def _classify_error(self, result: CliResult) -> CliErrorType:
        """
        CLI 실행 결과에서 오류 유형 분류.

        판정 순서 (신뢰도 높은 신호부터):
        1. RATE_LIMIT: _detect_rate_limit() — 문자열 패턴 + exit code + 출력 길이 복합 판정
        2. AUTH: stderr/stdout의 인증 오류 패턴
        3. ENCODING: U+FFFD 오염 비율 > 임계값
        4. NONZERO_EXIT: exit code != 0 또는 빈 응답
        5. OK

        Args:
            result: CliResult (stdout/stderr/exit_code/corruption_ratio 채워진 상태)

        Returns:
            CliErrorType: 분류된 오류 유형
        """
        is_limit, reset_at = self._detect_rate_limit(
            result.stdout, result.stderr, result.exit_code)
        if is_limit:
            result.rate_limit_reset_at = reset_at
            return CliErrorType.RATE_LIMIT

        combined = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
        if result.exit_code != 0 and any(p in combined for p in AUTH_ERROR_PATTERNS):
            return CliErrorType.AUTH

        # 오염 비율: convert_chunk이 채운 값과 stdout 직접 측정값 중 큰 쪽 사용
        # (외부에서 CliResult를 직접 구성한 경우에도 분류가 정확하도록)
        stdout_text = result.stdout or ""
        measured = (stdout_text.count(REPLACEMENT_CHAR) / len(stdout_text)
                    if stdout_text else 0.0)
        if max(result.corruption_ratio, measured) > ENCODING_CORRUPTION_THRESHOLD:
            return CliErrorType.ENCODING

        if result.exit_code != 0:
            return CliErrorType.NONZERO_EXIT
        if not (result.stdout or "").strip():
            # 정상 종료했지만 출력이 비어 있음 → 실패로 취급 (재시도 대상)
            return CliErrorType.NONZERO_EXIT

        return CliErrorType.OK

    def _detect_rate_limit(self, stdout: Optional[str], stderr: Optional[str],
                           exit_code: int) -> Tuple[bool, Optional[float]]:
        """
        Rate Limit(사용량 한도) 복합 감지.

        단순 문자열 매칭의 오탐(법학 지문에 우연히 포함된 단어 등)을 막기 위해
        여러 신호를 결합해 판정한다:

        신호 A (결정적): "usage limit reached|<epoch>" 패턴
            → claude CLI의 공식 한도 메시지. 리셋 시각(epoch)까지 파싱해 반환.
        신호 B (복합): 한도 관련 문구 존재 AND (exit_code != 0 OR 출력이 비정상적으로 짧음)
            → 정상 변환 결과(JSON, 수천 자)에 한도 문구가 우연히 들어가고
              exit 0에 충분한 길이라면 오탐으로 보고 무시.

        Args:
            stdout: 표준 출력
            stderr: 표준 오류
            exit_code: 종료 코드

        Returns:
            Tuple[bool, float|None]: (한도 여부, 리셋 시각 epoch 초 또는 None)
        """
        combined = f"{stdout or ''}\n{stderr or ''}"
        combined_lower = combined.lower()

        # 신호 A: 결정적 패턴 + 리셋 시각 파싱
        m = RATE_LIMIT_RESET_RE.search(combined)
        if m:
            epoch = float(m.group(1))
            if epoch > 1e12:  # 밀리초 단위로 온 경우 초로 변환
                epoch /= 1000.0
            return True, epoch

        # 신호 B: 패턴 + 상태 복합 판정
        pattern_hit = any(p in combined_lower for p in RATE_LIMIT_PATTERNS)
        if pattern_hit:
            output_len = len((stdout or "").strip())
            if exit_code != 0 or output_len < 500:
                return True, None

        return False, None
