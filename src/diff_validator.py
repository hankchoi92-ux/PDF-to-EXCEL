"""
Diff 검증 (Phase 3)

원본 텍스트 vs Claude 변환 결과 비교.
선지 누락, 텍스트 변형 감지.
"""

import logging
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from difflib import SequenceMatcher

# 원본 대비 결과 텍스트 길이가 이 비율 미만이면 "삭제 의심"으로 플래깅한다.
_LENGTH_TRUNCATION_THRESHOLD = 0.5

# 전체 유사도가 이 값 미만이면 "변형 의심"으로 플래깅한다.
_SIMILARITY_THRESHOLD = 0.5

# 원본 대비 결과에서 사라진 키워드 비율이 이 값을 넘으면 플래깅한다.
_KEYWORD_LOSS_RATIO_THRESHOLD = 0.3

# 선지 개수(원본 추정치 대비 결과)가 이 비율 미만이면 누락으로 플래깅한다.
_OPTION_COUNT_RATIO_THRESHOLD = 0.8

# 선지 텍스트 길이가 같은 문제 내 평균의 이 비율 미만이면 이상으로 플래깅한다
# (평균이 최소 길이 기준을 넘는 문제에 한해 적용 - 원래 짧은 선지 오탐 방지).
_OPTION_LENGTH_ANOMALY_RATIO = 0.3
_OPTION_LENGTH_MIN_AVG = 10

# 원본 선지 기호 패턴 (기호 유형 무관하게 모두 카운트하여 최댓값을 사용).
_OPTION_SYMBOL_PATTERNS = {
    "circled": re.compile(r"[①②③④⑤⑥⑦⑧⑨⑩]"),
    "korean": re.compile(r"(?<![가-힣])[ㄱㄴㄷㄹㅁ](?![가-힣])"),
    "numeric": re.compile(r"(?:^|\s)(\d{1,2})[.)]\s"),
}

# 키워드(주요 단어) 추출용: 한글/영문/숫자 3자 이상 토큰.
_KEYWORD_PATTERN = re.compile(r"[가-힣A-Za-z0-9]{3,}")


@dataclass
class DiffIssue:
    """Diff 검증 이슈."""
    issue_type: str  # OPTION_MISSING | TEXT_SIMILARITY_LOW | ...
    question_id: int
    severity: str    # ERROR | WARNING
    detail: str
    option_num: str = ""    # 해당 선지 번호 (선택적)
    similarity: float = 0.0  # 유사도 점수


class DiffValidator:
    """
    원본-결과 Diff 분석.
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        초기화.

        Args:
            logger: 로거 인스턴스 (선택적)
        """
        self.logger = logger or logging.getLogger(__name__)

    def validate(
        self,
        original_text: str,
        claude_output: Dict[str, Any]
    ) -> List[DiffIssue]:
        """
        원본-결과 Diff 분석.

        검증 항목:
        1. 원본 선지 개수 vs 결과 선지 개수
        2. 선지 텍스트 길이 급격한 변화 (삭제 의심)
        3. 원본에 있는데 결과에 없는 주요 키워드
        4. 유사도 임계값 이하 (변형 의심)

        알고리즘:
        - SequenceMatcher 기반 유사도

        Args:
            original_text: 원본 청크 텍스트
            claude_output: Claude JSON 파싱 결과

        Returns:
            List[DiffIssue]: 발견된 이슈 목록
        """
        original_text = original_text or ""
        claude_output = claude_output or {}
        questions = claude_output.get("questions", []) or []

        issues: List[DiffIssue] = []

        result_text = self._reconstruct_result_text(questions)
        similarity = self.calculate_similarity(original_text, result_text)

        if original_text:
            length_ratio = len(result_text) / len(original_text) if len(original_text) else 1.0
            if length_ratio < _LENGTH_TRUNCATION_THRESHOLD:
                issues.append(DiffIssue(
                    issue_type="TRUNCATION",
                    question_id=0,
                    severity="ERROR",
                    detail=(
                        f"결과 텍스트 길이({len(result_text)}자)가 원본"
                        f"({len(original_text)}자) 대비 "
                        f"{length_ratio:.0%}로 급격히 감소 (삭제 의심)"
                    ),
                    similarity=similarity,
                ))

        if similarity < _SIMILARITY_THRESHOLD:
            issues.append(DiffIssue(
                issue_type="HALLUCINATION",
                question_id=0,
                severity="ERROR",
                detail=f"원본-결과 전체 유사도 {similarity:.2f} (임계값 {_SIMILARITY_THRESHOLD} 미만, 변형 의심)",
                similarity=similarity,
            ))

        issues.extend(self.detect_missing_options(original_text, claude_output))
        issues.extend(self.detect_keyword_loss(original_text, claude_output))
        issues.extend(self.detect_length_anomalies(claude_output))

        self.logger.info(
            "Diff 검증 완료: 유사도 %.2f, 이슈 %d건", similarity, len(issues)
        )
        return issues

    def calculate_similarity(self, text1: str, text2: str) -> float:
        """
        SequenceMatcher 기반 유사도 계산.

        Args:
            text1: 원본 텍스트
            text2: 비교 텍스트

        Returns:
            float: 유사도 (0.0~1.0)
        """
        if not text1 and not text2:
            return 1.0
        return SequenceMatcher(None, text1 or "", text2 or "").ratio()

    def detect_missing_options(
        self,
        original: str,
        result: Dict[str, Any]
    ) -> List[DiffIssue]:
        """
        원본 대비 누락된 선지 감지.

        원본 텍스트에서 선지 기호(원문자/ㄱㄴㄷ/번호) 출현 횟수를 추정하고,
        결과에 포함된 전체 선지 개수와 비교한다. 청크 단위 비교이므로
        question_id는 0(청크 전체)으로 기록한다.

        Args:
            original: 원본 텍스트
            result: Claude 결과 (questions 포함)

        Returns:
            List[DiffIssue]: 누락 의심 이슈 목록
        """
        if not original:
            return []

        questions = result.get("questions", []) or []
        actual_option_count = sum(len(q.get("options", []) or []) for q in questions)

        estimated_counts = []
        for pattern in _OPTION_SYMBOL_PATTERNS.values():
            estimated_counts.append(len(pattern.findall(original)))
        estimated_original_count = max(estimated_counts) if estimated_counts else 0

        if estimated_original_count == 0:
            return []

        ratio = actual_option_count / estimated_original_count
        if ratio < _OPTION_COUNT_RATIO_THRESHOLD:
            return [DiffIssue(
                issue_type="OPTION_MISSING",
                question_id=0,
                severity="ERROR",
                detail=(
                    f"원본에서 추정된 선지 개수 {estimated_original_count}개 대비 "
                    f"결과 선지 개수 {actual_option_count}개 "
                    f"({ratio:.0%}) - 선지 누락 의심"
                ),
            )]
        return []

    def detect_keyword_loss(
        self,
        original: str,
        result: Dict[str, Any]
    ) -> List[DiffIssue]:
        """
        주요 키워드 손실 감지.

        3자 이상의 단어가 원본에는 있는데 결과에 없는 경우.

        Args:
            original: 원본 텍스트
            result: Claude 결과

        Returns:
            List[DiffIssue]: 키워드 손실 이슈 목록
        """
        if not original:
            return []

        questions = result.get("questions", []) or []
        result_text = self._reconstruct_result_text(questions)

        original_keywords = set(_KEYWORD_PATTERN.findall(original))
        if not original_keywords:
            return []

        missing = sorted(kw for kw in original_keywords if kw not in result_text)
        loss_ratio = len(missing) / len(original_keywords)

        if loss_ratio > _KEYWORD_LOSS_RATIO_THRESHOLD:
            sample = ", ".join(missing[:10])
            return [DiffIssue(
                issue_type="KEYWORD_LOSS",
                question_id=0,
                severity="WARNING",
                detail=(
                    f"원본 주요 키워드 중 {len(missing)}/{len(original_keywords)}개"
                    f"({loss_ratio:.0%})가 결과에서 발견되지 않음 (예: {sample})"
                ),
            )]
        return []

    def detect_length_anomalies(
        self,
        result: Dict[str, Any]
    ) -> List[DiffIssue]:
        """
        선지 텍스트 길이의 급격한 변화 감지.

        같은 문제의 모든 선지는 비슷한 길이를 가져야 함.

        Args:
            result: Claude 결과

        Returns:
            List[DiffIssue]: 길이 이상 이슈 목록
        """
        issues: List[DiffIssue] = []
        questions = result.get("questions", []) or [] if result else []

        for q in questions:
            qid = q.get("id", 0)
            options = q.get("options", []) or []
            lengths = [len((opt.get("text") or "")) for opt in options]
            if len(lengths) < 2:
                continue

            avg_len = sum(lengths) / len(lengths)
            if avg_len < _OPTION_LENGTH_MIN_AVG:
                continue

            for opt, length in zip(options, lengths):
                if length < avg_len * _OPTION_LENGTH_ANOMALY_RATIO:
                    issues.append(DiffIssue(
                        issue_type="LENGTH_ANOMALY",
                        question_id=qid,
                        severity="WARNING",
                        detail=(
                            f"선지 {opt.get('num', '?')}의 길이({length}자)가 "
                            f"동일 문제 평균({avg_len:.1f}자) 대비 지나치게 짧음 "
                            f"(삭제 의심)"
                        ),
                        option_num=opt.get("num", "?"),
                    ))
        return issues

    def _reconstruct_result_text(self, questions: List[Dict[str, Any]]) -> str:
        """
        결과 questions 배열의 텍스트 필드를 모두 이어붙여 비교용 문자열 생성.

        Args:
            questions: Claude 결과의 questions 리스트

        Returns:
            str: 이어붙인 전체 텍스트
        """
        parts: List[str] = []
        for q in questions:
            parts.append(q.get("text") or "")
            for opt in q.get("options", []) or []:
                parts.append(opt.get("text") or "")
                parts.append(opt.get("explanation") or "")
        return " ".join(p for p in parts if p)
