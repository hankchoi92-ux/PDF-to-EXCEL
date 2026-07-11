"""
신뢰도 점수 계산 (Phase 3)

검증 결과 기반 종합 신뢰도 점수 부여.
AUTO / HUMAN_REVIEW 분류.
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict


@dataclass
class ConfidenceScore:
    """신뢰도 점수 결과."""
    overall_score: float               # 0.0~1.0
    classification: str                # "AUTO" (≥0.95) | "HUMAN_REVIEW" (<0.95)
    deductions: List[Dict[str, Any]] = field(default_factory=list)  # 감점 항목 목록
    auto_fixable: int = 0              # 자동 수정 가능(경미) 이슈 건수
    manual_review: int = 0             # 수동 검토 필요(심각) 이슈 건수
    breakdown: Dict[str, Any] = field(default_factory=dict)         # 항목별 상세

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ConfidenceScorer:
    """
    종합 신뢰도 점수 계산.

    구조/Diff/용어 검증 결과를 입력받아 0.0~1.0 사이의 단일 점수로
    종합하고, 임계값 기준으로 AUTO/HUMAN_REVIEW를 분류한다.
    """

    # 감점 가중치 (요구사항 고정값)
    WEIGHTS = {
        'structure_error': -0.4,    # 누락/구조적 ERROR
        'diff_anomaly': -0.3,       # 길이 축소/변형 의심 (diff_validator 이슈 전체)
        'empty_field': -0.2,        # 빈 필드 등 WARNING급 구조 이슈
        'term_typo': -0.1,          # 용어 오타 패턴 발견
    }

    CLASSIFICATION_THRESHOLD = 0.95  # AUTO 기준값

    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        초기화.

        Args:
            logger: 로거 인스턴스 (선택적)
        """
        self.logger = logger or logging.getLogger(__name__)

    def calculate(
        self,
        validation_results: Dict[str, List[Any]]
    ) -> Dict[str, Any]:
        """
        종합 신뢰도 점수 계산.

        Input:
        {
            'structure_issues': [ValidationIssue, ...],
            'diff_issues': [DiffIssue, ...],
            'term_issues': [TermIssue, ...],
        }

        Output (ConfidenceScore.to_dict()):
        {
            'overall_score': 0.92,
            'classification': 'HUMAN_REVIEW',
            'deductions': [
                {'reason': '용어 오타 패턴 발견', 'amount': -0.1, 'detail': '...'},
            ],
            'auto_fixable': 2,
            'manual_review': 1,
            'breakdown': {
                'structure_error': {'count': 0, 'weight': -0.4, 'total_deduction': 0.0},
                'diff_anomaly':   {'count': 1, 'weight': -0.3, 'total_deduction': -0.3},
                'empty_field':    {'count': 0, 'weight': -0.2, 'total_deduction': 0.0},
                'term_typo':      {'count': 1, 'weight': -0.1, 'total_deduction': -0.1},
            }
        }

        Args:
            validation_results: 검증 결과 모음

        Returns:
            Dict: 신뢰도 점수 결과
        """
        validation_results = validation_results or {}
        issues = {
            "structure_issues": validation_results.get("structure_issues", []) or [],
            "diff_issues": validation_results.get("diff_issues", []) or [],
            "term_issues": validation_results.get("term_issues", []) or [],
        }

        base_score = self._calculate_base_score()
        final_score, deductions, breakdown = self._apply_deductions(base_score, issues)
        classification = self._classify(final_score)
        auto_fixable, manual_review = self._count_fixable_issues(issues)

        result = ConfidenceScore(
            overall_score=final_score,
            classification=classification,
            deductions=deductions,
            auto_fixable=auto_fixable,
            manual_review=manual_review,
            breakdown=breakdown,
        )

        self.logger.info(
            "신뢰도 점수 계산 완료: %.3f (%s), 감점 %d건",
            final_score, classification, len(deductions),
        )
        return result.to_dict()

    def _calculate_base_score(self) -> float:
        """
        기본 점수 (1.0).

        Returns:
            float: 1.0
        """
        return 1.0

    def _apply_deductions(
        self,
        base_score: float,
        issues: Dict[str, List[Any]]
    ) -> Tuple[float, List[Dict[str, Any]], Dict[str, Any]]:
        """
        이슈별 감점 계산.

        분류 기준:
        - structure_issues 중 severity == ERROR   -> 'structure_error' (-0.4)
        - structure_issues 중 severity == WARNING -> 'empty_field' (-0.2)
        - diff_issues 전체                         -> 'diff_anomaly' (-0.3)
        - term_issues 전체                         -> 'term_typo' (-0.1)

        Args:
            base_score: 기본 점수
            issues: 이슈 모음 ('structure_issues'/'diff_issues'/'term_issues')

        Returns:
            Tuple[float, List, Dict]: (최종 점수, 감점 항목 목록, 항목별 breakdown)
        """
        structure_issues = issues.get("structure_issues", [])
        diff_issues = issues.get("diff_issues", [])
        term_issues = issues.get("term_issues", [])

        structure_errors = [i for i in structure_issues if getattr(i, "severity", None) == "ERROR"]
        structure_warnings = [i for i in structure_issues if getattr(i, "severity", None) != "ERROR"]

        buckets = {
            "structure_error": structure_errors,
            "diff_anomaly": diff_issues,
            "empty_field": structure_warnings,
            "term_typo": term_issues,
        }

        deductions: List[Dict[str, Any]] = []
        breakdown: Dict[str, Any] = {}
        score = base_score

        for key, bucket_issues in buckets.items():
            weight = self.WEIGHTS[key]
            count = len(bucket_issues)
            total_deduction = round(weight * count, 4)
            breakdown[key] = {
                "count": count,
                "weight": weight,
                "total_deduction": total_deduction,
            }
            for issue in bucket_issues:
                detail = getattr(issue, "detail", None) or getattr(issue, "term", "")
                deductions.append({
                    "reason": key,
                    "amount": weight,
                    "detail": detail,
                })
            score += total_deduction

        final_score = max(0.0, round(score, 4))
        return final_score, deductions, breakdown

    def _classify(self, score: float) -> str:
        """
        신뢰도 점수 기반 분류.

        Args:
            score: 점수

        Returns:
            str: "AUTO" | "HUMAN_REVIEW"
        """
        return "AUTO" if score >= self.CLASSIFICATION_THRESHOLD else "HUMAN_REVIEW"

    def _count_fixable_issues(self, issues: Dict[str, List[Any]]) -> Tuple[int, int]:
        """
        자동 수정 가능 vs 수동 검토 필요 이슈 분류.

        - 자동 수정 가능: term_issues(교정 후보가 있는 사전 기반 오타),
          structure_issues 중 WARNING(빈 필드류가 아닌 경미한 구조 경고).
        - 수동 검토 필요: structure_issues 중 ERROR, diff_issues 전체
          (삭제/변형 의심은 사람이 원본과 대조해야 함).

        Args:
            issues: 이슈 모음

        Returns:
            Tuple[int, int]: (자동 수정 가능, 수동 검토 필요)
        """
        structure_issues = issues.get("structure_issues", [])
        diff_issues = issues.get("diff_issues", [])
        term_issues = issues.get("term_issues", [])

        structure_errors = sum(1 for i in structure_issues if getattr(i, "severity", None) == "ERROR")
        structure_warnings = sum(1 for i in structure_issues if getattr(i, "severity", None) != "ERROR")

        auto_fixable = structure_warnings + len(term_issues)
        manual_review = structure_errors + len(diff_issues)
        return auto_fixable, manual_review
