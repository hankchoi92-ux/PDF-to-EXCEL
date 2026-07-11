"""
프로젝트 전용 예외 클래스

Phase 1 전처리 파이프라인(pdf_extractor → chunk_manager →
local_hint_generator → local_corrector)에서 발생하는 오류를
표준 예외(ValueError, OSError 등)와 구분해 상위 계층(auto_pipeline)이
오류 유형별로 다른 대응(중단 / 건너뜀 / 안내 메시지)을 할 수 있게 한다.
"""


class ProjectError(Exception):
    """프로젝트 전용 예외의 최상위 클래스."""
    pass


# ---------------------------------------------------------------------
# PDF 추출 (pdf_extractor.py)
# ---------------------------------------------------------------------

class PDFExtractionError(ProjectError):
    """PDF 텍스트/구조 추출 실패의 기본 클래스."""
    pass


class PDFNotFoundError(PDFExtractionError):
    """PDF 파일이 존재하지 않음."""
    pass


class PDFCorruptedError(PDFExtractionError):
    """PDF 파일이 손상되어 열 수 없음."""
    pass


class PDFEncryptedError(PDFExtractionError):
    """PDF가 암호화되어 있고 빈 비밀번호로 해제할 수 없음."""
    pass


class PDFEmptyError(PDFExtractionError):
    """PDF에서 추출 가능한 텍스트가 전혀 없음 (스캔 이미지 전용 PDF 등)."""
    pass


class PageRangeError(PDFExtractionError):
    """요청한 페이지 번호가 문서 범위를 벗어남."""
    pass


class BlockExtractionError(PDFExtractionError):
    """특정 페이지/블록 단위 추출 중 개별 오류 (전체 중단 대상 아님)."""
    pass


# ---------------------------------------------------------------------
# 청킹 (chunk_manager.py)
# ---------------------------------------------------------------------

class ChunkingError(ProjectError):
    """청크 생성 실패의 기본 클래스."""
    pass


class NoQuestionPatternsFoundError(ChunkingError):
    """문제 번호 패턴을 하나도 감지하지 못해 청킹 기준이 없음."""
    pass


class ChunkTooLargeError(ChunkingError):
    """단일 문제 하나만으로도 토큰 상한을 초과함 (경고성, 진행은 계속)."""
    pass


# ---------------------------------------------------------------------
# 힌트 생성 (local_hint_generator.py)
# ---------------------------------------------------------------------

class HintGenerationError(ProjectError):
    """힌트 생성/저장 실패."""
    pass


# ---------------------------------------------------------------------
# 사전 및 보정 (local_corrector.py)
# ---------------------------------------------------------------------

class DictionaryError(ProjectError):
    """법률 용어 사전 관련 오류의 기본 클래스."""
    pass


class DictionaryLoadError(DictionaryError):
    """사전 파일을 찾을 수 없거나 형식이 올바르지 않음."""
    pass
