"""
구조 검증 (Phase 3)

Claude 변환 결과의 구조적 무결성 검증.
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class ValidationIssue:
    """검증 이슈."""
    issue_type: str  # MISSING_QUESTION | OPTION_COUNT_INCONSISTENT | ...
    severity: str    # ERROR | WARNING
    detail: str      # 상세 설명
    question_id: int = 0  # 해당 문제 번호 (청크 전체에 대한 이슈면 0)
    location: str = ""    # 경로 (예: "questions[4]")


class StructureValidator:
    """
    변환 결과의 구조적 무결성 검증.
    """

    # "정오" 필드(correct)에 허용되는 값. 프로젝트 JSON 스키마는 boolean만 허용한다
    # (CLAUDE.md 고정 형식 참조). 문자열 "O"/"X" 등이 섞여 들어오면 무효로 처리한다.
    VALID_CORRECT_VALUES = (True, False)

    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        초기화.

        Args:
            logger: 로거 인스턴스 (선택적)
        """
        self.logger = logger or logging.getLogger(__name__)

    def validate(
        self,
        chunk_data: Dict[str, Any],
        hint: Dict[str, Any]
    ) -> List[ValidationIssue]:
        """
        구조 검증 수행.

        검증 항목:
        1. 문제번호 연속성 (1,2,3... 빠짐 없이)
        2. 선지 개수 일관성 (모든 문제가 동일한 개수)
        3. "동일" 처리 누락 (선지 텍스트 중복)
        4. 정오표 유효성 (true/false만, 다른 값 없음)
        5. 빈 필드 검출 (text/num 필수)

        Args:
            chunk_data: Claude 파싱 결과 (questions 리스트 포함)
            hint: LocalHintGenerator 결과 (options_per_question 등)

        Returns:
            List[ValidationIssue]: 발견된 이슈 목록 (빈 리스트 = 통과)
        """
        questions = chunk_data.get("questions", []) if chunk_data else []
        hint = hint or {}
        expected_count = int(hint.get("options_per_question") or 0)

        issues: List[ValidationIssue] = []
        issues.extend(self._check_question_continuity(questions))
        issues.extend(self._check_option_count_consistency(questions, expected_count))
        issues.extend(self._check_text_duplication(questions))
        issues.extend(self._check_correct_field(questions))
        issues.extend(self._check_empty_fields(questions))

        if issues:
            self.logger.info(
                "구조 검증 완료: 문제 %d개 중 이슈 %d건 (ERROR %d / WARNING %d)",
                len(questions), len(issues),
                sum(1 for i in issues if i.severity == "ERROR"),
                sum(1 for i in issues if i.severity == "WARNING"),
            )
        else:
            self.logger.info("구조 검증 완료: 문제 %d개, 이슈 없음", len(questions))
        return issues

    def _check_question_continuity(
        self,
        questions: List[Dict[str, Any]]
    ) -> List[ValidationIssue]:
        """
        문제 번호 연속성 검사.

        Args:
            questions: 문제 리스트

        Returns:
            List[ValidationIssue]: 이슈 목록
        """
        issues: List[ValidationIssue] = []
        ids = [q.get("id") for q in questions if isinstance(q.get("id"), int)]
        if not ids:
            return issues

        seen: Dict[int, int] = {}
        for qid in ids:
            seen[qid] = seen.get(qid, 0) + 1
        for qid, count in seen.items():
            if count > 1:
                issues.append(ValidationIssue(
                    issue_type="DUPLICATE_QUESTION",
                    severity="ERROR",
                    detail=f"문제 번호 {qid}가 {count}회 중복 출현",
                    question_id=qid,
                    location=f"questions[id={qid}]",
                ))

        sorted_ids = sorted(seen.keys())
        for prev, curr in zip(sorted_ids, sorted_ids[1:]):
            if curr - prev > 1:
                for missing in range(prev + 1, curr):
                    issues.append(ValidationIssue(
                        issue_type="MISSING_QUESTION",
                        severity="ERROR",
                        detail=f"문제 번호 {missing}이(가) 누락됨 ({prev} 다음 {curr})",
                        question_id=missing,
                        location=f"questions[between {prev},{curr}]",
                    ))
        return issues

    def _check_option_count_consistency(
        self,
        questions: List[Dict[str, Any]],
        expected_count: int
    ) -> List[ValidationIssue]:
        """
        선지 개수 일관성 검사.

        Args:
            questions: 문제 리스트
            expected_count: 예상 선지 개수

        Returns:
            List[ValidationIssue]: 이슈 목록
        """
        issues: List[ValidationIssue] = []
        for q in questions:
            qid = q.get("id", 0)
            options = q.get("options", []) or []
            actual_count = len(options)
            if expected_count > 0 and actual_count != expected_count:
                issues.append(ValidationIssue(
                    issue_type="OPTION_COUNT_INCONSISTENT",
                    severity="WARNING",
                    detail=(
                        f"선지 개수 불일치: 예상 {expected_count}개, "
                        f"실제 {actual_count}개"
                    ),
                    question_id=qid,
                    location=f"questions[id={qid}].options",
                ))
        return issues

    def _check_text_duplication(
        self,
        questions: List[Dict[str, Any]]
    ) -> List[ValidationIssue]:
        """
        "동일" 처리 누락 검사.

        같은 문제 내에서 서로 다른 선지의 본문(text)이 완전히 동일하면
        추출 오류(복붙 실수) 가능성이 높으므로 플래깅한다.

        Args:
            questions: 문제 리스트

        Returns:
            List[ValidationIssue]: 이슈 목록
        """
        issues: List[ValidationIssue] = []
        for q in questions:
            qid = q.get("id", 0)
            options = q.get("options", []) or []
            text_to_nums: Dict[str, List[str]] = {}
            for opt in options:
                text = (opt.get("text") or "").strip()
                if not text or text == "동일":
                    continue
                text_to_nums.setdefault(text, []).append(opt.get("num", "?"))

            for text, nums in text_to_nums.items():
                if len(nums) > 1:
                    issues.append(ValidationIssue(
                        issue_type="TEXT_DUPLICATED",
                        severity="WARNING",
                        detail=(
                            f"선지 {', '.join(nums)}의 본문이 완전히 동일함 "
                            f"(추출 오류 의심): '{text[:30]}...'"
                            if len(text) > 30 else
                            f"선지 {', '.join(nums)}의 본문이 완전히 동일함 "
                            f"(추출 오류 의심): '{text}'"
                        ),
                        question_id=qid,
                        location=f"questions[id={qid}].options",
                    ))
        return issues

    def _check_correct_field(
        self,
        questions: List[Dict[str, Any]]
    ) -> List[ValidationIssue]:
        """
        correct 필드(정오표) 유효성 검사.

        - correct 값은 반드시 boolean(true/false)이어야 함.
        - 문제당 정답(true)은 정확히 1개여야 함(0개/2개 이상은 이상 신호).

        Args:
            questions: 문제 리스트

        Returns:
            List[ValidationIssue]: 이슈 목록
        """
        issues: List[ValidationIssue] = []
        for q in questions:
            qid = q.get("id", 0)
            options = q.get("options", []) or []
            correct_count = 0
            for opt in options:
                num = opt.get("num", "?")
                correct = opt.get("correct")
                if not isinstance(correct, bool):
                    issues.append(ValidationIssue(
                        issue_type="INVALID_CORRECT_VALUE",
                        severity="ERROR",
                        detail=(
                            f"선지 {num}의 correct 값이 유효하지 않음 "
                            f"(true/false만 허용): {correct!r}"
                        ),
                        question_id=qid,
                        location=f"questions[id={qid}].options[{num}].correct",
                    ))
                    continue
                if correct:
                    correct_count += 1

            if correct_count == 0:
                issues.append(ValidationIssue(
                    issue_type="NO_CORRECT_ANSWER",
                    severity="ERROR",
                    detail="정답(correct=true)으로 표시된 선지가 없음",
                    question_id=qid,
                    location=f"questions[id={qid}].options",
                ))
            elif correct_count > 1:
                issues.append(ValidationIssue(
                    issue_type="MULTIPLE_CORRECT_ANSWERS",
                    severity="WARNING",
                    detail=f"정답으로 표시된 선지가 {correct_count}개 (통상 1개)",
                    question_id=qid,
                    location=f"questions[id={qid}].options",
                ))
        return issues

    def _check_empty_fields(
        self,
        questions: List[Dict[str, Any]]
    ) -> List[ValidationIssue]:
        """
        빈 필드 검출.

        Args:
            questions: 문제 리스트

        Returns:
            List[ValidationIssue]: 이슈 목록
        """
        issues: List[ValidationIssue] = []
        for q in questions:
            qid = q.get("id", 0)
            if not (q.get("text") or "").strip():
                issues.append(ValidationIssue(
                    issue_type="EMPTY_QUESTION_TEXT",
                    severity="ERROR",
                    detail="문제 본문(text)이 비어 있음",
                    question_id=qid,
                    location=f"questions[id={qid}].text",
                ))

            options = q.get("options", []) or []
            if not options:
                issues.append(ValidationIssue(
                    issue_type="EMPTY_OPTIONS",
                    severity="ERROR",
                    detail="선지(options) 목록이 비어 있음",
                    question_id=qid,
                    location=f"questions[id={qid}].options",
                ))
                continue

            for opt in options:
                num = opt.get("num", "")
                if not str(num).strip():
                    issues.append(ValidationIssue(
                        issue_type="EMPTY_OPTION_NUM",
                        severity="ERROR",
                        detail="선지 번호(num)가 비어 있음",
                        question_id=qid,
                        location=f"questions[id={qid}].options",
                    ))
                if not (opt.get("text") or "").strip():
                    issues.append(ValidationIssue(
                        issue_type="EMPTY_OPTION_TEXT",
                        severity="ERROR",
                        detail=f"선지 {num or '?'}의 본문(text)이 비어 있음",
                        question_id=qid,
                        location=f"questions[id={qid}].options[{num}]",
                    ))
        return issues
