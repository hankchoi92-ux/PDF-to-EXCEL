"""
신뢰도 점수 계산 (Phase 3)

검증 결과 기반 종합 신뢰도 점수 부여.
AUTO / HUMAN_REVIEW 분류.
"""

from typing import Dict, List, Any
from dataclasses import dataclass


@dataclass
class ConfidenceScore:
    """신뢰도 점수 결과."""
    overall_score: float  # 0.0~1.0
    classification: str   # "AUTO" (≥0.95) | "HUMAN_REVIEW" (<0.95)
    deductions: List[Dict[str, Any]]  # 감점 항목 목록
    auto_fixable_count: int           # 자동 수정 가능 건수
    manual_review_count: int          # 수동 검토 필요 건수
    confidence_details: Dict[str, Any]  # 항목별 상세


class ConfidenceScorer:
    """
    종합 신뢰도 점수 계산.
    """

    # 가중치 설정
    WEIGHTS = {
        'structure_error': -0.3,   # 심각
        'diff_missing': -0.4,      # 매우 심각
        'term_mismatch': -0.1,     # 경미
        'empty_field': -0.2,       # 중간
    }

    CLASSIFICATION_THRESHOLD = 0.95  # AUTO 기준값

    def __init__(self, logger=None):
        """
        초기화.

        Args:
            logger: 로거 인스턴스 (선택적)
        """
        pass

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

        Output:
        {
            'overall_score': 0.92,
            'classification': 'HUMAN_REVIEW',
            'deductions': [
                {'reason': '용어 불일치', 'amount': -0.1, 'detail': '3번 문제'},
            ],
            'auto_fixable': 2,
            'manual_review': 1,
            'breakdown': {
                'structure': {'count': 0, 'weight': -0.3, 'total_deduction': 0.0},
                'diff': {'count': 1, 'weight': -0.4, 'total_deduction': -0.4},
                'term': {'count': 1, 'weight': -0.1, 'total_deduction': -0.1},
            }
        }

        Args:
            validation_results: 검증 결과 모음

        Returns:
            Dict: 신뢰도 점수 결과
        """
        pass

    def _calculate_base_score(self) -> float:
        """
        기본 점수 (1.0).

        Returns:
            float: 1.0
        """
        pass

    def _apply_deductions(
        self,
        base_score: float,
        issues: Dict[str, List[Any]]
    ) -> tuple:
        """
        이슈별 감점 계산.

        Args:
            base_score: 기본 점수
            issues: 이슈 모음

        Returns:
            Tuple[float, List]: (최종 점수, 감점 항목 목록)
        """
        pass

    def _classify(self, score: float) -> str:
        """
        신뢰도 점수 기반 분류.

        Args:
            score: 점수

        Returns:
            str: "AUTO" | "HUMAN_REVIEW"
        """
        pass

    def _count_fixable_issues(self, issues: Dict[str, List[Any]]) -> tuple:
        """
        자동 수정 가능 vs 수동 검토 필요 이슈 분류.

        Args:
            issues: 이슈 모음

        Returns:
            Tuple[int, int]: (자동 수정 가능, 수동 검토 필요)
        """
        pass
