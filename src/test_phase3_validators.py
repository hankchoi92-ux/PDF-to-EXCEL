"""
Phase 3 검증 모듈군 Dry-run 테스트.

structure_validator / diff_validator / term_validator / confidence_scorer를
더미 데이터로 단독 실행하여 정상 동작을 확인한다. pytest 없이도
`python src/test_phase3_validators.py`로 바로 실행 가능하다.
"""

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from structure_validator import StructureValidator
from diff_validator import DiffValidator
from term_validator import TermValidator
from confidence_scorer import ConfidenceScorer

DICTIONARY_PATH = str(PROJECT_ROOT / "dictionaries" / "legal_terms.json")


def _logger() -> logging.Logger:
    logger = logging.getLogger("phase3_dryrun")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


def test_structure_validator_clean():
    """정상 데이터: 이슈 0건이어야 함."""
    validator = StructureValidator(logger=_logger())
    chunk_data = {
        "questions": [
            {
                "id": 1,
                "text": "다음 중 계약의 성립 요건이 아닌 것은?",
                "options": [
                    {"num": "①", "text": "청약", "correct": False, "explanation": ""},
                    {"num": "②", "text": "승낙", "correct": False, "explanation": ""},
                    {"num": "③", "text": "물권 설정", "correct": True, "explanation": "정답 해설"},
                    {"num": "④", "text": "합의", "correct": False, "explanation": ""},
                    {"num": "⑤", "text": "당사자 확정", "correct": False, "explanation": ""},
                ],
            },
            {
                "id": 2,
                "text": "다음 중 물권이 아닌 것은?",
                "options": [
                    {"num": "①", "text": "소유권", "correct": False, "explanation": ""},
                    {"num": "②", "text": "저당권", "correct": False, "explanation": ""},
                    {"num": "③", "text": "질권", "correct": False, "explanation": ""},
                    {"num": "④", "text": "채권", "correct": True, "explanation": "정답 해설"},
                    {"num": "⑤", "text": "담보권", "correct": False, "explanation": ""},
                ],
            },
        ]
    }
    hint = {"options_per_question": 5}

    issues = validator.validate(chunk_data, hint)
    assert issues == [], f"정상 데이터에서 이슈 발생: {issues}"
    print("  PASS: 정상 데이터 -> 이슈 0건")


def test_structure_validator_broken():
    """비정상 데이터: 번호 누락, 정답 0/2개, 빈 필드, 선지 개수 불일치 감지."""
    validator = StructureValidator(logger=_logger())
    chunk_data = {
        "questions": [
            {
                "id": 1,
                "text": "",  # 빈 문제 본문
                "options": [
                    {"num": "①", "text": "청약", "correct": False, "explanation": ""},
                    {"num": "②", "text": "청약", "correct": False, "explanation": ""},  # 중복 텍스트
                    {"num": "③", "text": "물권", "correct": "O", "explanation": ""},  # 잘못된 correct 값
                ],
            },
            # 문제 2 누락 (다음이 3)
            {
                "id": 3,
                "text": "다음 중 옳은 것은?",
                "options": [
                    {"num": "①", "text": "가", "correct": True, "explanation": ""},
                    {"num": "②", "text": "나", "correct": True, "explanation": ""},  # 정답 2개
                ],
            },
        ]
    }
    hint = {"options_per_question": 5}

    issues = validator.validate(chunk_data, hint)
    issue_types = {i.issue_type for i in issues}
    expected = {
        "EMPTY_QUESTION_TEXT", "TEXT_DUPLICATED", "INVALID_CORRECT_VALUE",
        "MISSING_QUESTION", "MULTIPLE_CORRECT_ANSWERS", "OPTION_COUNT_INCONSISTENT",
    }
    missing = expected - issue_types
    assert not missing, f"예상 이슈 유형 누락: {missing} (실제: {issue_types})"
    print(f"  PASS: 비정상 데이터 -> {len(issues)}건 이슈 감지 ({sorted(issue_types)})")
    return issues


def test_diff_validator_clean():
    """원본과 결과가 거의 동일한 경우 이슈가 없어야 함."""
    validator = DiffValidator(logger=_logger())
    original = (
        "1. 다음 중 계약의 성립 요건이 아닌 것은?\n"
        "① 청약 ② 승낙 ③ 물권 설정 ④ 합의 ⑤ 당사자 확정"
    )
    claude_output = {
        "questions": [
            {
                "id": 1,
                "text": "다음 중 계약의 성립 요건이 아닌 것은?",
                "options": [
                    {"num": "①", "text": "청약", "correct": False, "explanation": ""},
                    {"num": "②", "text": "승낙", "correct": False, "explanation": ""},
                    {"num": "③", "text": "물권 설정", "correct": True, "explanation": "해설"},
                    {"num": "④", "text": "합의", "correct": False, "explanation": ""},
                    {"num": "⑤", "text": "당사자 확정", "correct": False, "explanation": ""},
                ],
            }
        ]
    }
    issues = validator.validate(original, claude_output)
    blocking = [i for i in issues if i.issue_type in ("TRUNCATION", "HALLUCINATION", "OPTION_MISSING")]
    assert not blocking, f"정상 데이터에서 심각 이슈 발생: {blocking}"
    print(f"  PASS: 정상 데이터 -> 심각 이슈 없음 (전체 {len(issues)}건, 경미 이슈만 허용)")


def test_diff_validator_truncated():
    """원본 대비 결과가 크게 축소된 경우 TRUNCATION/HALLUCINATION 감지."""
    validator = DiffValidator(logger=_logger())
    original = (
        "1. 다음 중 계약의 성립 요건이 아닌 것은? 매우 긴 문제 설명이 이어지고 "
        "① 청약 ② 승낙 ③ 물권 설정 ④ 합의 ⑤ 당사자 확정 해설: 청약과 승낙의 "
        "합치로 계약이 성립하며 물권 설정은 계약 성립 요건이 아니다."
    )
    claude_output = {
        "questions": [
            {
                "id": 1,
                "text": "문제",
                "options": [
                    {"num": "①", "text": "청약", "correct": True, "explanation": ""},
                ],
            }
        ]
    }
    issues = validator.validate(original, claude_output)
    issue_types = {i.issue_type for i in issues}
    assert "TRUNCATION" in issue_types, f"삭제 의심 미감지: {issue_types}"
    assert "OPTION_MISSING" in issue_types, f"선지 누락 미감지: {issue_types}"
    print(f"  PASS: 축소된 데이터 -> {sorted(issue_types)} 감지")
    return issues


def test_term_validator_regression():
    """local_corrector가 교정했어야 할 오타 패턴이 남아있으면 감지."""
    validator = TermValidator(DICTIONARY_PATH, logger=_logger())
    parsed_data = {
        "questions": [
            {
                "id": 1,
                "text": "다음 중 게약의 성립 요건이 아닌 것은?",  # "게약" 오타 회귀
                "options": [
                    {"num": "①", "text": "청악", "correct": False, "explanation": ""},  # "청악" 오타
                    {"num": "②", "text": "승낙", "correct": True, "explanation": "정상 용어"},
                ],
            }
        ]
    }
    issues = validator.verify(parsed_data)
    terms_found = {i.term for i in issues}
    assert "게약" in terms_found, f"'게약' 오타 회귀 미감지: {terms_found}"
    assert "청악" in terms_found, f"'청악' 오타 회귀 미감지: {terms_found}"
    print(f"  PASS: 오타 회귀 {len(issues)}건 감지 ({sorted(terms_found)})")
    return issues


def test_term_validator_clean():
    """정상 교정된 용어만 있으면 이슈가 없어야 함."""
    validator = TermValidator(DICTIONARY_PATH, logger=_logger())
    parsed_data = {
        "questions": [
            {
                "id": 1,
                "text": "다음 중 계약의 성립 요건이 아닌 것은?",
                "options": [
                    {"num": "①", "text": "청약", "correct": False, "explanation": ""},
                    {"num": "②", "text": "승낙", "correct": True, "explanation": ""},
                ],
            }
        ]
    }
    issues = validator.verify(parsed_data)
    assert issues == [], f"정상 데이터에서 이슈 발생: {issues}"
    print("  PASS: 정상 교정 데이터 -> 이슈 0건")


def test_confidence_scorer():
    """3개 validator 결과를 종합해 점수/분류가 기대대로 산출되는지 확인."""
    scorer = ConfidenceScorer(logger=_logger())

    # 케이스 1: 이슈 없음 -> AUTO, 1.0
    result_clean = scorer.calculate({
        "structure_issues": [], "diff_issues": [], "term_issues": [],
    })
    assert result_clean["overall_score"] == 1.0
    assert result_clean["classification"] == "AUTO"
    print(f"  PASS: 이슈 없음 -> {result_clean['overall_score']} / {result_clean['classification']}")

    # 케이스 2: structure ERROR 1건 -> 1.0 - 0.4 = 0.6 -> HUMAN_REVIEW
    structure_issues = test_structure_validator_broken()
    diff_issues = test_diff_validator_truncated()
    term_issues = test_term_validator_regression()

    result_broken = scorer.calculate({
        "structure_issues": structure_issues,
        "diff_issues": diff_issues,
        "term_issues": term_issues,
    })
    assert 0.0 <= result_broken["overall_score"] < 1.0
    assert result_broken["classification"] == "HUMAN_REVIEW"
    assert result_broken["manual_review"] > 0
    print(
        f"  PASS: 복합 이슈 -> {result_broken['overall_score']} / "
        f"{result_broken['classification']} "
        f"(auto_fixable={result_broken['auto_fixable']}, manual_review={result_broken['manual_review']})"
    )
    print(f"        breakdown={result_broken['breakdown']}")

    # 케이스 3: 점수는 절대 0 미만으로 내려가지 않음
    many_errors = structure_issues * 10
    result_floor = scorer.calculate({
        "structure_issues": many_errors, "diff_issues": [], "term_issues": [],
    })
    assert result_floor["overall_score"] == 0.0
    print(f"  PASS: 대량 이슈 -> 점수 하한 고정 확인 ({result_floor['overall_score']})")


def main():
    tests = [
        ("StructureValidator (정상)", test_structure_validator_clean),
        ("StructureValidator (비정상)", test_structure_validator_broken),
        ("DiffValidator (정상)", test_diff_validator_clean),
        ("DiffValidator (축소/변형)", test_diff_validator_truncated),
        ("TermValidator (오타 회귀)", test_term_validator_regression),
        ("TermValidator (정상)", test_term_validator_clean),
        ("ConfidenceScorer (종합)", test_confidence_scorer),
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
    else:
        print(f"전체 통과: {len(tests)}/{len(tests)}")


if __name__ == "__main__":
    main()
