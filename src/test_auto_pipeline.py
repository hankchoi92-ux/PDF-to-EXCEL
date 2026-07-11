"""
auto_pipeline.py Dry-run 테스트 (Mock 기반).

실제 PDF/Claude CLI 호출 없이, Phase 0~4 전체 흐름과 Rate Limit 감지 →
대기 → 자동 재개 루프가 끊기지 않고 도는지 검증한다.

- Phase 0(프리플라이트), Phase 1(전처리)은 무거운 외부 의존성(claude CLI,
  실제 PDF)을 가지므로 인스턴스 메서드를 직접 교체(monkeypatch)해 우회한다.
- Phase 2(CLI 호출)는 FakeCliClient로 대체해, 첫 번째 청크의 첫 시도에서
  RATE_LIMIT을 반환하도록 해 대기/재개 루프를 실제로 태운다.
- Phase 3/4(검증, Excel 생성)는 Group 3에서 구현한 실제 validator들과
  ExcelBuilder를 그대로 사용한다 (Mock 아님 — 진짜 통합 검증).
"""

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import yaml

from auto_pipeline import AutoPipeline
from claude_cli_client import CliErrorType, CliResult
from preflight import PreflightResult

TEST_STATE_FILE = "state/_test_auto_pipeline_state.json"
TEST_OUTPUT_DIR = "output/_dryrun_test_pipeline"


def _logger() -> logging.Logger:
    logger = logging.getLogger("auto_pipeline_dryrun")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


def _load_test_config() -> Dict[str, Any]:
    with open(PROJECT_ROOT / "config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    config["state"]["state_file"] = TEST_STATE_FILE
    config["excel"] = dict(config.get("excel", {}))
    config["excel"]["output_dir"] = TEST_OUTPUT_DIR
    config["cli"]["inter_chunk_delay_seconds"] = 0
    return config


def _fake_chunks():
    """Phase 1을 건너뛰기 위한 최소 청크 2개 (각각 문제 1개, 선지 1개)."""
    return [
        {
            "chunk_id": "chunk_001",
            "text": "문1. 계약의 성립요건이 아닌 것은?\n① 청약",
            "hint": {
                "question_range": {"start": 1, "end": 1},
                "options_per_question": 1,
                "option_symbols": "circled",
            },
            "metrics": {},
            "question_range": (1, 1),
        },
        {
            "chunk_id": "chunk_002",
            "text": "문2. 물권이 아닌 것은?\n① 채권",
            "hint": {
                "question_range": {"start": 2, "end": 2},
                "options_per_question": 1,
                "option_symbols": "circled",
            },
            "metrics": {},
            "question_range": (2, 2),
        },
    ]


class FakeCliClient:
    """
    claude_cli_client.ClaudeCliClient를 대체하는 Mock.

    chunk_001의 첫 호출은 RATE_LIMIT을 반환해 파이프라인의 대기/재개
    루프를 실제로 태우고, 이후 모든 호출은 마크다운 펜스로 감싼 JSON을
    성공 응답으로 반환한다 (auto_pipeline의 JSON 안전 추출 유틸리티 검증).
    """

    def __init__(self):
        self.call_counts: Dict[str, int] = {}
        self.rate_limited_once = False

    def run_with_retry(self, chunk: Dict[str, Any],
                       prompt_override: Optional[str] = None
                       ) -> Tuple[bool, Optional[CliResult]]:
        chunk_id = chunk["chunk_id"]
        self.call_counts[chunk_id] = self.call_counts.get(chunk_id, 0) + 1

        if chunk_id == "chunk_001" and not self.rate_limited_once:
            self.rate_limited_once = True
            return False, CliResult(
                success=False, error_type=CliErrorType.RATE_LIMIT,
                rate_limit_reset_at=time.time() + 0.01, exit_code=1,
                stderr="usage limit reached",
            )

        qid = int(chunk_id.split("_")[1])
        payload = {
            "questions": [{
                "id": qid,
                "text": chunk["text"].splitlines()[0],
                "options": [{
                    "num": "①", "text": chunk["text"].splitlines()[1].lstrip("① ").strip(),
                    "correct": True, "explanation": "",
                }],
            }]
        }
        # 마크다운 펜스로 감싸 "순수 JSON 추출 유틸리티"가 실제로 동작하는지 검증
        stdout = "여기 결과입니다:\n```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
        return True, CliResult(success=True, stdout=stdout, exit_code=0, duration_seconds=0.1)


def _cleanup():
    state_path = PROJECT_ROOT / TEST_STATE_FILE
    if state_path.exists():
        state_path.unlink()


def test_full_pipeline_with_rate_limit_recovery():
    """Phase 0~4 전체 흐름 + Rate Limit 대기/재개 루프가 끊기지 않고 완주하는지 확인."""
    _cleanup()
    logger = _logger()
    config = _load_test_config()

    pipeline = AutoPipeline("dummy_not_used.pdf", config, logger)

    # Phase 0/1 우회 (외부 의존성 없이 흐름만 검증)
    def fake_phase_1():
        chunks = _fake_chunks()
        for chunk in chunks:
            pipeline.state_manager.register_chunk(
                chunk["chunk_id"], metadata={"question_range": list(chunk["question_range"])})
        return chunks

    pipeline._phase_0_preflight = lambda: True
    pipeline._phase_1_preprocess = fake_phase_1

    # Phase 2 CLI 클라이언트를 Fake로 교체
    fake_client = FakeCliClient()
    pipeline.cli_client = fake_client

    # Rate Limit 대기 루프를 실제 대기 없이 통과시키기 위해 sleep을 무력화
    pipeline._sleep_fn = lambda seconds: None

    result = pipeline.run()

    assert result.success, f"파이프라인 실패: {result.error_summary}"
    assert result.total_problems == 2, f"문제 수 불일치: {result.total_problems}"
    assert result.auto_confirmed + result.human_review == result.total_problems
    assert "main" in result.output_files
    assert result.output_files["main"].exists()
    print(
        f"  PASS: 파이프라인 성공 (문제 {result.total_problems}개, "
        f"AUTO {result.auto_confirmed} / HUMAN_REVIEW {result.human_review})"
    )

    # Rate Limit 루프가 실제로 태워졌는지 확인 (chunk_001이 2번 호출됨: 실패 1회 + 재개 후 성공 1회)
    assert fake_client.call_counts.get("chunk_001") == 2, fake_client.call_counts
    assert fake_client.call_counts.get("chunk_002") == 1, fake_client.call_counts
    print(f"  PASS: Rate Limit 감지 → 대기 → 재개 루프 확인 (호출 횟수: {fake_client.call_counts})")

    # 상태 파일에 PAUSED_LIMIT을 거쳐 COMPLETED까지 히스토리가 남았는지 확인
    chunk_001_history = [h["state"] for h in pipeline.state_manager.state["chunks"]["chunk_001"]["history"]]
    assert "PAUSED_LIMIT" in chunk_001_history, chunk_001_history
    assert chunk_001_history[-1] == "COMPLETED", chunk_001_history
    print(f"  PASS: chunk_001 상태 이력에 PAUSED_LIMIT 포함 확인: {chunk_001_history}")

    _cleanup()


def test_preflight_failure_raises():
    """프리플라이트 실패 시 즉시 RuntimeError로 중단되어야 함 (청크 생성 낭비 방지)."""
    _cleanup()
    logger = _logger()
    config = _load_test_config()
    pipeline = AutoPipeline("dummy_not_used.pdf", config, logger)

    failed_result = PreflightResult(passed=False, errors=["CLI 미설치"])
    pipeline.preflight.run = lambda: failed_result
    pipeline._phase_1_preprocess = lambda: (_ for _ in ()).throw(
        AssertionError("Phase 0 실패 시 Phase 1이 호출되면 안 됨"))

    try:
        pipeline.run()
        raise AssertionError("RuntimeError가 발생해야 함")
    except RuntimeError as e:
        assert "프리플라이트" in str(e)
        print(f"  PASS: 프리플라이트 실패 → RuntimeError 발생, Phase 1 미실행 확인 ({e})")

    _cleanup()


def test_extract_json_safely_utility():
    """마크다운 펜스가 섞인 응답에서도 순수 JSON을 안전하게 추출하는지 확인."""
    logger = _logger()
    config = _load_test_config()
    pipeline = AutoPipeline("dummy_not_used.pdf", config, logger)

    wrapped = '설명입니다\n```json\n{"questions": []}\n```\n끝.'
    extracted = pipeline._extract_json_safely(wrapped)
    assert extracted == '{"questions": []}', extracted
    print(f"  PASS: 마크다운 펜스 제거 후 순수 JSON 추출 확인: {extracted!r}")

    no_fence = 'prefix {"questions": [{"id": 1}]} suffix'
    extracted2 = pipeline._extract_json_safely(no_fence)
    assert extracted2 == '{"questions": [{"id": 1}]}', extracted2
    print(f"  PASS: 펜스 없는 응답에서도 첫 {{ ~ 마지막 }} 추출 확인: {extracted2!r}")


def main():
    tests = [
        ("Phase 0~4 통합 + Rate Limit 재개 루프", test_full_pipeline_with_rate_limit_recovery),
        ("프리플라이트 실패 → RuntimeError", test_preflight_failure_raises),
        ("JSON 안전 추출 유틸리티", test_extract_json_safely_utility),
    ]
    failed = []
    for name, fn in tests:
        print(f"\n=== {name} ===")
        try:
            fn()
        except AssertionError as e:
            failed.append(name)
            print(f"  FAIL: {e}")

    print("\n" + "=" * 50)
    if failed:
        print(f"실패: {len(failed)}/{len(tests)} - {failed}")
        sys.exit(1)
    print(f"전체 통과: {len(tests)}/{len(tests)}")


if __name__ == "__main__":
    main()
