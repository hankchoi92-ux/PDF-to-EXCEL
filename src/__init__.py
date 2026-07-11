"""
PDF → Excel 변환 자동화 (v6) - 코어 모듈 패키지

Phase 별 모듈 구성:
- Phase 0: preflight.py
- Phase 1: pdf_extractor.py, local_hint_generator.py, chunk_manager.py, text_metrics.py, local_corrector.py
- Phase 2: claude_cli_client.py, response_parser.py
- Phase 3: structure_validator.py, diff_validator.py, term_validator.py, confidence_scorer.py
- Phase 4: excel_builder.py

상태 관리: state_manager.py
통합 조정: auto_pipeline.py
CLI 진입: main.py
"""

__version__ = "6.0.0"
__author__ = "Hank Choi"
