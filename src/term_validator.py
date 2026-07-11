"""
법률 용어 검증 (Phase 3)

Claude 변환 결과의 법률 용어 정확도 검증.
사전 기반 2차 검증.

⚠️ 설계 원칙 (local_corrector.py와 동일):
  - 이 모듈은 사전(dictionaries/legal_terms.json)을 읽기만 한다.
    검증 중 발견한 용어를 사전에 자동으로 추가/학습하는 기능은
    존재하지 않으며, 앞으로도 추가해서는 안 된다.
  - 이 모듈은 텍스트를 직접 수정하지 않는다. 사전에 등록된 오타 패턴이
    Claude 결과에 여전히 남아있는지(=local_corrector가 교정했어야 할
    용어로 회귀했는지)만 탐지해 이슈로 보고한다.
"""

import json
import logging
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

from exceptions import DictionaryLoadError

# 이 길이 미만의 패턴은 오탐 위험이 커서 검증 대상에서 제외한다.
_MIN_PATTERN_LENGTH = 2


@dataclass
class TermIssue:
    """법률 용어 검증 이슈."""
    issue_type: str  # TYPO_REGRESSION | ...
    severity: str    # ERROR | WARNING | INFO
    term: str        # 해당 용어 (사전에 등록된 오타 패턴)
    location: str    # 위치 (예: "question_3, option_②_text")
    suggestion: str = ""  # 제안 (교정 후보)


class TermValidator:
    """
    법률 용어 정확도 검증 (사전 기반 패턴 매칭).
    """

    def __init__(self, dictionary_path: str, logger: Optional[logging.Logger] = None):
        """
        초기화 및 사전 로드.

        Args:
            dictionary_path: legal_terms.json 경로
            logger: 로거 인스턴스 (선택적)

        Raises:
            DictionaryLoadError: 사전 파일 없음 또는 형식 오류
        """
        self.logger = logger or logging.getLogger(__name__)
        self.dictionary_path = dictionary_path
        self.dictionary = self.load_dictionary(dictionary_path)
        self._pattern_index = self._build_pattern_index(self.dictionary)

    def load_dictionary(self, path: str) -> Dict[str, Any]:
        """
        법률 용어 사전 로드.

        Args:
            path: 사전 파일 경로

        Returns:
            Dict: 로드된 사전

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

    def verify(self, parsed_data: Dict[str, Any]) -> List[TermIssue]:
        """
        Claude 변환 결과의 법률 용어 검증.

        단계:
        1. questions 배열에서 텍스트 추출 (text, option.text, explanation)
        2. 사전에 등록된 오타 패턴이 텍스트 내에 남아있는지 스캔
        3. 발견된 패턴을 회귀(regression) 이슈로 플래깅

        사전에 없는(등록되지 않은) 용어는 검증 대상이 아니다
        (NLP 기반 미등록 용어 추출은 이 모듈의 범위 밖).

        Args:
            parsed_data: Claude JSON 파싱 결과

        Returns:
            List[TermIssue]: 발견된 이슈 목록
        """
        issues: List[TermIssue] = []
        parsed_data = parsed_data or {}

        for question in parsed_data.get("questions", []) or []:
            qid = question.get("id", 0)
            for field_name, field_text in self._iter_question_fields(question):
                for hit in self._scan(field_text):
                    issues.append(TermIssue(
                        issue_type="TYPO_REGRESSION",
                        severity="WARNING" if hit["confidence"] == "medium" else "ERROR",
                        term=hit["pattern"],
                        location=f"question_{qid}, {field_name}",
                        suggestion=hit["canonical"],
                    ))

        self.logger.info("용어 검증 완료: 이슈 %d건", len(issues))
        return issues

    def _iter_question_fields(self, question: Dict[str, Any]):
        """questions[i] 내부에서 검증할 텍스트 필드를 (필드명, 텍스트) 쌍으로 순회."""
        yield "text", question.get("text", "") or ""
        for opt in question.get("options", []) or []:
            num = opt.get("num", "?")
            yield f"option_{num}_text", opt.get("text", "") or ""
            yield f"option_{num}_explanation", opt.get("explanation", "") or ""

    def _extract_legal_terms(self, text: str) -> List[str]:
        """
        텍스트에서 사전에 등록된 정확한(정상 표기) 법률 용어 목록 추출.

        Args:
            text: 텍스트

        Returns:
            List[str]: 텍스트에 등장하는 사전상 정확한 용어 목록 (중복 제거)
        """
        if not text:
            return []
        return sorted({
            canonical for canonical in self.dictionary.get("terms", {})
            if canonical in text
        })

    def _validate_term(self, term: str) -> Tuple[bool, str, str]:
        """
        단일 용어 검증.

        Args:
            term: 검증할 용어

        Returns:
            Tuple[bool, str, str]: (valid, correction_if_invalid, confidence_level)
                - valid: 사전 정확도(오타 패턴이 아니면 True)
                - correction_if_invalid: 교정 제안 (유효하지 않으면)
                - confidence_level: 제안의 신뢰도 (high|medium|low)
        """
        if term in self.dictionary.get("terms", {}):
            return True, "", "high"

        correction, confidence = self._find_correction(term)
        if correction:
            return False, correction, confidence
        return True, "", "low"

    def _find_correction(self, term: str) -> Tuple[Optional[str], str]:
        """
        용어의 교정 후보 찾기.

        Args:
            term: 용어

        Returns:
            Tuple[str|None, str]: (교정된 용어, 신뢰도)
                - 교정 불가능하면 (None, "low")
        """
        for pattern, canonical in self._pattern_index:
            if pattern == term:
                return canonical, self._confidence_for(pattern, canonical)
        return None, "low"

    # ------------------------------------------------------------------
    # 내부 구현
    # ------------------------------------------------------------------

    def _build_pattern_index(
        self, dictionary: Dict[str, Any]
    ) -> List[Tuple[str, str]]:
        """
        (오타 패턴, 정확한 용어) 인덱스 생성.

        local_corrector와 달리 "명백한 오타"로 제한하지 않는다 — 이 모듈은
        텍스트를 수정하지 않고 탐지만 하므로, 사전에 등록된 모든 오타
        패턴을 검증 대상으로 삼는 것이 안전하다.

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
                    continue
                index.append((pattern, canonical))
        index.sort(key=lambda pc: len(pc[0]), reverse=True)
        return index

    def _scan(self, text: str) -> List[Dict[str, Any]]:
        """
        사전 패턴 인덱스로 텍스트를 스캔해 잔존 오타 위치를 찾는다.

        긴 패턴을 먼저 검사하고(겹치는 짧은 패턴 방지), 이미 처리된 구간과
        겹치는 매칭은 건너뛴다.

        Args:
            text: 스캔할 텍스트

        Returns:
            List[Dict]: [{'start', 'end', 'pattern', 'canonical', 'confidence'}, ...]
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

    def _confidence_for(self, original: str, canonical: str) -> str:
        """길이가 같은(치환형 오타) 경우 high, 아니면(삽입/누락형) medium."""
        return "high" if len(original) == len(canonical) else "medium"
