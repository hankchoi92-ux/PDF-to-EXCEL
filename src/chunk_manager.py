"""
동적 청킹 관리 (토큰 기반)

추출된 텍스트를 토큰 한도에 맞춰 청크로 분할한다.
청크 경계는 항상 "문제 단위"로만 끊는다 — 문제 번호 패턴의 char_start
위치를 경계로 삼아 세그먼트를 만들기 때문에, 한 문제의 본문/선지/해설이
서로 다른 청크로 쪼개지는 일이 구조적으로 발생하지 않는다.

단방향 의존 원칙: pdf_extractor가 만든 question_patterns(순수 딕셔너리)만
입력으로 받고, pdf_extractor 모듈 자체는 import하지 않는다.
"""

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from exceptions import NoQuestionPatternsFoundError
from schemas import ChunkData

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 한국어 보수적 토큰 추정 기본값: 1토큰 ≈ 2자 (지시된 "2~3자/토큰" 범위 중
# 더 보수적인 쪽 = 같은 글자 수에 대해 더 많은 토큰으로 잡아 청크를 작게 유지)
DEFAULT_TOKEN_PER_CHAR_RATIO = 0.5


class ChunkManager:
    """
    토큰 기반 동적 청크 생성.

    입력 토큰 절약 + 출력 잘림 방지가 목표.
    """

    def __init__(self, max_tokens_per_chunk: int = 3500,
                 config: Optional[Dict[str, Any]] = None,
                 logger=None):
        """
        초기화.

        Args:
            max_tokens_per_chunk: 청크당 최대 토큰 수 (기본 3500)
            config: config.yaml 로드 결과 (chunking.token_per_char_ratio 등 참조)
            logger: 로거 인스턴스 (선택적)
        """
        import logging
        self.max_tokens = max_tokens_per_chunk
        self.config = config or {}
        self.logger = logger or logging.getLogger(__name__)
        self.token_per_char_ratio: float = float(
            self.config.get("chunking", {}).get(
                "token_per_char_ratio", DEFAULT_TOKEN_PER_CHAR_RATIO
            )
        )

    def estimate_tokens(self, text: str) -> int:
        """
        텍스트의 토큰 수 추정.

        한국어 보수적 추정: tokens = ceil(len(text) * token_per_char_ratio)
        기본 ratio=0.5는 "1토큰≈2자"에 해당하며, 지시된 "2~3자/토큰" 범위 중
        보수적인 끝값을 채택해 청크가 실제보다 작게 잡히도록 한다
        (출력 잘림보다 청크 수가 조금 늘어나는 쪽이 안전).

        Args:
            text: 추정할 텍스트

        Returns:
            int: 추정 토큰 수 (최소 0)
        """
        if not text:
            return 0
        return math.ceil(len(text) * self.token_per_char_ratio)

    def create_chunks(
        self,
        full_text: str,
        question_patterns: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        토큰 한도에 맞춰 동적 청크 생성.

        알고리즘:
        1. question_patterns를 char_start 순으로 정렬해 "문제 단위 세그먼트"로
           나눈다 (세그먼트 = [이번 문제 헤더 시작 ~ 다음 문제 헤더 시작 직전]).
           마지막 세그먼트는 전체 텍스트 끝까지.
        2. 세그먼트를 순서대로 누적하다 토큰 한도를 넘기기 직전에 청크를
           종료한다 (문제 경계에서만 자르므로 중간에 잘리는 일이 없음).
        3. 세그먼트 하나가 이미 한도를 초과하면 그 세그먼트만으로 단독 청크를
           만들고 경고 로그를 남긴다 (쪼개면 데이터 무결성이 깨지므로 예외
           대신 허용 + 경고를 택함).

        첫 문제 헤더 이전의 텍스트(표지, 안내문 등)는 문제에 속하지 않으므로
        청크에 포함하지 않는다.

        Args:
            full_text: 전체 텍스트 (pdf_extractor.extract_full_text() 결과)
            question_patterns: 문제 번호 패턴 리스트 (char_start 포함)

        Returns:
            List[Dict]: 청크 목록 (ChunkData.to_dict() 형식)
                [{
                    'chunk_id': 'chunk_001',
                    'question_range': [1, 8],
                    'text': '...',
                    'estimated_tokens': 3200,
                    'pages': [0, 1],
                    'question_count': 8,
                    'start_char': 0,
                    'end_char': 5000,
                }, ...]

        Raises:
            NoQuestionPatternsFoundError: question_patterns가 비어 있음
        """
        if not question_patterns:
            raise NoQuestionPatternsFoundError(
                "문제 번호 패턴이 감지되지 않아 청크 경계를 정할 수 없습니다. "
                "PDF의 문제 번호 형식이 지원 패턴('문N.', '(N)', 'N.' 등)과 "
                "다를 수 있습니다."
            )

        segments = self._build_segments(full_text, question_patterns)
        raw_chunks = self._pack_segments(segments)
        return [self._to_chunk_dict(idx, group) for idx, group in enumerate(raw_chunks, start=1)]

    def _build_segments(
        self,
        full_text: str,
        question_patterns: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        문제 번호 패턴을 기준으로 "문제 단위 세그먼트" 목록 생성.

        Args:
            full_text: 전체 텍스트
            question_patterns: 문제 번호 패턴 리스트

        Returns:
            List[Dict]: [{'question_id', 'page', 'text', 'start_char', 'end_char',
                          'tokens'}, ...] (char_start 오름차순)
        """
        ordered = sorted(question_patterns, key=lambda p: p["char_start"])
        segments: List[Dict[str, Any]] = []
        for i, pattern in enumerate(ordered):
            start = pattern["char_start"]
            end = ordered[i + 1]["char_start"] if i + 1 < len(ordered) else len(full_text)
            text = full_text[start:end].strip("\n")
            segments.append({
                "question_id": pattern["question_id"],
                "page": pattern.get("page", 0),
                "text": text,
                "start_char": start,
                "end_char": end,
                "tokens": self.estimate_tokens(text),
            })
        return segments

    def _pack_segments(
        self,
        segments: List[Dict[str, Any]]
    ) -> List[List[Dict[str, Any]]]:
        """
        세그먼트를 토큰 한도 내에서 청크로 묶는다 (bin-packing, 순서 유지).

        Args:
            segments: _build_segments() 결과

        Returns:
            List[List[Dict]]: 청크별 세그먼트 그룹
        """
        chunks: List[List[Dict[str, Any]]] = []
        current: List[Dict[str, Any]] = []
        current_tokens = 0

        for seg in segments:
            if seg["tokens"] > self.max_tokens:
                # 단일 문제가 한도를 초과 - 쪼갤 수 없으므로 단독 청크로 허용
                if current:
                    chunks.append(current)
                    current, current_tokens = [], 0
                chunks.append([seg])
                self.logger.warning(
                    "문제 %s: 예상 토큰 %d개가 청크 한도(%d)를 초과하지만 "
                    "문제 경계를 유지하기 위해 단독 청크로 처리합니다.",
                    seg["question_id"], seg["tokens"], self.max_tokens,
                )
                continue

            if current and current_tokens + seg["tokens"] > self.max_tokens:
                chunks.append(current)
                current, current_tokens = [], 0

            current.append(seg)
            current_tokens += seg["tokens"]

        if current:
            chunks.append(current)
        return chunks

    def _to_chunk_dict(self, index: int, group: List[Dict[str, Any]]) -> Dict[str, Any]:
        """세그먼트 그룹 하나를 ChunkData 딕셔너리로 변환."""
        question_ids = [seg["question_id"] for seg in group]
        pages = sorted({seg["page"] for seg in group})
        text = "\n\n".join(seg["text"] for seg in group)
        chunk = ChunkData(
            chunk_id=f"chunk_{index:03d}",
            question_range=(min(question_ids), max(question_ids)),
            text=text,
            estimated_tokens=sum(seg["tokens"] for seg in group),
            pages=pages,
            question_count=len(group),
            start_char=group[0]["start_char"],
            end_char=group[-1]["end_char"],
        )
        return chunk.to_dict()

    def create_manifest(self, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        전체 청크 메타데이터 생성.

        Args:
            chunks: create_chunks() 결과

        Returns:
            Dict: 메니페스트
                {
                    'total_chunks': 8,
                    'total_tokens_estimated': 25000,
                    'chunks': [{...}, ...],
                    'statistics': {
                        'avg_tokens_per_chunk': 3125.0,
                        'max_tokens_chunk_id': 'chunk_005',
                        'min_tokens_chunk_id': 'chunk_002',
                        'total_questions': 62,
                    }
                }
        """
        if not chunks:
            return {
                "total_chunks": 0,
                "total_tokens_estimated": 0,
                "chunks": [],
                "statistics": {},
            }

        total_tokens = sum(c["estimated_tokens"] for c in chunks)
        max_chunk = max(chunks, key=lambda c: c["estimated_tokens"])
        min_chunk = min(chunks, key=lambda c: c["estimated_tokens"])
        total_questions = sum(c["question_count"] for c in chunks)

        return {
            "total_chunks": len(chunks),
            "total_tokens_estimated": total_tokens,
            "chunks": chunks,
            "statistics": {
                "avg_tokens_per_chunk": round(total_tokens / len(chunks), 1),
                "max_tokens_chunk_id": max_chunk["chunk_id"],
                "min_tokens_chunk_id": min_chunk["chunk_id"],
                "total_questions": total_questions,
            },
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }

    def save_manifest(self, manifest: Dict[str, Any], output_path: str) -> None:
        """
        메니페스트를 JSON으로 저장.

        Args:
            manifest: create_manifest() 결과
            output_path: 저장 경로 (chunks/chunk_manifest.json)
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

    def save_chunk_texts(
        self,
        chunks: List[Dict[str, Any]],
        output_dir: str = "chunks/texts"
    ) -> List[Path]:
        """
        각 청크의 텍스트를 v6 설계 경로(chunks/texts/chunk_NNN.txt)에 저장.

        Args:
            chunks: create_chunks() 결과
            output_dir: 저장 디렉토리

        Returns:
            List[Path]: 저장된 파일 경로 목록
        """
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        saved: List[Path] = []
        for chunk in chunks:
            path = out_dir / f"{chunk['chunk_id']}.txt"
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(chunk["text"])
            saved.append(path)
        return saved
