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
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass

from preflight import Preflight
from state_manager import StateManager, PipelineState
from pdf_extractor import PDFTextExtractor
from local_hint_generator import LocalHintGenerator
from chunk_manager import ChunkManager
from text_metrics import TextMetrics
from local_corrector import LocalCorrector
from claude_cli_client import ClaudeCliClient, CliErrorType, CliResult
from response_parser import ResponseParser
from structure_validator import StructureValidator
from diff_validator import DiffValidator
from term_validator import TermValidator
from confidence_scorer import ConfidenceScorer
from excel_builder import ExcelBuilder

PROJECT_ROOT = Path(__file__).resolve().parent.parent


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
        self.pdf_path = pdf_path
        self.config = config
        self.logger = logger

        state_file = PROJECT_ROOT / config.get("state", {}).get(
            "state_file", "state/pipeline_state.json")
        self.state_manager = StateManager(str(state_file), logger=logger, config=config)

        self.preflight = Preflight(config, logger=logger)
        self.cli_client = ClaudeCliClient(config, logger=logger)
        self.response_parser = ResponseParser(logger=logger)

        dict_path = PROJECT_ROOT / config.get("local_correction", {}).get(
            "dictionary_path", "dictionaries/legal_terms.json")
        self.local_corrector = LocalCorrector(str(dict_path), config=config, logger=logger)

        self.structure_validator = StructureValidator(logger=logger)
        self.diff_validator = DiffValidator(logger=logger)
        self.term_validator = TermValidator(str(dict_path), logger=logger)
        self.confidence_scorer = ConfidenceScorer(logger=logger)

        output_dir = PROJECT_ROOT / config.get("excel", {}).get("output_dir", "output")
        self.excel_builder = ExcelBuilder(str(output_dir), logger=logger)

        # 테스트에서 실제 대기 없이 흐름만 검증할 수 있도록 주입 가능하게 분리
        self._sleep_fn: Callable[[float], None] = time.sleep
        self._start_time: Optional[float] = None

    def run(self) -> PipelineResult:
        """
        Phase 0~4 전체 실행.

        Returns:
            PipelineResult: 파이프라인 실행 결과

        Raises:
            Exception: 각 Phase의 실패 (상세 로깅됨)
        """
        self._start_time = time.monotonic()
        self.logger.info("=== v6 자동 파이프라인 시작: %s ===", self.pdf_path)

        self._phase_0_preflight()

        chunks = self._phase_1_preprocess()

        phase2_result = self._phase_2_convert(chunks)
        if not phase2_result["parsed_chunks"]:
            error_summary = (
                f"Phase 2에서 성공한 청크가 하나도 없음 "
                f"(실패 {len(phase2_result['failed_chunks'])}개)"
            )
            self.logger.error(error_summary)
            return PipelineResult(
                success=False, phase="PHASE_2", total_problems=0,
                auto_confirmed=0, human_review=0, output_files={},
                error_summary=error_summary,
            )

        validation_result = self._phase_3_validate(phase2_result, chunks)
        output_files = self._phase_4_excel(validation_result)

        duration = time.monotonic() - self._start_time
        self.logger.info(
            "=== 파이프라인 완료 (%.1fs): 문제 %d개 (AUTO %d / HUMAN_REVIEW %d) ===",
            duration, len(validation_result["all_questions"]),
            len(validation_result["auto_confirmed"]), len(validation_result["human_review"]),
        )

        return PipelineResult(
            success=True, phase="PHASE_4",
            total_problems=len(validation_result["all_questions"]),
            auto_confirmed=len(validation_result["auto_confirmed"]),
            human_review=len(validation_result["human_review"]),
            output_files=output_files,
        )

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
        self.logger.info("[Phase 0] 프리플라이트 검증")
        result = self.preflight.run()
        if not result.passed:
            raise RuntimeError(
                "프리플라이트 검증 실패:\n" + result.summary()
            )
        self.state_manager.transition("global", PipelineState.PREPARED)
        return True

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
        self.logger.info("[Phase 1] PDF 전처리 + 동적 청킹 시작")

        with PDFTextExtractor(self.pdf_path) as extractor:
            blocks = extractor.extract_text_with_positions()
            full_text = extractor.extract_full_text()
            patterns = extractor.detect_question_patterns(blocks)
            option_symbols = extractor.detect_option_symbols(blocks)
        self.state_manager.transition("global", PipelineState.TEXT_EXTRACTED)

        chunk_cfg = self.config.get("chunking", {})
        chunk_manager = ChunkManager(
            max_tokens_per_chunk=int(chunk_cfg.get("max_tokens_per_chunk", 3500)),
            config=self.config, logger=self.logger,
        )
        chunks = chunk_manager.create_chunks(full_text, patterns)
        manifest = chunk_manager.create_manifest(chunks)
        chunk_manager.save_manifest(manifest, str(PROJECT_ROOT / "chunks" / "chunk_manifest.json"))
        chunk_manager.save_chunk_texts(chunks, str(PROJECT_ROOT / "chunks" / "texts"))

        text_metrics = TextMetrics()
        hint_generator = LocalHintGenerator()
        hint_dir = PROJECT_ROOT / "chunks" / "hints"

        for chunk in chunks:
            q_start, q_end = chunk["question_range"]
            chunk_patterns = [p for p in patterns if q_start <= p["question_id"] <= q_end]
            metrics = text_metrics.measure(chunk["text"])
            hint = hint_generator.generate_hint(chunk["text"], chunk_patterns, option_symbols, metrics)
            hint_generator.save_hint(hint, str(hint_dir / f"{chunk['chunk_id']}_hint.json"))
            chunk["hint"] = hint
            chunk["metrics"] = metrics

            corrected_text, corrections = self.local_corrector.pre_correct(
                chunk["text"], chunk_id=chunk["chunk_id"])
            chunk["text"] = corrected_text
            chunk["pre_corrections"] = corrections

            self.state_manager.register_chunk(
                chunk["chunk_id"], metadata={"question_range": list(chunk["question_range"])})

        self.state_manager.transition("global", PipelineState.HINTS_GENERATED)
        self.state_manager.transition("global", PipelineState.CHUNKS_CREATED)
        self.logger.info("[Phase 1] 완료: 청크 %d개, 문제 %d개 감지", len(chunks), len(patterns))
        return chunks

    def _phase_2_convert(self, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Phase 2: Claude CLI 서브프로세스 자동 호출 (v6 핵심).

        청크별 순차 처리:
        1. 프롬프트 조립 (claude_cli_client.build_prompt)
        2. `claude -p` 서브프로세스 호출 (재시도 정책 포함)
        3. stdout에서 순수 JSON 추출 및 파싱 (마크다운 펜스 대응)
        4. 파싱 실패 시 더 엄격한 프롬프트로 1회 재시도
        5. Rate Limit 감지 시 state_manager.pause_for_limit() 후 대기, 자동 재개

        상태 전이: CHUNK_READY → SENT → RESPONDED → PARSED → (Phase 3에서 VALIDATED/COMPLETED)

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
        self.logger.info("[Phase 2] Claude CLI 변환 시작")
        chunk_by_id = {c["chunk_id"]: c for c in chunks}
        on_limit = self.config.get("cli", {}).get("on_limit", "wait")
        inter_delay = float(self.config.get("cli", {}).get("inter_chunk_delay_seconds", 0))

        parsed_chunks: List[Dict[str, Any]] = []
        failed_chunks: List[Dict[str, Any]] = []

        pending_ids: List[str] = self.state_manager.get_resumable_chunks()
        processed = 0
        total = len(pending_ids)

        while pending_ids:
            chunk_id = pending_ids.pop(0)
            chunk = chunk_by_id.get(chunk_id)
            if chunk is None:
                self.logger.warning("[%s] 이번 실행의 청크 목록에 없음 (이전 상태 잔여) → 건너뜀", chunk_id)
                continue

            processed += 1
            self.logger.info("[Phase 2] (%d/%d) %s 처리 중", processed, total, chunk_id)
            self._update_state(chunk_id, PipelineState.SENT)

            success, cli_result = self.cli_client.run_with_retry(chunk)

            if not success and cli_result and cli_result.error_type == CliErrorType.RATE_LIMIT:
                self.state_manager.pause_for_limit(chunk_id, reset_at=cli_result.rate_limit_reset_at)
                if on_limit == "stop":
                    self.logger.error(
                        "[%s] 사용량 한도 도달, on_limit=stop 설정으로 파이프라인 중단", chunk_id)
                    break
                resumed_ids = self.state_manager.wait_and_resume(sleep_fn=self._sleep_fn)
                # 한도 대기 중 재개된 청크(이번 청크 포함)를 다시 앞쪽에 이어붙여 처리
                pending_ids = resumed_ids + [cid for cid in pending_ids if cid not in resumed_ids]
                total = processed + len(pending_ids)
                continue

            if not success:
                error_type = cli_result.error_type.value if cli_result else "unknown"
                self._update_state(chunk_id, PipelineState.FAILED, {"error_type": error_type})
                failed_chunks.append({"chunk_id": chunk_id, "error": error_type})
                if cli_result and cli_result.error_type in (CliErrorType.AUTH, CliErrorType.CLI_NOT_FOUND):
                    raise RuntimeError(
                        f"[{chunk_id}] 복구 불가능한 CLI 오류({error_type})로 파이프라인을 중단합니다."
                    )
                continue

            self._update_state(chunk_id, PipelineState.RESPONDED)

            ok, data, errors = self.response_parser.parse_and_validate(cli_result.stdout or "")
            if not ok:
                self.logger.warning("[%s] JSON 파싱 실패(%s), 엄격 프롬프트로 재시도", chunk_id, errors)
                retry_prompt = self.cli_client._create_retry_prompt(chunk, "; ".join(errors))
                success2, cli_result2 = self.cli_client.run_with_retry(chunk, prompt_override=retry_prompt)
                if success2 and cli_result2:
                    ok, data, errors = self.response_parser.parse_and_validate(cli_result2.stdout or "")

            if not ok:
                self._update_state(chunk_id, PipelineState.FAILED,
                                   {"error_type": "PARSE_ERROR", "detail": "; ".join(errors)})
                failed_chunks.append({"chunk_id": chunk_id, "error": "PARSE_ERROR", "detail": errors})
                continue

            post_issues = self.local_corrector.post_verify(data, chunk_id=chunk_id)
            if post_issues:
                self.logger.info("[%s] 2차 용어 검증 의심 항목 %d건", chunk_id, len(post_issues))

            self._update_state(chunk_id, PipelineState.PARSED)
            chunk["parsed"] = data
            parsed_chunks.append(chunk)

            if inter_delay > 0 and pending_ids:
                self._sleep_fn(inter_delay)

        total_problems = sum(len(c["parsed"].get("questions", [])) for c in parsed_chunks)
        self.logger.info(
            "[Phase 2] 완료: 성공 %d개 / 실패 %d개, 문제 %d개",
            len(parsed_chunks), len(failed_chunks), total_problems,
        )
        return {
            "success": len(parsed_chunks) > 0,
            "parsed_chunks": parsed_chunks,
            "failed_chunks": failed_chunks,
            "total_problems": total_problems,
        }

    def _extract_json_safely(self, response_text: str) -> Optional[str]:
        """
        Claude 응답 텍스트에서 마크다운 펜스 등을 제거하고 순수 JSON 문자열만
        안전하게 추출하는 유틸리티.

        response_parser.extract_json_from_text()를 그대로 위임하며,
        Phase 2 재시도/로깅 등에서 파싱 이전 단계의 원문을 미리 살펴봐야 할
        때 이 메서드를 사용한다.

        Args:
            response_text: Claude CLI stdout 원문

        Returns:
            str|None: 추출된 JSON 문자열, 추출 실패 시 None
        """
        return self.response_parser.extract_json_from_text(response_text)

    def _phase_3_validate(
        self,
        parsed_data: Dict[str, Any],
        chunks: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Phase 3: 검증 및 신뢰도 점수 부여.

        다층 검증(청크 단위):
        - 구조 검증 (문제번호 연속성, 선지 개수 일관성 등)
        - Diff 검증 (원본 대비 누락/변형 감지)
        - 법률 용어 2차 검증
        - 신뢰도 점수 계산 → 해당 청크의 모든 문제에 동일하게 부여

        분류: AUTO (≥95%) | HUMAN_REVIEW (<95%)

        Args:
            parsed_data: Phase 2 결과 ({'parsed_chunks', 'failed_chunks', ...})
            chunks: Phase 1 청크 (미사용 — parsed_chunks가 hint/text를 이미 포함)

        Returns:
            Dict: {
                'all_questions': [...],
                'auto_confirmed': [...],
                'human_review': [...],
                'statistics': {...},
            }
        """
        self.logger.info("[Phase 3] 검증 및 신뢰도 점수 계산 시작")
        parsed_chunks = parsed_data.get("parsed_chunks", [])

        all_questions: List[Dict[str, Any]] = []
        error_breakdown: Dict[str, int] = {}

        for chunk in parsed_chunks:
            chunk_id = chunk["chunk_id"]
            data = chunk.get("parsed", {}) or {}
            hint = chunk.get("hint", {}) or {}
            original_text = chunk.get("text", "")

            structure_issues = self.structure_validator.validate(data, hint)
            diff_issues = self.diff_validator.validate(original_text, data)
            term_issues = self.term_validator.verify(data)

            for issue in (*structure_issues, *diff_issues, *term_issues):
                error_breakdown[issue.issue_type] = error_breakdown.get(issue.issue_type, 0) + 1

            score = self.confidence_scorer.calculate({
                "structure_issues": structure_issues,
                "diff_issues": diff_issues,
                "term_issues": term_issues,
            })

            for q in data.get("questions", []):
                augmented = dict(q)
                augmented["confidence"] = score["overall_score"]
                augmented["status"] = score["classification"]
                augmented["chunk_id"] = chunk_id
                all_questions.append(augmented)

            self._update_state(chunk_id, PipelineState.VALIDATED)
            self._update_state(chunk_id, PipelineState.COMPLETED, {
                "confidence": score["overall_score"], "classification": score["classification"],
            })

        auto_confirmed = [q for q in all_questions if q["status"] == "AUTO"]
        human_review = [q for q in all_questions if q["status"] == "HUMAN_REVIEW"]
        duration = time.monotonic() - self._start_time if self._start_time else 0.0

        statistics = {
            "total_problems": len(all_questions),
            "auto_confirmed_ratio": (len(auto_confirmed) / len(all_questions)) if all_questions else 0.0,
            "human_review_ratio": (len(human_review) / len(all_questions)) if all_questions else 0.0,
            "error_breakdown": error_breakdown,
            "total_duration_seconds": round(duration, 1),
            "failed_chunks": len(parsed_data.get("failed_chunks", [])),
        }

        self.logger.info(
            "[Phase 3] 완료: 문제 %d개 (AUTO %d / HUMAN_REVIEW %d)",
            len(all_questions), len(auto_confirmed), len(human_review),
        )
        return {
            "all_questions": all_questions,
            "auto_confirmed": auto_confirmed,
            "human_review": human_review,
            "statistics": statistics,
        }

    def _phase_4_excel(self, validation_result: Dict[str, Any]) -> Dict[str, Path]:
        """
        Phase 4: Excel 생성.

        3개 시트: 전체 문제 / 검토 필요 / 변환 통계.

        Args:
            validation_result: Phase 3 결과

        Returns:
            Dict[str, Path]: 생성된 Excel 파일 경로 {'main': Path('output/최종_문제집.xlsx')}
        """
        self.logger.info("[Phase 4] Excel 생성 시작")
        output_files = self.excel_builder.create_all_sheets(
            validation_result["all_questions"], validation_result)
        self.logger.info("[Phase 4] 완료: %s", output_files)
        return output_files

    def _update_state(self, chunk_id: str, state: Any, metadata: Optional[Dict] = None) -> None:
        """
        상태 머신 업데이트.

        Args:
            chunk_id: 청크 ID
            state: 새로운 상태 (PipelineState 또는 문자열)
            metadata: 추가 정보 (오류, 소요시간, 재시도 횟수 등)
        """
        self.state_manager.transition(chunk_id, state, metadata)
