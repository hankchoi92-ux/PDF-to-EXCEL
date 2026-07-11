"""
메인 진입점 (CLI 인터페이스)

법학 문제집 PDF → Excel 변환 자동화 파이프라인의 CLI 진입점.
- Phase 0: 프리플라이트 (CLI 설치/인증 확인)
- Phase 1~4: 자동 파이프라인 실행 (AutoPipeline, 아직 스켈레톤 - Group 3/4 예정)
- --dry-run: Phase 1(전처리)만 실행해 pdf_extractor → chunk_manager →
  local_hint_generator → local_corrector 데이터 흐름을 검증 (Claude 호출 없음)
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

# src/ 디렉토리를 sys.path에 명시적으로 추가해, 어떤 작업 디렉토리에서
# 실행하든(`python src/main.py`, `python -m src.main` 등) 형제 모듈의
# 평면 import(`from pdf_extractor import ...`)가 항상 성공하도록 한다.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from exceptions import ProjectError  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def setup_logging(config: Dict[str, Any]) -> logging.Logger:
    """
    로깅 설정 초기화.

    콘솔(stdout)과 config.logging.log_file(기본 logs/conversion.log)
    양쪽에 동시에 기록한다.

    Args:
        config: config.yaml 로드 결과

    Returns:
        logging.Logger: 설정된 로거
    """
    log_cfg = config.get("logging", {})
    level_name = str(log_cfg.get("level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)

    logger = logging.getLogger("pdf2excel")
    logger.setLevel(level)
    logger.handlers.clear()
    logger.propagate = False

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logger.addHandler(console)

    log_file = PROJECT_ROOT / log_cfg.get("log_file", "logs/conversion.log")
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except OSError as e:
        logger.warning("로그 파일 핸들러 초기화 실패 (%s), 콘솔 로그만 사용", e)

    return logger


def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    """
    config.yaml 로드.

    Args:
        config_path: 설정 파일 경로 (상대 경로면 프로젝트 루트 기준)

    Returns:
        dict: 파싱된 설정

    Raises:
        FileNotFoundError: 설정 파일 없음
        yaml.YAMLError: YAML 파싱 오류
    """
    path = Path(config_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.exists():
        raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {path}")
    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config or {}


def validate_input_pdf(pdf_path: str) -> Path:
    """
    입력 PDF 파일 검증.

    Args:
        pdf_path: PDF 파일 경로 (상대 경로면 프로젝트 루트 기준)

    Returns:
        Path: 검증된 절대 경로

    Raises:
        FileNotFoundError: 파일 없음
        ValueError: PDF가 아닌 파일 (확장자 기준)
    """
    path = Path(pdf_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.exists():
        raise FileNotFoundError(f"PDF 파일을 찾을 수 없습니다: {path}")
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"PDF 파일이 아닙니다 (확장자 .pdf 아님): {path}")
    return path.resolve()


def run_phase1_dry_run(pdf_path: str, config: Dict[str, Any],
                       logger: logging.Logger) -> Dict[str, Any]:
    """
    Phase 1 데이터 흐름 Dry-run.

    pdf_extractor → chunk_manager → local_hint_generator → local_corrector로
    이어지는 단방향 경로를 실제 PDF로 실행하고, v6 설계 경로
    (chunks/texts/, chunks/hints/, chunks/chunk_manifest.json,
    logs/corrections/)에 중간 산출물을 저장한다. Claude CLI는 호출하지 않는다.

    Args:
        pdf_path: 검증된 PDF 경로
        config: config.yaml 로드 결과
        logger: 로거

    Returns:
        Dict: 각 단계 결과 요약

    Raises:
        ProjectError: 전처리 파이프라인 중 발생한 프로젝트 전용 예외
            (PDFExtractionError, NoQuestionPatternsFoundError 등)
    """
    from chunk_manager import ChunkManager
    from local_corrector import LocalCorrector
    from local_hint_generator import LocalHintGenerator
    from pdf_extractor import PDFTextExtractor
    from text_metrics import TextMetrics

    logger.info("[Dry-run] Phase 1 데이터 흐름 검증 시작: %s", pdf_path)

    # 1) pdf_extractor
    with PDFTextExtractor(pdf_path) as extractor:
        blocks = extractor.extract_text_with_positions()
        full_text = extractor.extract_full_text()
        patterns = extractor.detect_question_patterns(blocks)
        option_symbols = extractor.detect_option_symbols(blocks)
        page_count = extractor.get_page_count()
    logger.info(
        "[Dry-run] 1/4 pdf_extractor: 블록 %d개, 문제 %d개 감지, 선지유형=%s, 전체 %d페이지",
        len(blocks), len(patterns), option_symbols, page_count,
    )

    # 2) chunk_manager
    chunk_cfg = config.get("chunking", {})
    chunk_manager = ChunkManager(
        max_tokens_per_chunk=int(chunk_cfg.get("max_tokens_per_chunk", 3500)),
        config=config, logger=logger,
    )
    chunks = chunk_manager.create_chunks(full_text, patterns)
    manifest = chunk_manager.create_manifest(chunks)
    manifest_path = PROJECT_ROOT / "chunks" / "chunk_manifest.json"
    chunk_manager.save_manifest(manifest, str(manifest_path))
    saved_texts = chunk_manager.save_chunk_texts(chunks, str(PROJECT_ROOT / "chunks" / "texts"))
    logger.info(
        "[Dry-run] 2/4 chunk_manager: 청크 %d개 생성 (%s), 총 추정 토큰 %d, 저장 %d개 → %s",
        len(chunks), ", ".join(c["chunk_id"] for c in chunks),
        manifest["total_tokens_estimated"], len(saved_texts), manifest_path,
    )

    # 3) local_hint_generator (+ text_metrics)
    text_metrics = TextMetrics()
    hint_generator = LocalHintGenerator()
    hint_dir = PROJECT_ROOT / "chunks" / "hints"
    hint_paths = []
    for chunk in chunks:
        q_start, q_end = chunk["question_range"]
        chunk_patterns = [p for p in patterns if q_start <= p["question_id"] <= q_end]
        metrics = text_metrics.measure(chunk["text"])
        hint = hint_generator.generate_hint(
            chunk["text"], chunk_patterns, option_symbols, metrics
        )
        hint_path = hint_dir / f"{chunk['chunk_id']}_hint.json"
        hint_generator.save_hint(hint, str(hint_path))
        hint_paths.append(hint_path)
        chunk["_hint"] = hint  # 다음 단계(보정)에서 재사용하지는 않지만 요약 출력용으로 보관
    logger.info(
        "[Dry-run] 3/4 local_hint_generator: 힌트 %d개 생성 → %s", len(hint_paths), hint_dir
    )

    # 4) local_corrector
    dict_path = PROJECT_ROOT / config.get("local_correction", {}).get(
        "dictionary_path", "dictionaries/legal_terms.json"
    )
    corrector = LocalCorrector(str(dict_path), config=config, logger=logger)
    total_corrections = 0
    correction_summary = []
    for chunk in chunks:
        _corrected_text, corrections = corrector.pre_correct(
            chunk["text"], chunk_id=chunk["chunk_id"]
        )
        total_corrections += len(corrections)
        for c in corrections:
            correction_summary.append(f"{chunk['chunk_id']}: {c['original']}→{c['corrected']}")
    logger.info(
        "[Dry-run] 4/4 local_corrector: 총 %d건 보정 (%s) → logs/corrections/",
        total_corrections, "; ".join(correction_summary) if correction_summary else "없음",
    )

    logger.info(
        "[Dry-run] Phase 1 전체 경로 정상 완료 (pdf_extractor → chunk_manager → "
        "local_hint_generator → local_corrector)"
    )

    return {
        "pdf_path": str(pdf_path),
        "page_count": page_count,
        "blocks": len(blocks),
        "questions_detected": len(patterns),
        "option_symbols": option_symbols,
        "chunks": len(chunks),
        "total_tokens_estimated": manifest["total_tokens_estimated"],
        "hints_generated": len(hint_paths),
        "corrections_applied": total_corrections,
        "manifest_path": str(manifest_path),
    }


def _generate_sample_pdf(output_path: Path) -> None:
    """
    --dry-run 실행 시 입력 PDF가 주어지지 않으면 사용할 합성 샘플 PDF 생성.

    fitz.TextWriter + 시스템 폰트(맑은 고딕)로 실제 한글이 PyMuPDF로 정확히
    왕복 추출되는 PDF를 만든다(내장 CJK 폰트는 ToUnicode 매핑이 없어
    추출 시 깨지므로 사용하지 않음). 문제 4개, 순환 검증용 오타("게약")
    1개, 페이지 경계를 넘는 청크 상황을 포함한다.

    Args:
        output_path: 생성할 PDF 경로
    """
    import fitz

    font_candidates = [
        r"C:\Windows\Fonts\malgun.ttf",
        r"C:\Windows\Fonts\gulim.ttc",
        r"C:\Windows\Fonts\batang.ttc",
    ]
    font_file = next((f for f in font_candidates if Path(f).exists()), None)
    if not font_file:
        raise ProjectError(
            "샘플 PDF 생성용 한글 폰트를 찾을 수 없습니다 "
            f"(시도한 경로: {font_candidates}). --dry-run에 직접 PDF 경로를 지정하세요."
        )
    font = fitz.Font(fontfile=font_file)

    pages_content = [
        [
            "법학 개론 문제집 - 1장 계약의 성립",
            "",
            "문1. 게약의 성립요건으로 옳지 않은 것은?",
            "① 청약",
            "② 승낙",
            "③ 대가 지급",
            "④ 상대방 의사능력",
            "[해설] 정답은 ④. 대가 지급은 채권발생의 원인이지 계약의 성립요건이 아니다.",
            "",
            "문2. 물권과 채권의 차이에 관한 설명으로 옳은 것은?",
            "① 물권은 대세적 권리이다",
            "② 채권은 대세적 권리이다",
            "③ 물권은 특정인에게만 주장 가능하다",
            "④ 채권은 모든 사람에게 주장 가능하다",
            "[해설] 정답은 ①. 물권은 누구에게나 주장할 수 있는 대세권이다.",
        ],
        [
            "문3. 법인의 성립에 관한 설명으로 옳은 것은?",
            "① 법인은 정관 작성만으로 성립한다",
            "② 법인은 설립등기를 완료해야 성립한다",
            "③ 법인은 대표자 선임만으로 성립한다",
            "④ 법인은 사원총회 결의만으로 성립한다",
            "[해설] 정답은 ②. 법인은 설립등기를 통해 성립한다.",
            "",
            "문4. 상속에 관한 설명으로 옳지 않은 것은?",
            "① 상속은 피상속인의 사망으로 개시된다",
            "② 상속인은 상속포기를 할 수 있다",
            "③ 유언은 상속에 우선하지 않는다",
            "④ 법정상속분은 법률로 정해진다",
            "[해설] 정답은 ③. 유언은 법정상속에 우선한다.",
        ],
    ]

    doc = fitz.open()
    for lines in pages_content:
        page = doc.new_page()
        tw = fitz.TextWriter(page.rect)
        y = 72
        for line in lines:
            if line:
                tw.append((72, y), line, font=font, fontsize=11)
            y += 18
        tw.write_text(page)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    doc.close()


def run_pipeline(pdf_path: str, config: Dict[str, Any], logger: logging.Logger) -> int:
    """
    전체 파이프라인 실행 (Phase 0~4).

    AutoPipeline(Phase 0 프리플라이트 + Phase 2 Claude 호출 + Phase 3 검증 +
    Phase 4 Excel 생성)은 Group 3/4에서 구현 예정이다. 현재는 Phase 1까지만
    실제 로직이 있으므로, 전체 실행 요청은 안내 메시지와 함께 명시적으로
    미구현임을 알린다 (조용히 아무 일도 안 하는 것을 방지).

    Args:
        pdf_path: 입력 PDF 경로
        config: 설정
        logger: 로거

    Returns:
        int: 종료 코드 (0=성공, >0=실패)
    """
    logger.error(
        "전체 파이프라인(Phase 0~4)은 아직 구현되지 않았습니다 "
        "(Claude CLI 자동 호출/검증/Excel 생성은 Group 3~4 예정). "
        "현재는 `--dry-run`으로 Phase 1 전처리 경로만 검증할 수 있습니다: %s",
        pdf_path,
    )
    return 2


def main() -> int:
    """
    CLI 메인 함수.

    Returns:
        int: 종료 코드
    """
    parser = argparse.ArgumentParser(
        description="법학 문제집 PDF → Excel 변환 자동화 (v6)"
    )
    parser.add_argument("pdf", nargs="?", help="입력 PDF 경로")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Phase 1(전처리) 데이터 흐름만 검증하고 종료 (Claude 호출 없음). "
             "PDF 미지정 시 합성 샘플 PDF를 자동 생성",
    )
    parser.add_argument("--config", default="config.yaml", help="config.yaml 경로")
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except (FileNotFoundError, yaml.YAMLError) as e:
        print(f"설정 로드 실패: {e}", file=sys.stderr)
        return 1

    logger = setup_logging(config)

    if args.dry_run:
        pdf_path: Optional[str] = args.pdf
        if not pdf_path:
            sample_path = PROJECT_ROOT / "input" / "sample_problems.pdf"
            try:
                _generate_sample_pdf(sample_path)
            except ProjectError as e:
                logger.error("[Dry-run] 샘플 PDF 생성 실패: %s", e)
                return 1
            pdf_path = str(sample_path)
            logger.info("[Dry-run] 입력 PDF 미지정 → 합성 샘플 PDF 생성: %s", sample_path)

        try:
            validated = validate_input_pdf(pdf_path)
            summary = run_phase1_dry_run(str(validated), config, logger)
        except (FileNotFoundError, ValueError) as e:
            logger.error("[Dry-run] 입력 검증 실패: %s", e)
            return 1
        except ProjectError as e:
            logger.error("[Dry-run] Phase 1 실행 실패: %s", e)
            return 1

        logger.info("[Dry-run] 요약: %s", json.dumps(summary, ensure_ascii=False))
        return 0

    if not args.pdf:
        print("PDF 경로를 지정하세요 (또는 --dry-run으로 샘플 검증을 실행하세요).",
              file=sys.stderr)
        return 1

    try:
        validated = validate_input_pdf(args.pdf)
    except (FileNotFoundError, ValueError) as e:
        logger.error(str(e))
        return 1

    return run_pipeline(str(validated), config, logger)


if __name__ == "__main__":
    sys.exit(main())
