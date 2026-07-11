"""
Excel 생성 (Phase 4)

최종 Excel 파일 생성 (3개 시트: 전체 문제 / 검토 필요 / 변환 통계).
스타일, 필터, 조건부 서식 적용.

입력 계약: all_questions는 auto_pipeline._phase_3_validate()가 만드는
"평탄화된" 문제 리스트로, 각 원소는 다음 키를 갖는다.
    {
        'id': int, 'text': str,
        'options': [{'num', 'text', 'correct'(bool), 'explanation'}, ...],
        'confidence': float (0.0~1.0),  # 해당 문제가 속한 청크의 종합 신뢰도
        'status': 'AUTO' | 'HUMAN_REVIEW',
        'chunk_id': str,
    }
선지 1개당 1행으로 출력하므로, 시트의 실제 행 수는 문제 수가 아니라
전체 선지 수와 같다.
"""

import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

import openpyxl
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

# "전체 문제" / "검토 필요" 공통 컬럼 정의
_COLUMNS = ["문제번호", "문제", "선지번호", "선지내용", "정오", "해설", "신뢰도", "상태"]
_REVIEW_EXTRA_COLUMN = "수동 확인"

_CONFIDENCE_COL = 7   # G: 신뢰도
_STATUS_COL = 8       # H: 상태
_QUESTION_TEXT_COL = 2  # B: 문제
_CORRECT_COL = 5      # E: 정오

_HUMAN_REVIEW_THRESHOLD = 0.95
_LOW_CONFIDENCE_THRESHOLD = 0.7

_MAX_COLUMN_WIDTH = 60
_MIN_COLUMN_WIDTH = 8


class ExcelBuilder:
    """
    최종 Excel 파일 생성.
    """

    def __init__(self, output_dir: str, logger: Optional[logging.Logger] = None):
        """
        초기화.

        Args:
            output_dir: 출력 디렉토리 (output/)
            logger: 로거 인스턴스 (선택적)
        """
        self.output_dir = Path(output_dir)
        self.logger = logger or logging.getLogger(__name__)
        self.styles = self._init_styles()

    def _init_styles(self) -> Dict[str, Dict[str, Any]]:
        """
        Excel 스타일 정의.

        Returns:
            Dict: 스타일 정의
                {
                    'header': {...},
                    'auto_confirmed': {...},
                    'human_review': {...},
                    ...
                }
        """
        return {
            "header": {
                "font": Font(bold=True, color="FFFFFF"),
                "fill": PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid"),
                "alignment": Alignment(horizontal="center", vertical="center", wrap_text=True),
            },
            "wrap": {
                "alignment": Alignment(vertical="top", wrap_text=True),
            },
            "low_confidence": {
                "fill": PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid"),  # 노란색
            },
            "very_low_confidence": {
                "fill": PatternFill(start_color="FFA500", end_color="FFA500", fill_type="solid"),  # 주황색
            },
            "correct_o": {
                "fill": PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid"),  # 연두
                "font": Font(color="006100"),
            },
            "correct_x": {
                "fill": PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid"),  # 연빨강
                "font": Font(color="9C0006"),
            },
            "duplicate_gray": {
                "fill": PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid"),
                "font": Font(color="808080", italic=True),
            },
            "border": Border(
                left=Side(style="thin", color="D9D9D9"), right=Side(style="thin", color="D9D9D9"),
                top=Side(style="thin", color="D9D9D9"), bottom=Side(style="thin", color="D9D9D9"),
            ),
        }

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def create_all_sheets(
        self,
        all_questions: List[Dict[str, Any]],
        validation_results: Dict[str, Any]
    ) -> Dict[str, Path]:
        """
        3개 시트 생성 및 Excel 파일 저장.

        시트:
        1. 전체 문제
        2. 검토 필요
        3. 변환 통계

        Args:
            all_questions: 모든 문제 리스트 (모듈 docstring의 입력 계약 참조)
            validation_results: 검증 결과
                {
                    'human_review': [...] (선택적, 없으면 all_questions에서 status로 필터링),
                    'statistics': {...},
                }

        Returns:
            Dict[str, Path]: 생성된 파일 경로 {'main': Path('output/최종_문제집.xlsx')}
        """
        validation_results = validation_results or {}
        wb = openpyxl.Workbook()

        ws_main = wb.active
        ws_main.title = "전체 문제"
        self.create_main_sheet(ws_main, all_questions)

        review_items = validation_results.get("human_review")
        if review_items is None:
            review_items = [q for q in all_questions if q.get("status") == "HUMAN_REVIEW"]
        ws_review = wb.create_sheet("검토 필요")
        self.create_review_sheet(ws_review, review_items)

        ws_stats = wb.create_sheet("변환 통계")
        statistics = validation_results.get("statistics") or self._derive_statistics(all_questions)
        self.create_statistics_sheet(ws_stats, statistics)

        output_path = self.output_dir / "최종_문제집.xlsx"
        saved = self.save_workbook(wb, str(output_path))
        self.logger.info(
            "Excel 생성 완료: %s (문제 %d개, 검토필요 %d건)",
            saved, len({q.get("id") for q in all_questions}), len(review_items),
        )
        return {"main": saved}

    def create_main_sheet(
        self,
        ws,
        all_questions: List[Dict[str, Any]]
    ) -> None:
        """
        "전체 문제" 시트 생성.

        컬럼: 문제번호 | 문제 | 선지번호 | 선지내용 | 정오 | 해설 | 신뢰도 | 상태

        기능:
        - 틀 고정 (1행)
        - 필터 적용
        - 조건부 서식 (신뢰도별 배경색, 정오 색상, "동일" 회색)
        - 열 너비 자동 조정

        Args:
            ws: openpyxl Worksheet
            all_questions: 문제 리스트
        """
        self._write_header(ws, _COLUMNS)
        row = 2
        for q in all_questions:
            row = self._write_question_rows(ws, row, q)

        last_row = max(row - 1, 1)
        self._apply_header_style(ws, 1)
        self._apply_conditional_formatting(ws, f"A1:H{last_row}")
        self._auto_adjust_column_width(ws)

        ws.freeze_panes = "A2"
        if last_row >= 1:
            ws.auto_filter.ref = f"A1:H{last_row}"

    def create_review_sheet(
        self,
        ws,
        review_items: List[Dict[str, Any]]
    ) -> None:
        """
        "검토 필요" 시트 생성.

        상태가 HUMAN_REVIEW인 문제(해당 문제의 전체 선지)만 표시.
        맨 끝에 수동 확인용 드롭다운 컬럼("수동 확인": 공란/O/X) 추가.

        Args:
            ws: openpyxl Worksheet
            review_items: 검토 필요 항목 리스트 (문제 단위)
        """
        columns = _COLUMNS + [_REVIEW_EXTRA_COLUMN]
        self._write_header(ws, columns)
        row = 2
        for q in review_items:
            row = self._write_question_rows(ws, row, q)

        last_row = max(row - 1, 1)
        self._apply_header_style(ws, 1)
        self._apply_conditional_formatting(ws, f"A1:H{last_row}")
        self._auto_adjust_column_width(ws)

        ws.freeze_panes = "A2"
        if last_row >= 1:
            ws.auto_filter.ref = f"A1:I{last_row}"

        if last_row >= 2:
            dv = DataValidation(
                type="list", formula1='"미확인,O,X"', allow_blank=True,
                showDropDown=False,
            )
            dv.error = "미확인/O/X 중 하나를 선택하세요."
            dv.errorTitle = "잘못된 입력"
            col_letter = get_column_letter(len(columns))
            dv_range = f"{col_letter}2:{col_letter}{last_row}"
            dv.add(dv_range)
            ws.add_data_validation(dv)
            for r in range(2, last_row + 1):
                ws.cell(row=r, column=len(columns), value="미확인")

    def create_statistics_sheet(
        self,
        ws,
        statistics: Dict[str, Any]
    ) -> None:
        """
        "변환 통계" 시트 생성.

        항목:
        - 전체 문제 수
        - 자동 확정 비율
        - 검토 필요 비율
        - 오류 유형별 빈도
        - 처리 시간

        Args:
            ws: openpyxl Worksheet
            statistics: 통계 데이터
                {
                    'total_problems': 100,
                    'auto_confirmed_ratio': 0.92,
                    'human_review_ratio': 0.08,
                    'error_breakdown': {...},
                    'total_duration_seconds': 300,
                    ...
                }
        """
        ws.append(["항목", "값"])
        self._apply_header_style(ws, 1)

        rows = [
            ("전체 문제 수", statistics.get("total_problems", 0)),
            ("자동 확정(AUTO) 비율", f"{statistics.get('auto_confirmed_ratio', 0.0):.1%}"),
            ("검토 필요(HUMAN_REVIEW) 비율", f"{statistics.get('human_review_ratio', 0.0):.1%}"),
            ("실패한 청크 수", statistics.get("failed_chunks", 0)),
            ("총 소요 시간(초)", statistics.get("total_duration_seconds", 0)),
        ]
        for label, value in rows:
            ws.append([label, value])

        error_breakdown: Dict[str, int] = statistics.get("error_breakdown", {}) or {}
        if error_breakdown:
            ws.append([])
            ws.append(["오류 유형", "빈도"])
            header_row = ws.max_row
            self._apply_header_style(ws, header_row)
            for issue_type, count in sorted(error_breakdown.items(), key=lambda kv: -kv[1]):
                ws.append([issue_type, count])

        self._auto_adjust_column_width(ws)

    def save_workbook(self, wb, output_path: str) -> Path:
        """
        Workbook 저장.

        Args:
            wb: openpyxl Workbook
            output_path: 저장 경로

        Returns:
            Path: 저장된 파일 경로

        Raises:
            IOError: 쓰기 실패
        """
        path = Path(output_path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            wb.save(str(path))
        except OSError as e:
            raise IOError(f"Excel 파일 저장 실패: {path} ({e})") from e
        return path

    # ------------------------------------------------------------------
    # 스타일 / 서식 내부 구현
    # ------------------------------------------------------------------

    def _write_header(self, ws, columns: List[str]) -> None:
        """헤더 행 작성."""
        ws.append(columns)

    def _write_question_rows(self, ws, start_row: int, question: Dict[str, Any]) -> int:
        """
        문제 1개를 선지 개수만큼의 행으로 작성.

        Args:
            ws: Worksheet
            start_row: 이 문제의 첫 행 번호
            question: 문제 딕셔너리 (id/text/options/confidence/status)

        Returns:
            int: 다음 문제가 시작할 행 번호
        """
        options = question.get("options", []) or []
        confidence = question.get("confidence", 0.0)
        status = question.get("status", "HUMAN_REVIEW")
        qid = question.get("id", "")
        qtext = question.get("text", "")

        if not options:
            options = [{"num": "", "text": "", "correct": False, "explanation": ""}]

        row = start_row
        for i, opt in enumerate(options):
            display_text = qtext if i == 0 else "동일"
            correct_symbol = "O" if opt.get("correct") else "X"
            ws.append([
                qid, display_text, opt.get("num", ""), opt.get("text", ""),
                correct_symbol, opt.get("explanation", ""), round(float(confidence), 3), status,
            ])
            cell_b = ws.cell(row=row, column=_QUESTION_TEXT_COL)
            cell_d = ws.cell(row=row, column=4)
            cell_f = ws.cell(row=row, column=6)
            cell_b.alignment = self.styles["wrap"]["alignment"]
            cell_d.alignment = self.styles["wrap"]["alignment"]
            cell_f.alignment = self.styles["wrap"]["alignment"]
            if i > 0:
                cell_b.fill = self.styles["duplicate_gray"]["fill"]
                cell_b.font = self.styles["duplicate_gray"]["font"]
            row += 1
        return row

    def _apply_header_style(self, ws, header_row: int) -> None:
        """
        헤더 행 스타일 적용.

        Args:
            ws: Worksheet
            header_row: 헤더 행 번호
        """
        for cell in ws[header_row]:
            cell.font = self.styles["header"]["font"]
            cell.fill = self.styles["header"]["fill"]
            cell.alignment = self.styles["header"]["alignment"]

    def _apply_conditional_formatting(self, ws, data_range: str) -> None:
        """
        조건부 서식 적용 (신뢰도 기반 배경색, 정오 O/X 색상, "동일" 회색).

        Args:
            ws: Worksheet
            data_range: 데이터 범위 (예: "A1:H100"), 헤더 행 포함해서 전달해도
                무방 (openpyxl은 규칙 적용 시 헤더 값도 평가하지만 문자열
                비교/숫자 비교 조건에 해당하지 않으므로 영향 없음)
        """
        _sheet_part, cell_range = data_range.split("!") if "!" in data_range else (None, data_range)
        (start_col, start_row), (end_col, end_row) = self._parse_range(cell_range)
        if end_row < 2:
            return

        confidence_col_letter = get_column_letter(_CONFIDENCE_COL)
        confidence_range = f"{confidence_col_letter}2:{confidence_col_letter}{end_row}"
        ws.conditional_formatting.add(
            confidence_range,
            CellIsRule(operator="lessThan", formula=[str(_LOW_CONFIDENCE_THRESHOLD)],
                       fill=self.styles["very_low_confidence"]["fill"], stopIfTrue=True),
        )
        ws.conditional_formatting.add(
            confidence_range,
            CellIsRule(operator="lessThan", formula=[str(_HUMAN_REVIEW_THRESHOLD)],
                       fill=self.styles["low_confidence"]["fill"]),
        )

        correct_col_letter = get_column_letter(_CORRECT_COL)
        correct_range = f"{correct_col_letter}2:{correct_col_letter}{end_row}"
        ws.conditional_formatting.add(
            correct_range,
            CellIsRule(operator="equal", formula=['"O"'],
                       fill=self.styles["correct_o"]["fill"]),
        )
        ws.conditional_formatting.add(
            correct_range,
            CellIsRule(operator="equal", formula=['"X"'],
                       fill=self.styles["correct_x"]["fill"]),
        )

        question_col_letter = get_column_letter(_QUESTION_TEXT_COL)
        question_range = f"{question_col_letter}2:{question_col_letter}{end_row}"
        ws.conditional_formatting.add(
            question_range,
            FormulaRule(formula=[f'{question_col_letter}2="동일"'],
                        fill=self.styles["duplicate_gray"]["fill"]),
        )

    def _parse_range(self, cell_range: str) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        """"A1:H100" 형식 범위를 ((시작열,시작행),(끝열,끝행))로 파싱."""
        from openpyxl.utils.cell import range_boundaries
        min_col, min_row, max_col, max_row = range_boundaries(cell_range)
        return (min_col, min_row), (max_col, max_row)

    def _auto_adjust_column_width(self, ws) -> None:
        """
        열 너비 자동 조정.

        각 열에서 가장 긴 값의 표시 길이(개행 기준 최대 줄 길이)를 측정해
        너비를 설정한다. 지나치게 넓어지는 것을 막기 위해 상한을 둔다.

        Args:
            ws: Worksheet
        """
        widths: Dict[int, int] = {}
        for row in ws.iter_rows():
            for cell in row:
                if cell.value is None:
                    continue
                lines = str(cell.value).split("\n")
                length = max(len(line) for line in lines) if lines else 0
                widths[cell.column] = max(widths.get(cell.column, _MIN_COLUMN_WIDTH), length)

        for col_idx, width in widths.items():
            ws.column_dimensions[get_column_letter(col_idx)].width = min(
                max(width + 2, _MIN_COLUMN_WIDTH), _MAX_COLUMN_WIDTH
            )

    def _derive_statistics(self, all_questions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """validation_results에 statistics가 없을 때 all_questions로부터 최소 통계 산출."""
        total = len({q.get("id") for q in all_questions}) if all_questions else 0
        auto = len({q.get("id") for q in all_questions if q.get("status") == "AUTO"})
        review = total - auto
        return {
            "total_problems": total,
            "auto_confirmed_ratio": (auto / total) if total else 0.0,
            "human_review_ratio": (review / total) if total else 0.0,
            "error_breakdown": {},
            "total_duration_seconds": 0,
        }
