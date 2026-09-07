"""
프리플라이트 검증 (Phase 0)

파이프라인 시작 전 필수 조건 사전 점검:
1. Claude Code CLI 설치 여부 (claude --version)
2. 인증 상태 + 한글 인코딩 (초소형 한글 프롬프트 1회 실행)
3. stdin 전달 방식 판정 (subprocess 우선 → powershell 폴백, 결과 캐시)
4. --output-format json 지원 여부 (미지원이어도 에러 없이 플래그만 False로 — Fallback)
5. 법률 용어 사전 파일 로드 가능 여부

목적: 청크 60개를 만들어 놓고 첫 호출에서 실패하는 낭비 방지 (fail-fast).
검증 결과는 state/preflight.json에 저장되어 이후 실행에서 참조 가능.
"""

import json
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from claude_cli_client import ClaudeCliClient, CliErrorType

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 인증+인코딩을 한 번에 확인하는 초소형 프롬프트.
# 한글 마커가 왕복해서 돌아오면 인코딩 정상, 응답 자체가 오면 인증 정상.
PROBE_MARKER = "가나다검증완료"
PROBE_PROMPT = (
    f"다음 단어만 정확히 출력하세요. 다른 텍스트는 절대 출력하지 마세요: {PROBE_MARKER}"
)
VERSION_CHECK_TIMEOUT = 60   # --version은 빨라야 정상
PROBE_TIMEOUT = 120          # 초소형 프롬프트 응답 대기 상한


@dataclass
class PreflightResult:
    """프리플라이트 검증 결과."""
    passed: bool = False                       # 모든 필수 검사 통과 여부
    cli_available: bool = False                # CLI 설치/실행 가능
    cli_version: Optional[str] = None          # CLI 버전 문자열
    authenticated: bool = False                # 인증 상태
    encoding_ok: bool = False                  # 한글 UTF-8 왕복 정상
    stdin_method: Optional[str] = None         # 동작 확인된 방식 (subprocess|powershell)
    output_format_json_supported: bool = False # --output-format json 지원 여부
    cli_response_time: Optional[float] = None  # 테스트 프롬프트 응답 시간(초)
    dictionaries_ok: bool = False              # 사전 파일 로드 가능
    errors: List[str] = field(default_factory=list)    # 실행 차단 사유
    warnings: List[str] = field(default_factory=list)  # 비차단 경고

    def summary(self) -> str:
        """사람이 읽을 요약 문자열."""
        mark = lambda ok: "✓" if ok else "✗"
        lines = [
            f"[Phase 0] 프리플라이트 결과: {'통과' if self.passed else '실패'}",
            f"  {mark(self.cli_available)} CLI 설치"
            + (f" (버전: {self.cli_version})" if self.cli_version else ""),
            f"  {mark(self.authenticated)} 인증 상태",
            f"  {mark(self.encoding_ok)} 한글 인코딩 (UTF-8 왕복)",
            f"  {mark(self.dictionaries_ok)} 법률 용어 사전",
            f"  - stdin 방식: {self.stdin_method or '판정 실패'}",
            f"  - --output-format json: "
            + ("지원" if self.output_format_json_supported else "미지원 → 텍스트 모드 폴백"),
        ]
        if self.cli_response_time is not None:
            lines.append(f"  - 기준 응답 시간: {self.cli_response_time:.1f}초")
        for e in self.errors:
            lines.append(f"  [오류] {e}")
        for w in self.warnings:
            lines.append(f"  [경고] {w}")
        return "\n".join(lines)


class Preflight:
    """
    프리플라이트 검증 실행기 (Phase 0).

    ClaudeCliClient의 호출 경로를 그대로 사용해 검증하므로,
    여기서 통과한 방식은 본 실행(Phase 2)에서도 동일하게 동작함이 보장된다.
    """

    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        """
        초기화.

        Args:
            config: config.yaml 로드 결과 (검증 결과에 따라 cli 섹션이 갱신됨)
            logger: 로거 인스턴스
        """
        self.config = config
        self.cli_cfg: Dict[str, Any] = config.setdefault("cli", {})
        self.logger = logger or logging.getLogger(__name__)
        self.claude_cmd: str = self.cli_cfg.get("claude_cmd", "claude")
        self.dictionary_path = PROJECT_ROOT / config.get("local_correction", {}).get(
            "dictionary_path", "dictionaries/legal_terms.json")
        self.result_file = PROJECT_ROOT / "state" / "preflight.json"

    def run(self) -> PreflightResult:
        """
        프리플라이트 검증 전체 실행.

        순서:
        1. CLI 설치 확인 — 실패 시 이후 검사 생략하고 즉시 반환
        2. 프로브 프롬프트 실행 → 인증/인코딩/stdin 방식/응답시간 동시 확인
        3. --output-format json 지원 테스트 → config 플래그 갱신 (Fallback, 에러 아님)
        4. 사전 파일 확인
        5. 결과를 state/preflight.json에 저장

        Returns:
            PreflightResult: 검증 결과
        """
        result = PreflightResult()
        self.logger.info("[Phase 0] 프리플라이트 검증 시작")

        # 1. CLI 설치 확인
        result.cli_available, result.cli_version = self._check_cli_installed()
        if not result.cli_available:
            result.errors.append(
                "Claude Code CLI를 찾을 수 없습니다. "
                "`claude --version`이 동작하는지 확인하고, 미설치라면 "
                "https://claude.com/claude-code 에서 설치하세요.")
            self._save_result(result)
            self.logger.error(result.summary())
            return result

        # 2. 프로브 프롬프트: 인증 + 인코딩 + stdin 방식 + 응답시간을 1회 호출로 확인
        client = self._make_probe_client(use_output_format_json=False)
        probe = self._run_probe(client, result)

        # 3. --output-format json 지원 테스트 (인증된 경우에만 의미 있음)
        if result.authenticated:
            result.output_format_json_supported = self._check_output_format_json()
        self._apply_output_format_fallback(result)

        # 4. 사전 파일 확인
        result.dictionaries_ok = self._check_dictionaries()
        if not result.dictionaries_ok:
            result.errors.append(
                f"법률 용어 사전을 로드할 수 없습니다: {self.dictionary_path}")

        # 5. 종합 판정 및 저장
        result.passed = (
            result.cli_available
            and result.authenticated
            and result.encoding_ok
            and result.dictionaries_ok
            and result.stdin_method is not None
        )
        self._save_result(result)
        log = self.logger.info if result.passed else self.logger.error
        log(result.summary())
        return result

    # ------------------------------------------------------------------
    # 개별 검사
    # ------------------------------------------------------------------

    def _check_cli_installed(self) -> Tuple[bool, Optional[str]]:
        """
        Claude CLI 설치/실행 가능 여부 확인.

        1차: shutil.which로 해석한 경로를 직접 실행 (claude --version)
        2차: PowerShell 경유 실행 (PATH 해석/shim 문제 폴백)

        Returns:
            Tuple[bool, str|None]: (설치됨, 버전 문자열)
        """
        resolved = shutil.which(self.claude_cmd)
        if resolved:
            ok, version = self._try_version_cmd([resolved, "--version"])
            if ok:
                return True, version

        # PowerShell 폴백 (& 호출은 .cmd shim도 처리)
        ok, version = self._try_version_cmd([
            "powershell", "-NoProfile", "-NonInteractive", "-Command",
            f"& '{self.claude_cmd}' --version",
        ])
        return ok, version

    def _try_version_cmd(self, cmd: List[str]) -> Tuple[bool, Optional[str]]:
        """버전 확인 명령 1회 시도."""
        try:
            proc = subprocess.run(cmd, capture_output=True,
                                  timeout=VERSION_CHECK_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired):
            return False, None
        out = proc.stdout.decode("utf-8", errors="replace").strip()
        if proc.returncode == 0 and out:
            return True, out.splitlines()[0]
        return False, None

    def _make_probe_client(self, use_output_format_json: bool) -> ClaudeCliClient:
        """
        프로브 전용 ClaudeCliClient 생성.

        본 실행과 동일한 호출 경로를 쓰되, 타임아웃은 짧게 / 재시도 없음 /
        output-format 플래그만 개별 제어한 별도 설정 사본을 사용.
        """
        probe_config = {
            **self.config,
            "cli": {
                **self.cli_cfg,
                "timeout_seconds": PROBE_TIMEOUT,
                "max_retries": 1,
                "use_output_format_json": use_output_format_json,
            },
        }
        return ClaudeCliClient(probe_config, self.logger)

    def _run_probe(self, client: ClaudeCliClient, result: PreflightResult) -> None:
        """
        프로브 프롬프트 실행 → 인증/인코딩/stdin 방식/응답시간 판정.

        ClaudeCliClient.convert_chunk()을 그대로 사용:
        - "auto" 모드가 subprocess → powershell 순으로 시도하고
          성공한 방식이 client._resolved_method에 캐시됨 → 그 값을 채택
        - 오류 분류(AUTH/RATE_LIMIT 등)도 본 실행과 동일한 로직으로 판정

        Args:
            client: 프로브용 클라이언트
            result: 판정 결과를 채워 넣을 PreflightResult
        """
        probe_chunk = {"chunk_id": "preflight_probe", "text": ""}
        cli_result = client.convert_chunk(probe_chunk, prompt_override=PROBE_PROMPT)

        result.cli_response_time = cli_result.duration_seconds
        result.stdin_method = client._resolved_method

        if cli_result.error_type == CliErrorType.AUTH:
            result.authenticated = False
            result.errors.append(
                "Claude CLI 인증이 필요합니다. 터미널에서 `claude`를 실행해 "
                "로그인한 뒤 다시 시도하세요.")
            return
        if cli_result.error_type == CliErrorType.RATE_LIMIT:
            result.authenticated = True  # 인증은 되어 있으나 한도 상태
            result.errors.append(
                "현재 Pro 사용량 한도에 도달한 상태입니다. 한도 해제 후 실행하세요.")
            return
        if cli_result.error_type == CliErrorType.CLI_NOT_FOUND:
            result.cli_available = False
            result.errors.append("claude 명령 실행에 실패했습니다 (경로 확인 필요).")
            return
        if not cli_result.success:
            result.errors.append(
                f"테스트 프롬프트 실행 실패: {cli_result.error_type.value} "
                f"(exit={cli_result.exit_code}, stderr={(cli_result.stderr or '')[:200]})")
            return

        # 응답 수신 성공 = 인증 정상
        result.authenticated = True

        # 인코딩 판정: 한글 마커 or 한글 자모 포함 여부 + 오염 비율
        # CLI 버전에 따라 마커만 반환하거나 부가 설명을 붙여 반환할 수 있으므로
        # 정확한 마커 포함 또는 한글 유니코드 블록 문자가 하나라도 있으면 통과.
        import re
        output = cli_result.stdout or ""
        marker_ok = PROBE_MARKER in output or bool(re.search(r"[가-힣]", output))
        corruption_ok = cli_result.corruption_ratio <= 0.005
        result.encoding_ok = marker_ok and corruption_ok
        if not result.encoding_ok:
            result.errors.append(
                f"한글 인코딩 검증 실패 (마커 수신: {marker_ok}, "
                f"오염 비율: {cli_result.corruption_ratio:.2%}). "
                "PowerShell/터미널 코드페이지 설정을 확인하세요 (chcp 65001).")

    def _check_output_format_json(self) -> bool:
        """
        --output-format json 지원 여부 테스트.

        지원 판정 기준: 플래그를 붙여 호출했을 때
        (a) 정상 종료하고 (b) raw stdout이 JSON 봉투로 파싱되며
        (c) 봉투에서 result 필드를 꺼낼 수 있어야 함.

        ⚠️ 미지원이어도 예외를 던지지 않는다 — 호출부가 플래그를 False로
        내려 텍스트 모드로 폴백하는 것이 설계 의도.

        Returns:
            bool: 지원 여부
        """
        client = self._make_probe_client(use_output_format_json=True)
        probe_chunk = {"chunk_id": "preflight_json_probe", "text": ""}
        try:
            cli_result = client.convert_chunk(probe_chunk, prompt_override="OK만 출력하세요.")
        except Exception as e:  # 어떤 실패도 "미지원"으로만 처리 (Fallback 구조)
            self.logger.warning("--output-format json 테스트 중 예외: %s", e)
            return False

        if not cli_result.success:
            return False
        raw = (cli_result.raw_stdout or "").strip()
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError:
            return False
        return isinstance(envelope, dict) and "result" in envelope

    def _apply_output_format_fallback(self, result: PreflightResult) -> None:
        """
        검증 결과를 config에 반영 (Fallback 처리).

        - config에서 use_output_format_json: true 요청 + 실제 미지원
          → 플래그를 False로 강제 변경하고 경고만 남김 (에러 아님)
        - 요청이 false였으면 지원 여부와 무관하게 false 유지

        Args:
            result: output_format_json_supported가 채워진 결과
        """
        requested = bool(self.cli_cfg.get("use_output_format_json", False))
        effective = requested and result.output_format_json_supported
        self.cli_cfg["use_output_format_json"] = effective
        if requested and not result.output_format_json_supported:
            result.warnings.append(
                "--output-format json이 요청되었으나 이 CLI 버전에서 지원이 확인되지 "
                "않아 텍스트 모드로 폴백합니다 (use_output_format_json=False).")

    def _check_dictionaries(self) -> bool:
        """
        법률 용어 사전 파일 존재 + JSON 로드 가능 여부.

        Returns:
            bool: 로드 가능 여부
        """
        try:
            with open(self.dictionary_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return isinstance(data, dict) and "terms" in data
        except (OSError, json.JSONDecodeError) as e:
            self.logger.error("사전 로드 실패: %s", e)
            return False

    # ------------------------------------------------------------------
    # 결과 저장
    # ------------------------------------------------------------------

    def _save_result(self, result: PreflightResult) -> None:
        """
        검증 결과를 state/preflight.json에 저장.

        본 실행(Phase 2)에서 stdin_method 등을 재판정 없이 참조할 수 있게 함.
        """
        try:
            self.result_file.parent.mkdir(parents=True, exist_ok=True)
            payload = asdict(result)
            payload["checked_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            with open(self.result_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except OSError as e:
            self.logger.warning("프리플라이트 결과 저장 실패: %s", e)
