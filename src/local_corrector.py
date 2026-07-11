"""
로컬 보정 (사전 기반 1차/2차 보정)

법률 용어 사전에 등록된 패턴만 명백한 오타로 간주해 수정한다.
Claude 변환 전(pre_correct)과 후(post_verify)에 각각 1회씩 사용된다.

⚠️ 설계 원칙 (반드시 준수):
  - 이 모듈은 사전(dictionaries/legal_terms.json)을 읽기만 한다.
    실행 중 발견한 새로운 용어/교정 사례를 사전에 자동으로 추가하거나
    학습하는 기능은 존재하지 않으며, 앞으로도 추가해서는 안 된다
    (환각으로 사전이 오염되는 것을 막기 위함).
  - 사전에 없는 용어는 절대 교정하지 않고 원본을 그대로 둔다.
    대신 post_verify()가 "의심 항목"으로만 보고한다.
  - 모든 교정은 logs/corrections/에 무엇을 왜 바꿨는지 기록되어
    사후에 사람이 검토할 수 있다.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from exceptions import DictionaryLoadError
from schemas import CorrectionRecord

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 이 길이 미만의 패턴은 사전 데이터 품질과 무관하게 교정 대상에서 제외한다.
# (예: 1글자 패턴이 실수로 등록되면 "질문"의 "질"까지 오염시킬 수 있는
#  치명적 오탐을 코드 레벨에서 원천 차단하는 안전장치)
_MIN_PATTERN_LENGTH = 2


class LocalCorrector:
    """
    사전 기반 로컬 보정.

    과도한 보정 금지 (확실하지 않으면 원본 유지).
    """

    def __init__(self, dictionary_path: str, config: Optional[Dict[str, Any]] = None,
                 logger=None):
        """
        초기화 및 사전 로드.

        Args:
            dictionary_path: legal_terms.json 경로
            config: config.yaml 로드 결과 (local_correction 섹션 참조)
            logger: 로거 인스턴스 (선택적)

        Raises:
            DictionaryLoadError: 사전 파일 없음 또는 형식 오류
        """
        import logging
        self.logger = logger or logging.getLogger(__name__)
        self.config = config or {}
        self.auto_correct_obvious: bool = bool(
            self.config.get("local_correction", {}).get("auto_correct_obvious", True)
        )
        self.corrections_log_dir = PROJECT_ROOT / "logs" / "corrections"

        self.dictionary_path = dictionary_path
        self.dictionary = self.load_dictionary(dictionary_path)
        self._pattern_index = self._build_pattern_index(self.dictionary)

    def load_dictionary(self, path: str) -> Dict[str, Any]:
        """
        법률 용어 사전 로드.

        형식:
        {
            "terms": {
                "정확한용어": {
                    "patterns": ["자주틀리는패턴1", "패턴2"],
                    "category": "민법총칙",
                    ...
                }
            }
        }

        Args:
            path: 사전 파일 경로

        Returns:
            Dict: 파싱된 사전

        Raises:
            DictionaryLoadError: 파일 없음 또는 JSON 형식 오류
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            raise DictionaryLoadError(f"법률 용어 사전 로드 실패: {path} ({e})") from e

        if not isinstance(data, dict) or "terms" not in data:
            raise DictionaryLoadError(
                f"사전 형식이 올바르지 않습니다 ('terms' 키 없음): {path}"
            )
        return data

    def _build_pattern_index(
        self, dictionary: Dict[str, Any]
    ) -> List[Tuple[str, str]]:
        """
        (오타 패턴, 정확한 용어) 인덱스 생성.

        - 패턴이 정확한 용어와 동일하면 제외 (오타가 아니라 정상 표기이므로).
        - _MIN_PATTERN_LENGTH 미만인 패턴은 오탐 위험이 커서 제외.
        - 긴 패턴이 짧은 패턴보다 먼저 매칭되도록 길이 내림차순 정렬
          (예: "특수한물권"을 먼저 검사해야 그 안의 "물권"에 부분매칭되지 않음).

        Args:
            dictionary: load_dictionary() 결과

        Returns:
            List[Tuple[str, str]]: [(pattern, canonical), ...] (길이 내림차순)
        """
        index: List[Tuple[str, str]] = []
        for canonical, info in dictionary.get("terms", {}).items():
            for pattern in info.get("patterns", []):
                if pattern == canonical:
                    continue
                if len(pattern) < _MIN_PATTERN_LENGTH:
                    self.logger.warning(
                        "사전 항목 '%s'의 패턴 '%s'는 %d자 미만이라 오탐 위험이 "
                        "커서 교정 대상에서 제외합니다.",
                        canonical, pattern, _MIN_PATTERN_LENGTH,
                    )
                    continue
                if not self._is_obvious_typo(pattern, canonical):
                    continue
                index.append((pattern, canonical))
        index.sort(key=lambda pc: len(pc[0]), reverse=True)
        return index

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def pre_correct(self, text: str, chunk_id: str = "unknown") -> Tuple[str, List[Dict[str, Any]]]:
        """
        Claude 전송 전 1차 보정.

        사전에 있는 명백한 패턴만 수정. 확실하지 않으면(사전에 없으면)
        원본을 그대로 둔다. 실제로 교정이 발생하면 logs/corrections/에 기록한다.

        Args:
            text: 원본 텍스트

        Returns:
            Tuple[str, List]: (보정된 텍스트, 수정 목록)
                수정 목록 항목: CorrectionRecord.to_dict() 형식
                {'chunk_id', 'original', 'corrected', 'canonical_term',
                 'location', 'confidence', 'timestamp'}
        """
        if not self.auto_correct_obvious or not text:
            return text, []

        hits = self._scan(text)
        if not hits:
            return text, []

        now = datetime.now().isoformat(timespec="seconds")
        corrected_parts: List[str] = []
        corrections: List[Dict[str, Any]] = []
        cursor = 0
        for hit in hits:
            corrected_parts.append(text[cursor:hit["start"]])
            corrected_parts.append(hit["canonical"])
            corrections.append(CorrectionRecord(
                chunk_id=chunk_id,
                original=hit["pattern"],
                corrected=hit["canonical"],
                canonical_term=hit["canonical"],
                location=f"offset {hit['start']}-{hit['end']}",
                confidence=hit["confidence"],
                timestamp=now,
            ).to_dict())
            cursor = hit["end"]
        corrected_parts.append(text[cursor:])
        corrected_text = "".join(corrected_parts)

        self._log_corrections(chunk_id, corrections)
        return corrected_text, corrections

    def post_verify(
        self, parsed_data: Dict[str, Any], chunk_id: str = "unknown"
    ) -> List[Dict[str, Any]]:
        """
        Claude 응답 후 2차 검증.

        JSON 내 텍스트에서 사전 패턴과 일치하는(=아직 교정되지 않은) 용어를
        찾아 의심 항목으로 보고한다. 여기서도 텍스트를 직접 고치지는 않는다
        — 실제 수정 여부는 사람의 검토(Excel "검토 필요" 시트) 또는 후속
        파이프라인 단계의 몫이다.

        Args:
            parsed_data: Claude JSON 응답 파싱 결과 ({'questions': [...]})

        Returns:
            List[Dict]: 의심 항목 목록
                [{'question_id': 3, 'field': 'option_①_text',
                  'found': '게약', 'expected_candidates': ['계약'],
                  'severity': 'high'}, ...]
        """
        issues: List[Dict[str, Any]] = []
        for question in parsed_data.get("questions", []):
            qid = question.get("id")
            for field_name, field_text in self._iter_question_fields(question):
                for hit in self._scan(field_text):
                    issues.append({
                        "question_id": qid,
                        "field": field_name,
                        "found": hit["pattern"],
                        "expected_candidates": [hit["canonical"]],
                        "severity": "high" if hit["confidence"] == "high" else "medium",
                    })
        return issues

    # ------------------------------------------------------------------
    # 내부 구현
    # ------------------------------------------------------------------

    def _iter_question_fields(self, question: Dict[str, Any]):
        """questions[i] 내부에서 검증할 텍스트 필드를 (필드명, 텍스트) 쌍으로 순회."""
        yield "text", question.get("text", "") or ""
        for opt in question.get("options", []):
            num = opt.get("num", "?")
            yield f"option_{num}_text", opt.get("text", "") or ""
            yield f"option_{num}_explanation", opt.get("explanation", "") or ""

    def _scan(self, text: str) -> List[Dict[str, Any]]:
        """
        사전 패턴 인덱스로 텍스트를 스캔해 교정 대상 위치를 찾는다.

        긴 패턴을 먼저 검사하고(겹치는 짧은 패턴 방지), 이미 처리된 구간과
        겹치는 매칭은 건너뛴다.

        Args:
            text: 스캔할 텍스트

        Returns:
            List[Dict]: [{'start', 'end', 'pattern', 'canonical', 'confidence'}, ...]
                (start 오름차순)
        """
        if not text:
            return []

        used_spans: List[Tuple[int, int]] = []
        results: List[Dict[str, Any]] = []
        for pattern, canonical in self._pattern_index:
            for m in re.finditer(re.escape(pattern), text):
                s, e = m.start(), m.end()
                if any(s < ue and e > us for us, ue in used_spans):
                    continue
                results.append({
                    "start": s, "end": e,
                    "pattern": pattern, "canonical": canonical,
                    "confidence": self._confidence_for(pattern, canonical),
                })
                used_spans.append((s, e))
        results.sort(key=lambda r: r["start"])
        return results

    def _extract_legal_terms(self, text: str) -> List[str]:
        """
        텍스트에서 사전에 등록된 정확한 법률 용어(정상 표기) 목록 추출.

        Args:
            text: 텍스트

        Returns:
            List[str]: 텍스트에 등장하는 사전상 정확한 용어 목록 (중복 제거)
        """
        return sorted({
            canonical for canonical in self.dictionary.get("terms", {})
            if canonical in text
        })

    def _find_correction_candidates(self, term: str) -> List[str]:
        """
        주어진 문자열이 오타 패턴으로 등록된 경우 교정 후보(정확한 용어) 반환.

        Args:
            term: 검사할 문자열 (사전의 오타 패턴과 정확히 일치해야 함)

        Returns:
            List[str]: 교정 후보 목록 (없으면 빈 리스트)
        """
        return [canonical for pattern, canonical in self._pattern_index if pattern == term]

    def _is_obvious_typo(self, original: str, expected: str) -> bool:
        """
        명백한 오타인지 판단.

        기준:
        - 길이가 같고 정확히 1글자만 다름 → 명백한 오타 (high)
        - 길이가 1글자만 차이남 (삽입/누락 추정) → 명백한 오타 (medium)
        - 그 외 (길이 차이 2 이상 등) → 불확실하므로 오타로 보지 않음

        Args:
            original: 원본(패턴) 문자열
            expected: 예상 정정값(사전상 정확한 용어)

        Returns:
            bool: 명백한 오타 여부
        """
        if original == expected:
            return False
        len_diff = abs(len(original) - len(expected))
        if len_diff == 0:
            diff_count = sum(1 for a, b in zip(original, expected) if a != b)
            return diff_count == 1
        return len_diff == 1

    def _confidence_for(self, original: str, canonical: str) -> str:
        """길이가 같은(1글자 치환) 경우 high, 아니면 medium."""
        return "high" if len(original) == len(canonical) else "medium"

    def _log_corrections(self, chunk_id: str, corrections: List[Dict[str, Any]]) -> None:
        """
        교정 내역을 logs/corrections/에 기록.

        - logs/corrections/{chunk_id}_corrections.json: 청크별 상세 기록(리스트)
        - logs/corrections/corrections.log: 사람이 훑어보기 좋은 누적 로그

        Args:
            chunk_id: 청크 ID
            corrections: pre_correct()가 만든 CorrectionRecord.to_dict() 목록
        """
        if not corrections:
            return
        try:
            self.corrections_log_dir.mkdir(parents=True, exist_ok=True)

            detail_path = self.corrections_log_dir / f"{chunk_id}_corrections.json"
            with open(detail_path, "w", encoding="utf-8") as f:
                json.dump(corrections, f, ensure_ascii=False, indent=2)

            log_path = self.corrections_log_dir / "corrections.log"
            with open(log_path, "a", encoding="utf-8") as f:
                for c in corrections:
                    f.write(
                        f"[{c['timestamp']}] {c['chunk_id']}: "
                        f"{c['original']} -> {c['corrected']} "
                        f"({c['location']}, {c['confidence']})\n"
                    )
        except OSError as e:
            self.logger.warning("교정 로그 기록 실패 (%s): %s", chunk_id, e)
