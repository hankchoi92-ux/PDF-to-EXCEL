"""
pdf_extractor.py 패턴 인식 패치 단위 테스트.

1. "문N" (구분자 없음, "1 문65"류 아티팩트 포함) 신규 인식 확인
2. 기존 "문N.", "(N)", "N." 등 형식이 계속 인식되는지(회귀 없음) 확인
3. 완화된 수열 검증(_is_monotonic_sequence) - 발췌 문서(65번부터 시작)와
   일부 역전이 섞인 수열을 정상 통과시키는지 확인
4. 실제 sample(65-67).pdf로 end-to-end 감지 확인 (파일이 있을 때만)
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pdf_extractor import PDFTextExtractor, QUESTION_PATTERNS, OCR_LOOSE_QUESTION_PATTERNS

SAMPLE_PDF = PROJECT_ROOT / "sample" / "sample(65-67).pdf"


def _blocks_from_lines(lines_per_page):
    """테스트용 blocks 구조 생성 (실제 PyMuPDF 없이 순수 딕셔너리로 구성)."""
    blocks = []
    block_id = 0
    for page, lines in enumerate(lines_per_page):
        for text in lines:
            blocks.append({
                "page": page, "text": text,
                "bbox": (0.0, 0.0, 0.0, 0.0), "font_size": 10.0, "block_id": block_id,
            })
            block_id += 1
    return blocks


def _detect(lines_per_page):
    """PDFTextExtractor.__init__ 없이(파일 불필요) detect_question_patterns 단독 호출."""
    extractor = PDFTextExtractor.__new__(PDFTextExtractor)  # 파일 오픈 없이 인스턴스 생성
    blocks = _blocks_from_lines(lines_per_page)
    return extractor.detect_question_patterns(blocks)


def test_bare_question_number_with_artifact_prefix():
    """"1 문65"처럼 장식 숫자 아티팩트가 앞에 붙은 구분자 없는 형식 인식."""
    lines = [
        ["제0절 1 도 급", "1 문65"],
        ["1 문66", "도급, 위임에 관한 설명 중 옳은 것은?"],
        ["1 문67", "도급계약에 관한 설명으로 옳지 않은 것은?"],
    ]
    patterns = _detect(lines)
    ids = [p["question_id"] for p in patterns]
    assert ids == [65, 66, 67], ids
    print(f"  PASS: 구분자 없는 '문N' + 아티팩트 접두 인식 확인: {ids}")


def test_bare_question_number_without_prefix():
    """접두 아티팩트 없이 "문N"만 있는 경우도 인식."""
    lines = [["문1", "본문 내용"], ["문2", "본문 내용"], ["문3", "본문 내용"]]
    patterns = _detect(lines)
    ids = [p["question_id"] for p in patterns]
    assert ids == [1, 2, 3], ids
    print(f"  PASS: 접두 없는 '문N' 인식 확인: {ids}")


def test_existing_dot_format_still_works():
    """기존 "문1." "문2)" 형식이 여전히 정상 인식되는지 회귀 확인."""
    lines = [
        ["문1. 계약의 성립요건이 아닌 것은?"],
        ["문2) 물권과 채권의 차이는?"],
        ["문3. 법인의 성립요건은?"],
    ]
    patterns = _detect(lines)
    ids = [p["question_id"] for p in patterns]
    assert ids == [1, 2, 3], ids
    assert all(p["format"] == "문{N}." for p in patterns)
    print(f"  PASS: 기존 '문N.'/'문N)' 형식 회귀 없음 확인: {ids}")


def test_existing_paren_and_bare_dot_still_work():
    """기존 '(N)', 'N.' 형식도 영향받지 않는지 확인 (question_dot 매칭 실패 시에만 시도됨)."""
    paren_lines = [["(1) 문제 내용입니다"], ["(2) 문제 내용입니다"], ["(3) 문제 내용입니다"]]
    patterns = _detect(paren_lines)
    ids = [p["question_id"] for p in patterns]
    assert ids == [1, 2, 3], ids
    assert patterns[0]["format"] == "({N})"
    print(f"  PASS: 기존 '(N)' 형식 회귀 없음 확인: {ids}")

    bare_lines = [["1. 문제 내용입니다"], ["2. 문제 내용입니다"], ["3. 문제 내용입니다"]]
    patterns2 = _detect(bare_lines)
    ids2 = [p["question_id"] for p in patterns2]
    assert ids2 == [1, 2, 3], ids2
    print(f"  PASS: 기존 'N.' 형식 회귀 없음 확인: {ids2}")


def test_no_false_positive_on_prose_mentions():
    """본문 중 '문항', '질문', '본문' 등 단어가 오탐되지 않는지 확인."""
    lines = [
        ["이 문항은 판례에 따라 다르게 해석될 수 있다."],
        ["질문 1개 있습니다 다음 줄로 이어집니다."],
        ["본문 내용을 참고하시기 바랍니다."],
        ["주문하다라는 표현이 등장합니다."],
    ]
    patterns = _detect(lines)
    assert patterns == [], patterns
    print("  PASS: 본문 중 '문' 포함 단어 오탐 없음 확인")


def test_monotonic_sequence_tolerates_excerpt_start():
    """발췌본처럼 65번부터 시작하는 수열도 더 이상 거부되지 않는지 확인."""
    numbers = [65, 66, 67, 68]
    assert PDFTextExtractor._is_monotonic_sequence(numbers) is True
    print(f"  PASS: 65번부터 시작하는 수열 통과 확인: {numbers}")


def test_monotonic_sequence_tolerates_single_ocr_glitch():
    """OCR 오인식으로 한 쌍이 역전돼도(60% 이상 증가) 통과하는지 확인."""
    # (65,66) 증가, (66,64) 역전(OCR 오인식 가정), (64,68) 증가 → 2/3 ≈ 0.667 >= 0.6
    numbers = [65, 66, 64, 68]
    assert PDFTextExtractor._is_monotonic_sequence(numbers) is True
    print(f"  PASS: 역전 1건 포함 수열도 통과 확인 (ratio=2/3): {numbers}")


def test_monotonic_sequence_still_rejects_random_numbers():
    """무작위/대부분 역전되는 숫자열은 여전히 거부되어야 함(과도한 완화 아님)."""
    numbers = [10, 3, 55, 2, 900, 1]
    assert PDFTextExtractor._is_monotonic_sequence(numbers) is False
    print(f"  PASS: 무작위 숫자열은 여전히 거부됨: {numbers}")


def test_ocr_loose_pattern_requires_explicit_opt_in():
    """OCR_LOOSE_QUESTION_PATTERNS는 extra_patterns로 명시할 때만 적용되는지 확인.

    실측(물권기출 문1-문19.pdf의 Tesseract 재OCR 결과) 사례: 문제 번호 앞에
    OCR이 장식/아이콘을 잡음 한두 글자로 오인식("| 문3", "훈 문9")하거나
    그 잡음과 "문" 사이에 공백이 없고("|문4"), 원래는 별개 레이아웃이었던
    텍스트(연도 등)가 같은 줄에 큰 공백을 두고 붙어버리는("문1 ... 22년
    변호사시험") 경우가 있다. 기본 QUESTION_PATTERNS만으로는 이런 잡음을
    감지하지 못해야 하고(회귀 없음), extra_patterns로 명시했을 때만
    감지되어야 한다.
    """
    lines = [
        ["1 문1                                                      22년 변호사시험"],
        ["| 문 3                                                      26년 변호사시험"],
        ["|문4"],
        ["훈 문 9"],
    ]
    blocks = _blocks_from_lines(lines)
    extractor = PDFTextExtractor.__new__(PDFTextExtractor)

    default_patterns = extractor.detect_question_patterns(blocks)
    assert default_patterns == [], default_patterns
    print("  PASS: extra_patterns 없이는 OCR 잡음 섞인 형식이 감지되지 않음(기존 동작 보존)")

    loose_patterns = extractor.detect_question_patterns(
        blocks, extra_patterns=OCR_LOOSE_QUESTION_PATTERNS
    )
    ids = [p["question_id"] for p in loose_patterns]
    assert ids == [1, 3, 4, 9], ids
    print(f"  PASS: extra_patterns 지정 시 OCR 잡음 섞인 형식도 감지됨: {ids}")


def test_real_sample_pdf_end_to_end():
    """실제 sample(65-67).pdf에서 문65~68이 모두 감지되는지 end-to-end 확인."""
    if not SAMPLE_PDF.exists():
        print(f"  SKIP: 샘플 PDF 없음 ({SAMPLE_PDF})")
        return
    with PDFTextExtractor(str(SAMPLE_PDF)) as extractor:
        blocks = extractor.extract_text_with_positions()
        patterns = extractor.detect_question_patterns(blocks)
    ids = [p["question_id"] for p in patterns]
    assert ids == [65, 66, 67, 68], ids
    print(f"  PASS: 실제 sample(65-67).pdf에서 문제 4개 감지 확인: {ids}")


def main():
    tests = [
        ("구분자 없는 '문N' + 아티팩트 접두", test_bare_question_number_with_artifact_prefix),
        ("구분자 없는 '문N' (접두 없음)", test_bare_question_number_without_prefix),
        ("기존 '문N.'/'문N)' 회귀 확인", test_existing_dot_format_still_works),
        ("기존 '(N)'/'N.' 회귀 확인", test_existing_paren_and_bare_dot_still_work),
        ("본문 오탐 방지 확인", test_no_false_positive_on_prose_mentions),
        ("OCR 전용 관대한 패턴은 명시적 opt-in일 때만 적용", test_ocr_loose_pattern_requires_explicit_opt_in),
        ("수열 완화 - 발췌본 시작번호", test_monotonic_sequence_tolerates_excerpt_start),
        ("수열 완화 - OCR 오인식 1건 허용", test_monotonic_sequence_tolerates_single_ocr_glitch),
        ("수열 완화 - 무작위 숫자열 여전히 거부", test_monotonic_sequence_still_rejects_random_numbers),
        ("실제 sample(65-67).pdf end-to-end", test_real_sample_pdf_end_to_end),
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
