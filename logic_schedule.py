# -*- coding: utf-8 -*-
"""
logic_schedule.py
─────────────────────────────────────────────────────────────
공정표 고도화 엔진 — 고도화 ③

배경
  기존 공정표는 행별 시작일/종료일을 손으로 찍어 px.timeline 에 그리는 수준이었다.
  · 주말·공휴일을 세지 않아 실제 소요일수와 달력일이 어긋난다
  · 선행 공정이 밀렸을 때 후속 공정이 자동으로 밀리지 않는다
  · 어느 공정이 전체 공기를 결정하는지(주공정선) 알 수 없다
  → 공기 단축 협의나 지체상금 검토 시 근거로 쓸 수 없다.

이 모듈이 하는 일
  1. 영업일 달력 (주말 + 공휴일 제외, 토요일 근무 여부 선택)
  2. 선후행 관계 FS / SS / FF / SF + 지연(lag) 지원
  3. CPM 전진계산(ES/EF) · 후진계산(LS/LF) · 여유(TF/FF)
  4. 주공정선(Critical Path) 판별
  5. 순환 참조 탐지 (위상정렬 실패 시 경로 표시)
  6. 마일스톤(공기 0일) 처리
  7. 계획 진도율 S-Curve (금액 가중)

내부 좌표계
  모든 계산을 '영업일 서수(ordinal)' 공간에서 수행한 뒤 날짜로 환산한다.
  구간 표기는 종료 배타(exclusive end) 규약을 쓴다.
      start=3, duration=2  →  점유 서수 3,4 / finish=5
  이 규약은 마일스톤(duration=0, start==finish)을 자연스럽게 흡수한다.

의존: config, pandas
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

import pandas as pd

import config

log = config.get_logger("schedule")

# ═══════════════════════════════════════════════════════════
# 0. 스키마 및 상수
# ═══════════════════════════════════════════════════════════
SCHEDULE_SHEET = "공정계획"
HOLIDAY_SHEET = "공휴일"

SCHEDULE_COLUMNS = [
    "activity_id", "공종명", "구분", "공기", "선행공정",
    "고정시작일", "담당", "마일스톤", "비고",
]
HOLIDAY_COLUMNS = ["날짜", "명칭", "비고"]

REL_TYPES = ("FS", "SS", "FF", "SF")
DEFAULT_REL = "FS"

MAX_HORIZON_DAYS = 365 * 6      # 달력 생성 상한 (무한 루프 방지)

_EMPTY_TOKENS = ("", "-", "nan", "none", "null")
_TRUE_TOKENS = ("y", "yes", "true", "o", "ㅇ", "1", "마일스톤", "milestone")


def _norm_text(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in _EMPTY_TOKENS else text


def _is_true(value) -> bool:
    return _norm_text(value).lower() in _TRUE_TOKENS


def _to_date(value):
    """다양한 표기를 date 로 변환. 실패 시 None."""
    text = _norm_text(value)
    if not text:
        return None
    stamp = pd.to_datetime(text, errors="coerce")
    if pd.isna(stamp):
        return None
    return stamp.date()


# ═══════════════════════════════════════════════════════════
# 1. 공휴일 기본값 (2026년)
# ═══════════════════════════════════════════════════════════
# ⚠️ 주의: 아래 목록은 공개 자료를 취합한 것으로, 자료 간 상충이 있는 항목은
#          uncertain=True 로 표시했다. 계약·공기 산정에 쓰기 전 반드시
#          관공서 공휴일 규정 원문 또는 발주처 기준으로 확인할 것.
#          '공휴일' 시트를 만들면 이 기본값을 완전히 대체한다.
KR_HOLIDAYS_2026 = {
    "2026-01-01": ("신정", False),
    "2026-02-16": ("설날 연휴", False),
    "2026-02-17": ("설날", False),
    "2026-02-18": ("설날 연휴", False),
    "2026-03-01": ("삼일절", False),
    "2026-03-02": ("삼일절 대체공휴일", False),
    "2026-05-01": ("근로자의 날", True),      # 법정공휴일 격상 여부 자료 상충
    "2026-05-05": ("어린이날", False),
    "2026-05-24": ("부처님오신날", False),
    "2026-05-25": ("부처님오신날 대체공휴일", False),
    "2026-06-03": ("전국동시지방선거", True),  # 임시공휴일 성격
    "2026-06-06": ("현충일", False),
    "2026-07-17": ("제헌절", True),            # 공휴일 재지정 여부 자료 상충
    "2026-08-15": ("광복절", False),
    "2026-08-17": ("광복절 대체공휴일", True),  # 토요일 겹침 대체 적용 여부 상충
    "2026-09-24": ("추석 연휴", False),
    "2026-09-25": ("추석", False),
    "2026-09-26": ("추석 연휴", False),
    "2026-10-03": ("개천절", False),
    "2026-10-05": ("개천절 대체공휴일", True),  # 토요일 겹침 대체 적용 여부 상충
    "2026-10-09": ("한글날", False),
    "2026-12-25": ("성탄절", False),
}


def default_holidays(*, include_uncertain: bool = True) -> dict:
    """기본 공휴일 사전 {date: 명칭}.

    include_uncertain=False 로 두면 자료가 상충하는 날짜를 제외한다.
    (보수적으로 공기를 산정하고 싶을 때)
    """
    out = {}
    for iso, (name, uncertain) in KR_HOLIDAYS_2026.items():
        if uncertain and not include_uncertain:
            continue
        out[_dt.date.fromisoformat(iso)] = name
    return out


def uncertain_holidays() -> pd.DataFrame:
    """검증이 필요한 공휴일 목록. 화면 경고용."""
    rows = [{"날짜": iso, "명칭": name}
            for iso, (name, uncertain) in KR_HOLIDAYS_2026.items() if uncertain]
    return pd.DataFrame(rows, columns=["날짜", "명칭"])


def normalize_holiday_sheet(df: pd.DataFrame | None) -> dict:
    """'공휴일' 시트 → {date: 명칭}. 비어 있으면 빈 사전."""
    if df is None or df.empty or "날짜" not in df.columns:
        return {}
    out = {}
    for _, row in df.iterrows():
        day = _to_date(row.get("날짜"))
        if day is not None:
            out[day] = _norm_text(row.get("명칭")) or "공휴일"
    return out


# ═══════════════════════════════════════════════════════════
# 2. 영업일 달력
# ═══════════════════════════════════════════════════════════
class WorkCalendar:
    """영업일 달력. 날짜 ↔ 영업일 서수 변환을 담당한다."""

    def __init__(self, start: _dt.date, *, holidays: dict | None = None,
                 work_saturday: bool = False, work_sunday: bool = False,
                 horizon_days: int = MAX_HORIZON_DAYS):
        self.start = start
        self.holidays = dict(holidays or {})
        self.work_saturday = work_saturday
        self.work_sunday = work_sunday

        self._days: list = []
        self._index: dict = {}
        cursor = start
        limit = start + _dt.timedelta(days=horizon_days)
        while cursor <= limit:
            if self.is_workday(cursor):
                self._index[cursor] = len(self._days)
                self._days.append(cursor)
            cursor += _dt.timedelta(days=1)

        if not self._days:
            raise ValueError("영업일이 하나도 없습니다. 휴무일 설정을 확인하세요.")

    def is_workday(self, day: _dt.date) -> bool:
        weekday = day.weekday()          # 월0 … 토5 일6
        if weekday == 5 and not self.work_saturday:
            return False
        if weekday == 6 and not self.work_sunday:
            return False
        return day not in self.holidays

    def ordinal_of(self, day: _dt.date, *, forward: bool = True) -> int:
        """날짜 → 영업일 서수. 휴무일이면 다음(또는 이전) 영업일로 보정."""
        if day in self._index:
            return self._index[day]
        step = 1 if forward else -1
        cursor = day
        for _ in range(400):
            cursor += _dt.timedelta(days=step)
            if cursor in self._index:
                return self._index[cursor]
        raise ValueError(f"{day} 근처에서 영업일을 찾지 못했습니다.")

    def date_of(self, ordinal: int) -> _dt.date:
        """영업일 서수 → 날짜. 범위를 넘으면 마지막 영업일 기준으로 외삽."""
        if ordinal < 0:
            return self._days[0]
        if ordinal < len(self._days):
            return self._days[ordinal]
        overflow = ordinal - (len(self._days) - 1)
        return self._days[-1] + _dt.timedelta(days=overflow)

    def count_between(self, start: _dt.date, end: _dt.date) -> int:
        """[start, end] 구간의 영업일 수 (양끝 포함)."""
        if end < start:
            return 0
        return sum(1 for d in self._days if start <= d <= end)

    @property
    def workdays(self) -> list:
        return list(self._days)


# ═══════════════════════════════════════════════════════════
# 3. 활동 및 관계
# ═══════════════════════════════════════════════════════════
@dataclass
class Relation:
    pred: str
    rel_type: str = DEFAULT_REL
    lag: int = 0


@dataclass
class Activity:
    activity_id: str
    name: str
    duration: int = 1
    predecessors: list = field(default_factory=list)
    # ⚠️ 타입 어노테이션 필수: 어노테이션이 없으면 dataclass 가 일반 클래스 변수로
    #    취급해 __init__ 인자에서 누락된다.
    pinned_start: "_dt.date | None" = None
    gubun: str = ""
    owner: str = ""
    milestone: bool = False
    note: str = ""
    amount: float = 0.0

    # 계산 결과 (영업일 서수)
    es: int = 0
    finish: int = 0        # 종료 배타
    ls: int = 0
    lf: int = 0

    @property
    def total_float(self) -> int:
        return self.ls - self.es

    @property
    def is_critical(self) -> bool:
        return self.total_float == 0


@dataclass
class ScheduleIssue:
    level: str
    target: str
    message: str

    def as_row(self) -> dict:
        return {"수준": "오류" if self.level == "error" else "주의",
                "대상": self.target, "내용": self.message}


# ═══════════════════════════════════════════════════════════
# 4. 선행공정 표기 파서
# ═══════════════════════════════════════════════════════════
def parse_predecessors(text) -> tuple[list, list]:
    """선행공정 문자열을 Relation 목록으로 변환한다.

    지원 표기 (쉼표 구분)
        A            → A 종료 후 시작 (FS, lag 0)
        A FS+2       → A 종료 +2영업일 후 시작
        A SS         → A 와 동시 착수
        A FF-1       → A 종료 1일 전까지 종료
        A+3          → FS 생략형
    """
    raw = _norm_text(text)
    if not raw:
        return [], []

    relations: list = []
    errors: list = []
    for token in raw.replace(";", ",").split(","):
        piece = token.strip()
        if not piece:
            continue

        body = piece.replace(" ", "")
        lag = 0
        rel_type = DEFAULT_REL

        # 부호 위치 탐색 (선행 ID 내부의 하이픈과 구분하기 위해 뒤에서 찾는다)
        sign_pos = max(body.rfind("+"), body.rfind("-"))
        if sign_pos > 0:
            lag_text = body[sign_pos:]
            try:
                lag = int(lag_text)
                body = body[:sign_pos]
            except ValueError:
                errors.append(f"'{piece}' 의 지연값을 해석할 수 없음")
                continue

        upper = body.upper()
        for candidate in REL_TYPES:
            if upper.endswith(candidate):
                rel_type = candidate
                body = body[: len(body) - len(candidate)]
                break

        pred_id = body.strip().rstrip(":")
        if not pred_id:
            errors.append(f"'{piece}' 에 선행 공정 ID가 없음")
            continue
        relations.append(Relation(pred_id, rel_type, lag))

    return relations, errors


# ═══════════════════════════════════════════════════════════
# 5. 입력 정규화
# ═══════════════════════════════════════════════════════════
def empty_schedule_sheet() -> pd.DataFrame:
    return pd.DataFrame(columns=SCHEDULE_COLUMNS)


def normalize_schedule_sheet(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return empty_schedule_sheet()

    out = df.copy().reset_index(drop=True)
    for col in SCHEDULE_COLUMNS:
        if col not in out.columns:
            out[col] = ""

    for col in ("activity_id", "공종명", "구분", "선행공정", "담당", "비고"):
        out[col] = out[col].map(_norm_text)
    out["공기"] = config.to_number_series(out["공기"], default=1.0)

    # activity_id 가 없으면 공종명으로 대체
    out["activity_id"] = [
        aid or name for aid, name in zip(out["activity_id"], out["공종명"])
    ]
    out = out[out["activity_id"] != ""]
    return out[SCHEDULE_COLUMNS].reset_index(drop=True)


def build_activities(df_schedule: pd.DataFrame | None,
                     df_amounts: pd.DataFrame | None = None) -> tuple[dict, list]:
    """공정계획 시트 → {activity_id: Activity}. 금액은 진도율 가중에 사용."""
    normalized = normalize_schedule_sheet(df_schedule)
    issues: list = []
    activities: dict = {}

    amount_map: dict = {}
    if df_amounts is not None and not df_amounts.empty and "공종명" in df_amounts.columns:
        amounts = config.to_number_series(df_amounts.get("합계", 0))
        for name, value in zip(df_amounts["공종명"], amounts):
            key = _norm_text(name)
            if key:
                amount_map[key] = amount_map.get(key, 0.0) + float(value)

    for _, row in normalized.iterrows():
        aid = row["activity_id"]
        if aid in activities:
            issues.append(ScheduleIssue("error", aid, "activity_id 가 중복되었습니다."))
            continue

        milestone = _is_true(row["마일스톤"])
        duration = int(round(float(row["공기"])))
        if milestone:
            duration = 0
        elif duration < 1:
            issues.append(ScheduleIssue("warn", aid,
                                        f"공기가 {duration} 이어서 1일로 보정했습니다."))
            duration = 1

        relations, rel_errors = parse_predecessors(row["선행공정"])
        for message in rel_errors:
            issues.append(ScheduleIssue("error", aid, message))

        name = row["공종명"] or aid
        activities[aid] = Activity(
            activity_id=aid, name=name, duration=duration,
            predecessors=relations,
            pinned_start=_to_date(row["고정시작일"]),
            gubun=row["구분"], owner=row["담당"],
            milestone=milestone, note=row["비고"],
            amount=amount_map.get(name, 0.0),
        )

    # 존재하지 않는 선행 참조 제거
    for activity in activities.values():
        kept = []
        for relation in activity.predecessors:
            if relation.pred in activities:
                kept.append(relation)
            else:
                issues.append(ScheduleIssue(
                    "error", activity.activity_id,
                    f"선행 공정 '{relation.pred}' 이 목록에 없습니다."))
        activity.predecessors = kept

    return activities, issues


# ═══════════════════════════════════════════════════════════
# 6. 위상정렬 (순환 탐지)
# ═══════════════════════════════════════════════════════════
def topological_order(activities: dict) -> tuple[list, list]:
    """선행 → 후속 순서로 정렬. 순환이 있으면 경로를 오류로 보고한다."""
    indegree = {aid: 0 for aid in activities}
    successors = {aid: [] for aid in activities}

    for aid, activity in activities.items():
        for relation in activity.predecessors:
            successors[relation.pred].append(aid)
            indegree[aid] += 1

    queue = sorted([aid for aid, deg in indegree.items() if deg == 0])
    order: list = []
    while queue:
        current = queue.pop(0)
        order.append(current)
        for nxt in successors[current]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
        queue.sort()

    if len(order) == len(activities):
        return order, []

    stuck = sorted(set(activities) - set(order))
    cycle = _find_cycle(activities, stuck)
    message = " → ".join(cycle) if cycle else ", ".join(stuck)
    log.error("공정 순환 참조: %s", message)
    return order, [ScheduleIssue("error", stuck[0] if stuck else "-",
                                 f"순환 참조로 일정을 계산할 수 없습니다: {message}")]


def _find_cycle(activities: dict, candidates: list) -> list:
    """순환 경로 하나를 찾아 반환 (DFS)."""
    state: dict = {}
    stack: list = []

    def dfs(node: str):
        state[node] = 1
        stack.append(node)
        for relation in activities[node].predecessors:
            pred = relation.pred
            if pred not in activities:
                continue
            if state.get(pred) == 1:
                idx = stack.index(pred)
                return stack[idx:] + [pred]
            if state.get(pred, 0) == 0:
                found = dfs(pred)
                if found:
                    return found
        stack.pop()
        state[node] = 2
        return None

    for node in candidates:
        if state.get(node, 0) == 0:
            found = dfs(node)
            if found:
                return list(reversed(found))
    return []


# ═══════════════════════════════════════════════════════════
# 7. CPM 계산
# ═══════════════════════════════════════════════════════════
def _forward_pass(activities: dict, order: list, calendar: WorkCalendar) -> None:
    for aid in order:
        activity = activities[aid]
        earliest = 0

        if activity.pinned_start is not None:
            earliest = calendar.ordinal_of(activity.pinned_start)

        for relation in activity.predecessors:
            pred = activities[relation.pred]
            lag = relation.lag
            if relation.rel_type == "FS":
                candidate = pred.finish + lag
            elif relation.rel_type == "SS":
                candidate = pred.es + lag
            elif relation.rel_type == "FF":
                candidate = pred.finish + lag - activity.duration
            else:  # SF
                candidate = pred.es + lag - activity.duration
            earliest = max(earliest, candidate)

        activity.es = max(earliest, 0)
        activity.finish = activity.es + activity.duration


def _backward_pass(activities: dict, order: list, project_finish: int) -> None:
    successors: dict = {aid: [] for aid in activities}
    for aid, activity in activities.items():
        for relation in activity.predecessors:
            successors[relation.pred].append((aid, relation))

    for aid in reversed(order):
        activity = activities[aid]
        if not successors[aid]:
            activity.lf = project_finish
        else:
            latest = None
            for succ_id, relation in successors[aid]:
                succ = activities[succ_id]
                lag = relation.lag
                if relation.rel_type == "FS":
                    candidate = succ.ls - lag
                elif relation.rel_type == "SS":
                    candidate = succ.ls - lag + activity.duration
                elif relation.rel_type == "FF":
                    candidate = succ.lf - lag
                else:  # SF
                    candidate = succ.lf - lag + activity.duration
                latest = candidate if latest is None else min(latest, candidate)
            activity.lf = latest if latest is not None else project_finish
        activity.ls = activity.lf - activity.duration


def compute_schedule(df_schedule: pd.DataFrame | None,
                     *, project_start=None, holidays: dict | None = None,
                     work_saturday: bool = False, work_sunday: bool = False,
                     df_amounts: pd.DataFrame | None = None,
                     deadline=None) -> dict:
    """CPM 일정을 계산한다.

    반환 dict
      "table"    : 활동별 일정 DataFrame
      "issues"   : 경고 목록
      "calendar" : WorkCalendar
      "summary"  : 공기·주공정선 요약
    """
    activities, issues = build_activities(df_schedule, df_amounts)
    if not activities:
        return {"table": pd.DataFrame(columns=[
                    "ID", "공종명", "구분", "담당", "공기",
                    "시작일", "종료일", "여유일", "주공정", "선행공정", "비고"]),
                "issues": issues, "calendar": None,
                "summary": {"활동수": 0}}

    start = _to_date(project_start)
    if start is None:
        pinned = [a.pinned_start for a in activities.values() if a.pinned_start]
        start = min(pinned) if pinned else _dt.date.today()

    calendar = WorkCalendar(start, holidays=holidays if holidays is not None
                            else default_holidays(),
                            work_saturday=work_saturday, work_sunday=work_sunday)

    order, cycle_issues = topological_order(activities)
    issues.extend(cycle_issues)
    if cycle_issues:
        # 순환이 있으면 계산을 포기하되, 입력 내용은 그대로 표로 돌려준다
        rows = [{"ID": a.activity_id, "공종명": a.name, "구분": a.gubun,
                 "담당": a.owner, "공기": a.duration, "시작일": None, "종료일": None,
                 "여유일": None, "주공정": "", "선행공정": ", ".join(
                     f"{r.pred}{r.rel_type}{r.lag:+d}" if r.lag else f"{r.pred}{r.rel_type}"
                     for r in a.predecessors),
                 "비고": a.note} for a in activities.values()]
        return {"table": pd.DataFrame(rows), "issues": issues,
                "calendar": calendar, "summary": {"활동수": len(activities),
                                                  "상태": "순환 참조로 계산 중단"}}

    _forward_pass(activities, order, calendar)
    project_finish = max(a.finish for a in activities.values())

    if deadline is not None:
        deadline_date = _to_date(deadline)
        if deadline_date is not None:
            target = calendar.ordinal_of(deadline_date, forward=False) + 1
            if target < project_finish:
                issues.append(ScheduleIssue(
                    "warn", "전체 공정",
                    f"목표 준공일({deadline_date})보다 "
                    f"{project_finish - target}영업일 초과합니다."))
            project_finish = max(project_finish, target)

    _backward_pass(activities, order, project_finish)

    rows: list = []
    for aid in order:
        activity = activities[aid]
        start_date = calendar.date_of(activity.es)
        if activity.duration == 0:
            end_date = start_date
        else:
            end_date = calendar.date_of(activity.finish - 1)
        rows.append({
            "ID": aid,
            "공종명": activity.name,
            "구분": activity.gubun,
            "담당": activity.owner,
            "공기": activity.duration,
            "시작일": pd.Timestamp(start_date),
            "종료일": pd.Timestamp(end_date),
            "여유일": activity.total_float,
            "주공정": "★" if activity.is_critical else "",
            "선행공정": ", ".join(
                f"{r.pred}{r.rel_type}{r.lag:+d}" if r.lag else f"{r.pred}{r.rel_type}"
                for r in activity.predecessors),
            "마일스톤": "◆" if activity.milestone else "",
            "금액": int(round(activity.amount)),
            "비고": activity.note,
        })

    table = pd.DataFrame(rows)
    critical = [r["ID"] for r in rows if r["주공정"] == "★"]
    finish_date = calendar.date_of(project_finish - 1)

    summary = {
        "활동수": len(activities),
        "착수일": calendar.date_of(min(a.es for a in activities.values())),
        "준공일": finish_date,
        "총공기(영업일)": project_finish,
        "총공기(달력일)": (finish_date - start).days + 1,
        "주공정활동": len(critical),
        "주공정선": " → ".join(critical),
    }
    log.info("일정 계산 완료: 활동 %d개 / 공기 %d영업일 / 주공정 %d개",
             len(activities), project_finish, len(critical))
    return {"table": table, "issues": issues, "calendar": calendar, "summary": summary}


# ═══════════════════════════════════════════════════════════
# 8. 진도율 S-Curve
# ═══════════════════════════════════════════════════════════
def build_s_curve(table: pd.DataFrame | None, calendar: WorkCalendar | None,
                  *, freq: str = "W") -> pd.DataFrame:
    """금액 가중 계획 진도율. 공정 기간에 금액을 균등 배분한다.

    freq: "W"(주별) | "M"(월별) | "D"(일별)
    """
    if table is None or table.empty or calendar is None:
        return pd.DataFrame(columns=["기준일", "계획금액", "누적금액", "누적진도율(%)"])
    if "금액" not in table.columns:
        return pd.DataFrame(columns=["기준일", "계획금액", "누적금액", "누적진도율(%)"])

    work = table.dropna(subset=["시작일", "종료일"]).copy()
    if work.empty:
        return pd.DataFrame(columns=["기준일", "계획금액", "누적금액", "누적진도율(%)"])

    work["금액"] = config.to_number_series(work["금액"])
    daily: dict = {}

    for _, row in work.iterrows():
        amount = float(row["금액"])
        if amount <= 0:
            continue
        start = row["시작일"].date()
        end = row["종료일"].date()
        days = [d for d in calendar.workdays if start <= d <= end]
        if not days:
            days = [start]
        share = amount / len(days)
        for day in days:
            daily[day] = daily.get(day, 0.0) + share

    if not daily:
        return pd.DataFrame(columns=["기준일", "계획금액", "누적금액", "누적진도율(%)"])

    series = pd.Series(daily).sort_index()
    series.index = pd.to_datetime(series.index)
    grouped = series if freq == "D" else series.resample(freq).sum()

    total = float(grouped.sum())
    cumulative = grouped.cumsum()
    return pd.DataFrame({
        "기준일": grouped.index,
        "계획금액": grouped.round(0).astype("int64").values,
        "누적금액": cumulative.round(0).astype("int64").values,
        "누적진도율(%)": (cumulative / total * 100).round(2).values if total else 0,
    })


def critical_path_table(table: pd.DataFrame | None) -> pd.DataFrame:
    """주공정선만 추린 표. 공기 단축 협의 자료용."""
    if table is None or table.empty or "주공정" not in table.columns:
        return pd.DataFrame()
    return table[table["주공정"] == "★"].reset_index(drop=True)


def validate(issues: list) -> pd.DataFrame:
    seen: set = set()
    rows: list = []
    for issue in issues or []:
        signature = (issue.level, issue.target, issue.message)
        if signature in seen:
            continue
        seen.add(signature)
        rows.append(issue.as_row())
    return pd.DataFrame(rows, columns=["수준", "대상", "내용"])


def sample_schedule_sheet() -> pd.DataFrame:
    """작성 예시 (양식 다운로드용)."""
    return pd.DataFrame([
        {"activity_id": "A10", "공종명": "가설 및 준비", "구분": "가설", "공기": 3,
         "선행공정": "", "고정시작일": "2026-08-03", "담당": "시설팀",
         "마일스톤": "", "비고": "착수"},
        {"activity_id": "A20", "공종명": "기존 배관 철거", "구분": "철거", "공기": 5,
         "선행공정": "A10", "고정시작일": "", "담당": "협력사",
         "마일스톤": "", "비고": ""},
        {"activity_id": "A30", "공종명": "소화배관 설치", "구분": "소방", "공기": 12,
         "선행공정": "A20FS+1", "고정시작일": "", "담당": "협력사",
         "마일스톤": "", "비고": "선행 종료 후 1일 여유"},
        {"activity_id": "A40", "공종명": "도장", "구분": "마감", "공기": 4,
         "선행공정": "A30SS+8", "고정시작일": "", "담당": "협력사",
         "마일스톤": "", "비고": "배관 착수 8일 후 동시 진행"},
        {"activity_id": "A50", "공종명": "수압시험", "구분": "소방", "공기": 2,
         "선행공정": "A30, A40", "고정시작일": "", "담당": "시설팀",
         "마일스톤": "", "비고": ""},
        {"activity_id": "M99", "공종명": "준공 검사", "구분": "검사", "공기": 0,
         "선행공정": "A50", "고정시작일": "", "담당": "시설팀",
         "마일스톤": "Y", "비고": "마일스톤"},
    ], columns=SCHEDULE_COLUMNS)
