"""
상태 머신 관리 (v6)

파이프라인 상태 추적, 중단 후 재개, 오류 복구.
PAUSED_LIMIT 상태로 Pro 사용량 한도 대응:
  - claude_cli_client가 RATE_LIMIT을 감지하면 pause_for_limit() 호출
  - resume_at(재개 예정 시각)을 기록하고 상태 파일에 저장
  - wait_and_resume()이 남은 시간을 대기한 뒤 PAUSED_LIMIT 청크를
    CHUNK_READY로 되돌려 중단 지점부터 정확히 재개
"""

import json
import logging
import os
import time
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class PipelineState(Enum):
    """파이프라인 상태 정의."""
    PREPARED = "PREPARED"                   # 초기 상태
    TEXT_EXTRACTED = "TEXT_EXTRACTED"       # PDF 텍스트 추출 완료
    HINTS_GENERATED = "HINTS_GENERATED"     # 로컬 힌트 생성 완료
    CHUNKS_CREATED = "CHUNKS_CREATED"       # 청크 생성 완료
    CHUNK_READY = "CHUNK_READY"             # Claude 입력 준비 완료
    SENT = "SENT"                           # Claude 전송 완료
    RESPONDED = "RESPONDED"                 # 응답 수신 완료
    PARSED = "PARSED"                       # JSON 파싱 완료
    VALIDATED = "VALIDATED"                 # 검증 완료
    COMPLETED = "COMPLETED"                 # 청크별 최종 완료
    FAILED = "FAILED"                       # 실패
    PAUSED_LIMIT = "PAUSED_LIMIT"           # ★ v6: Pro 사용량 한도 일시정지 (재개 가능)
    SKIPPED = "SKIPPED"                     # 건너뜀


class StateTransitionError(Exception):
    """상태 전이 오류."""
    pass


# 재시도/재개가 가능한 상태 (COMPLETED/SKIPPED 외 전부 후보)
RESUMABLE_STATES = {
    PipelineState.CHUNK_READY,
    PipelineState.SENT,          # 크래시 복구: 전송 중 중단된 청크
    PipelineState.FAILED,
    PipelineState.PAUSED_LIMIT,
}


class StateManager:
    """
    파이프라인 상태 머신 관리.

    상태 저장/로드, 전이 검증, 중단/재개(특히 PAUSED_LIMIT) 지원.
    상태 파일은 매 전이마다 원자적으로 저장되므로, 프로세스가 어느
    시점에 죽어도 재실행 시 정확한 지점부터 이어갈 수 있다.
    """

    # 허용되는 상태 전이
    TRANSITIONS = {
        PipelineState.PREPARED: [PipelineState.TEXT_EXTRACTED, PipelineState.CHUNK_READY],
        PipelineState.TEXT_EXTRACTED: [PipelineState.HINTS_GENERATED],
        PipelineState.HINTS_GENERATED: [PipelineState.CHUNKS_CREATED],
        PipelineState.CHUNKS_CREATED: [PipelineState.CHUNK_READY],
        PipelineState.CHUNK_READY: [PipelineState.SENT, PipelineState.SKIPPED],
        PipelineState.SENT: [
            PipelineState.RESPONDED,
            PipelineState.PAUSED_LIMIT,   # 사용량 한도 감지
            PipelineState.FAILED,
            PipelineState.CHUNK_READY,    # 크래시 복구 (전송 중 중단 → 재준비)
        ],
        PipelineState.RESPONDED: [PipelineState.PARSED, PipelineState.FAILED],
        PipelineState.PARSED: [PipelineState.VALIDATED, PipelineState.FAILED],
        PipelineState.VALIDATED: [PipelineState.COMPLETED, PipelineState.FAILED],
        PipelineState.PAUSED_LIMIT: [PipelineState.CHUNK_READY],  # 한도 해제 후 재개
        PipelineState.FAILED: [PipelineState.CHUNK_READY, PipelineState.SKIPPED],  # 재시도/포기
        PipelineState.COMPLETED: [],
        PipelineState.SKIPPED: [PipelineState.CHUNK_READY],  # 수동 재시도 허용
    }

    def __init__(self, state_file: str, logger: Optional[logging.Logger] = None,
                 config: Optional[Dict[str, Any]] = None):
        """
        초기화.

        Args:
            state_file: 상태 저장 파일 경로 (state/pipeline_state.json)
            logger: 로거 인스턴스 (없으면 모듈 로거)
            config: config.yaml 로드 결과 (limit_recheck_minutes 등 참조)
        """
        self.state_file = Path(state_file)
        self.logger = logger or logging.getLogger(__name__)
        self.config = config or {}
        self.state: Dict[str, Any] = self.load_state()

    # ------------------------------------------------------------------
    # 로드 / 저장
    # ------------------------------------------------------------------

    def load_state(self) -> Dict[str, Any]:
        """
        상태 파일 로드. 파일이 없으면 초기 상태 생성.
        손상된 파일은 .corrupt-<timestamp> 로 백업 후 새로 시작.

        Returns:
            Dict: 로드된 상태
        """
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    state = json.load(f)
                if not isinstance(state, dict) or "chunks" not in state:
                    raise ValueError("상태 파일 구조가 올바르지 않음")
                self.logger.info(
                    "상태 파일 로드: %s (청크 %d개)",
                    self.state_file, len(state.get("chunks", {}))
                )
                return state
            except (json.JSONDecodeError, ValueError, OSError) as e:
                backup = self.state_file.with_suffix(
                    f".corrupt-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                )
                try:
                    self.state_file.rename(backup)
                    self.logger.warning(
                        "상태 파일 손상(%s) → %s 로 백업 후 초기화", e, backup.name
                    )
                except OSError:
                    self.logger.warning("상태 파일 손상(%s), 백업 실패 → 초기화", e)
        return self._fresh_state()

    def _fresh_state(self) -> Dict[str, Any]:
        """초기 상태 구조 생성."""
        now = datetime.now().isoformat(timespec="seconds")
        return {
            "pdf_path": None,
            "created_at": now,
            "last_updated": now,
            "global_state": PipelineState.PREPARED.value,
            "pause_info": None,   # 사용량 한도 정보 {'resume_at': epoch, 'reason': ...}
            "chunks": {},
        }

    def save_state(self) -> None:
        """
        현재 상태를 파일로 원자적으로 저장.

        임시 파일에 쓴 뒤 os.replace()로 교체 — 저장 도중 프로세스가
        죽어도 기존 상태 파일이 반파되지 않도록 보장.
        """
        self.state["last_updated"] = datetime.now().isoformat(timespec="seconds")
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.state_file.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.state_file)

    # ------------------------------------------------------------------
    # 청크 등록 / 상태 전이
    # ------------------------------------------------------------------

    def register_chunk(self, chunk_id: str,
                       initial_state: PipelineState = PipelineState.CHUNK_READY,
                       metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        청크를 상태 머신에 등록. 이미 등록된 청크는 무시 (재실행 시 상태 보존).

        Args:
            chunk_id: 청크 ID
            initial_state: 초기 상태 (기본 CHUNK_READY)
            metadata: 초기 메타데이터
        """
        if chunk_id in self.state["chunks"]:
            return
        now = datetime.now().isoformat(timespec="seconds")
        entry: Dict[str, Any] = {
            "state": initial_state.value,
            "timestamp": now,
            "retry_count": 0,
            "error_type": None,
            "history": [{"state": initial_state.value, "timestamp": now}],
        }
        if metadata:
            entry.update(metadata)
        self.state["chunks"][chunk_id] = entry
        self.save_state()

    def _normalize_state(self, state: Any) -> PipelineState:
        """문자열/enum 입력을 PipelineState로 정규화."""
        if isinstance(state, PipelineState):
            return state
        try:
            return PipelineState(str(state))
        except ValueError:
            raise StateTransitionError(f"알 수 없는 상태: {state!r}")

    def validate_transition(self, current_state: str, new_state: str) -> bool:
        """
        상태 전이 유효성 검증.

        Args:
            current_state: 현재 상태 (문자열 또는 enum)
            new_state: 새로운 상태 (문자열 또는 enum)

        Returns:
            bool: 전이 가능 여부
        """
        cur = self._normalize_state(current_state)
        new = self._normalize_state(new_state)
        if cur == new:
            return True  # 동일 상태 재기록은 no-op으로 허용 (메타데이터 갱신용)
        return new in self.TRANSITIONS.get(cur, [])

    def transition(self, chunk_id: str, new_state: str,
                   metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        상태 전이 실행.

        1. 전이 유효성 검증 (TRANSITIONS 규칙)
        2. 메타데이터 병합 기록 (시간, 오류, retry_count, duration 등)
        3. 히스토리 추가 후 상태 파일 원자 저장

        Args:
            chunk_id: 청크 ID. "global"이면 전역 파이프라인 상태를 갱신
                      (전역 상태는 Phase 표시용이라 전이 규칙을 강제하지 않음)
            new_state: 새로운 상태
            metadata: 추가 정보 (error_type, duration_seconds, cli_method 등)

        Raises:
            StateTransitionError: 유효하지 않은 전이 또는 미등록 청크
        """
        new = self._normalize_state(new_state)
        now = datetime.now().isoformat(timespec="seconds")

        if chunk_id == "global":
            self.state["global_state"] = new.value
            self.save_state()
            return

        if chunk_id not in self.state["chunks"]:
            # 미등록 청크: CHUNK_READY로의 진입만 자동 등록 허용
            if new == PipelineState.CHUNK_READY:
                self.register_chunk(chunk_id, metadata=metadata)
                return
            raise StateTransitionError(f"미등록 청크: {chunk_id} (→ {new.value} 불가)")

        entry = self.state["chunks"][chunk_id]
        cur = self._normalize_state(entry["state"])
        if not self.validate_transition(cur, new):
            raise StateTransitionError(
                f"{chunk_id}: 유효하지 않은 전이 {cur.value} → {new.value}"
            )

        entry["state"] = new.value
        entry["timestamp"] = now
        if metadata:
            # retry_count는 누적 관리, 나머지는 최신값으로 병합
            if "retry_count" in metadata:
                entry["retry_count"] = metadata["retry_count"]
            entry.update({k: v for k, v in metadata.items() if k != "retry_count"})
        history_item = {"state": new.value, "timestamp": now}
        if metadata:
            history_item.update(metadata)
        entry.setdefault("history", []).append(history_item)

        self.save_state()
        self.logger.debug("%s: %s → %s", chunk_id, cur.value, new.value)

    # ------------------------------------------------------------------
    # PAUSED_LIMIT: 사용량 한도 일시정지 / 재개 (v6 핵심)
    # ------------------------------------------------------------------

    def pause_for_limit(self, chunk_id: str,
                        reset_at: Optional[float] = None,
                        metadata: Optional[Dict[str, Any]] = None) -> float:
        """
        Rate Limit 감지 시 청크를 PAUSED_LIMIT으로 전이하고 재개 시각을 기록.

        재개 시각 결정:
        - CLI 출력에서 파싱한 reset_at(epoch 초)이 있으면 그 시각 사용
          (claude CLI는 "usage limit reached|<epoch>" 형태로 리셋 시각을 알려줌)
        - 없으면 now + limit_recheck_minutes(기본 30분)

        Args:
            chunk_id: 한도에 걸린 청크 ID
            reset_at: 한도 리셋 예정 시각 (epoch 초, CLI 출력에서 파싱된 값)
            metadata: 추가 기록 정보 (stderr 요약 등)

        Returns:
            float: 확정된 재개 예정 시각 (epoch 초)
        """
        recheck_minutes = self.config.get("cli", {}).get("limit_recheck_minutes", 30)
        now = time.time()
        if reset_at and reset_at > now:
            resume_at = reset_at
        else:
            resume_at = now + recheck_minutes * 60

        meta = dict(metadata or {})
        meta.update({
            "error_type": "RATE_LIMIT",
            "resume_at": resume_at,
            "resume_at_iso": datetime.fromtimestamp(resume_at).isoformat(timespec="seconds"),
        })
        self.transition(chunk_id, PipelineState.PAUSED_LIMIT, meta)

        # 전역 일시정지 정보 기록 (재실행 시 get_wait_seconds가 참조)
        self.state["pause_info"] = {
            "resume_at": resume_at,
            "paused_chunk": chunk_id,
            "paused_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.save_state()
        self.logger.warning(
            "사용량 한도 감지 (%s) → PAUSED_LIMIT, 재개 예정: %s",
            chunk_id, meta["resume_at_iso"]
        )
        return resume_at

    def get_wait_seconds(self) -> float:
        """
        PAUSED_LIMIT 재개까지 남은 대기 시간(초) 계산.

        - PAUSED_LIMIT 청크들의 resume_at 중 가장 늦은 시각 기준
        - 기록이 없으면 config의 limit_recheck_minutes 기본값 사용

        Returns:
            float: 남은 대기 시간(초), 이미 지났으면 0
        """
        now = time.time()
        resume_ats = [
            c.get("resume_at") for c in self.state["chunks"].values()
            if c.get("state") == PipelineState.PAUSED_LIMIT.value and c.get("resume_at")
        ]
        pause_info = self.state.get("pause_info") or {}
        if pause_info.get("resume_at"):
            resume_ats.append(pause_info["resume_at"])

        if not resume_ats:
            recheck_minutes = self.config.get("cli", {}).get("limit_recheck_minutes", 30)
            return recheck_minutes * 60.0
        return max(0.0, max(resume_ats) - now)

    def wait_and_resume(self,
                        sleep_fn: Callable[[float], None] = time.sleep,
                        log_interval_seconds: float = 300.0) -> List[str]:
        """
        사용량 한도 대기 후 중단된 청크를 재개 가능 상태로 복구.

        동작:
        1. PAUSED_LIMIT 청크가 없으면 즉시 재개 목록 반환
        2. get_wait_seconds()만큼 대기 (log_interval마다 남은 시간 로깅)
        3. 모든 PAUSED_LIMIT 청크를 CHUNK_READY로 전이 (resume 이력 기록)
        4. 전역 pause_info 해제
        5. 재처리 대상 청크 ID 목록을 순서대로 반환

        프로세스가 대기 중 죽어도 상태 파일에 resume_at이 남아 있으므로,
        재실행 시 이 메서드가 남은 시간만 마저 대기하고 이어간다.

        Args:
            sleep_fn: 대기 함수 (테스트 시 주입 가능, 기본 time.sleep)
            log_interval_seconds: 대기 중 로그 출력 간격

        Returns:
            List[str]: 재개할 청크 ID 목록 (정렬됨)
        """
        paused = [
            cid for cid, c in self.state["chunks"].items()
            if c.get("state") == PipelineState.PAUSED_LIMIT.value
        ]
        if not paused:
            return self.get_resumable_chunks()

        remaining = self.get_wait_seconds()
        self.logger.warning(
            "사용량 한도 대기 시작: %.1f분 후 재개 (%d개 청크 일시정지)",
            remaining / 60.0, len(paused)
        )
        while remaining > 0:
            step = min(remaining, log_interval_seconds)
            sleep_fn(step)
            remaining -= step
            if remaining > 0:
                self.logger.info("한도 해제 대기 중... 남은 시간 %.1f분", remaining / 60.0)

        for cid in sorted(paused):
            self.transition(cid, PipelineState.CHUNK_READY,
                            {"resumed_from": "PAUSED_LIMIT"})
        self.state["pause_info"] = None
        self.save_state()
        self.logger.info("사용량 한도 해제 → %d개 청크 재개", len(paused))
        return self.get_resumable_chunks()

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------

    def get_resumable_chunks(self) -> List[str]:
        """
        재개/재시도 대상 청크 ID 목록 반환.

        대상 상태: CHUNK_READY, SENT(크래시 복구), FAILED, PAUSED_LIMIT.
        SENT/FAILED 청크는 CHUNK_READY로 자동 복원 후 포함
        (PAUSED_LIMIT은 wait_and_resume()이 별도 처리).

        Returns:
            List[str]: 청크 ID 목록 (ID 순 정렬 → 문제 번호 순서 보장)
        """
        resumable = []
        for cid in sorted(self.state["chunks"].keys()):
            entry = self.state["chunks"][cid]
            st = self._normalize_state(entry["state"])
            if st in (PipelineState.SENT, PipelineState.FAILED):
                self.transition(cid, PipelineState.CHUNK_READY,
                                {"resumed_from": st.value})
                resumable.append(cid)
            elif st in (PipelineState.CHUNK_READY, PipelineState.PAUSED_LIMIT):
                resumable.append(cid)
        return resumable

    def get_chunk_state(self, chunk_id: str) -> Optional[str]:
        """단일 청크의 현재 상태 문자열 반환 (미등록 시 None)."""
        entry = self.state["chunks"].get(chunk_id)
        return entry["state"] if entry else None

    def get_progress(self) -> Dict[str, Any]:
        """
        전체 진행률 반환.

        ETA는 COMPLETED 청크들의 duration_seconds 평균 × 남은 청크 수로 추정.

        Returns:
            Dict: {'completed', 'total', 'percentage', 'paused', 'failed',
                   'remaining', 'eta_seconds'}
        """
        chunks = self.state["chunks"]
        total = len(chunks)
        counts = {"completed": 0, "paused": 0, "failed": 0, "skipped": 0}
        durations: List[float] = []

        for entry in chunks.values():
            st = entry.get("state")
            if st == PipelineState.COMPLETED.value:
                counts["completed"] += 1
                if entry.get("duration_seconds"):
                    durations.append(float(entry["duration_seconds"]))
            elif st == PipelineState.PAUSED_LIMIT.value:
                counts["paused"] += 1
            elif st == PipelineState.FAILED.value:
                counts["failed"] += 1
            elif st == PipelineState.SKIPPED.value:
                counts["skipped"] += 1

        done = counts["completed"] + counts["skipped"]
        remaining = total - done
        avg = (sum(durations) / len(durations)) if durations else None
        return {
            "completed": counts["completed"],
            "total": total,
            "percentage": round(done / total * 100.0, 1) if total else 0.0,
            "paused": counts["paused"],
            "failed": counts["failed"],
            "remaining": remaining,
            "eta_seconds": round(avg * remaining, 1) if avg is not None else None,
        }
