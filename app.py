# -*- coding: utf-8 -*-
"""
app.py — 포타송 설계서 작성 (Ver.260730)
─────────────────────────────────────────────────────────────
탭 구성
  대시보드 / 설계·원가계산 / 일위대가 / 수량산출 / 공정표 / 설계변경 / 기초데이터

설계 원칙
  · 부가 시트(세트구성·수량산출·공정계획·변경사유)가 비어 있으면 안내만 표시하고
    기존 동작을 그대로 유지한다. 새 기능이 기존 작업을 막지 않는다.
  · 모든 쓰기는 db_manager / db_extra 를 거치며 원자적으로 처리된다.
  · 오류는 삼키지 않고 화면에 사유를 표시한다.
  · 편집 권한(auth.py)은 선택 사항이다. 파일이 없으면 전원 편집 가능으로 동작한다.
"""

import io
from datetime import date, datetime

import pandas as pd
import plotly.express as px
import streamlit as st

import config
import db_manager as db
import db_extra as dbx
import logic_boq as boq
import logic_calculator as calc
import logic_change as chg
import logic_schedule as sch
import logic_takeoff as tko
import state_manager as state
import ui_components as ui

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
log = config.get_logger("app")

# auth.py가 없으면 기존처럼 누구나 편집할 수 있다.
# 단, auth.py가 존재하지만 정상 동작하지 않으면 안전을 위해 앱을 중지한다.
try:
    import auth
    _AUTH = True
    _AUTH_ERROR = None
except ModuleNotFoundError as exc:
    if exc.name != "auth":
        raise
    auth = None
    _AUTH = False
    _AUTH_ERROR = None
except Exception as exc:
    auth = None
    _AUTH = True
    _AUTH_ERROR = exc


def can_edit() -> bool:
    """편집 권한 오류는 허용하지 않고 잠금 상태로 처리한다."""
    if not _AUTH:
        return True
    try:
        return auth.can_edit()
    except Exception:
        log.exception("권한 확인 실패 — 편집 잠금으로 처리")
        return False


def require_edit(action: str) -> bool:
    if can_edit():
        return True
    st.warning(f"{action}은 편집 권한이 필요합니다. 사이드바에서 잠금을 해제하세요.")
    return False


def audit(action: str, detail: str = "") -> None:
    if _AUTH:
        try:
            auth.audit(action, detail)
        except Exception:
            log.exception("감사 로그 기록 실패")


# ═══════════════════════════════════════════════════════════
# 1. 페이지 설정 및 초기화
# ═══════════════════════════════════════════════════════════
st.set_page_config(page_title=config.PAGE_TITLE, page_icon=config.PAGE_ICON,
                   layout="wide")
st.title(config.APP_TITLE)
ui.apply_theme()

if _AUTH_ERROR:
    st.error("편집 권한 모듈을 불러오지 못했습니다. 보안을 위해 앱을 시작하지 않습니다.")
    st.caption(f"상세 사유: {type(_AUTH_ERROR).__name__} - {_AUTH_ERROR}")
    st.stop()

init_result = db.init_db()
if not init_result:
    st.error("Google Sheets에 연결할 수 없습니다.")
    st.caption(f"상세 사유: {init_result.message}")
    st.info("관리자에게 다음을 확인해 달라고 요청하세요: "
            "Streamlit secrets의 GOOGLE_CREDENTIALS·SPREADSHEET_URL, "
            "서비스 계정의 스프레드시트 편집 권한, Google Sheets API 활성화 여부.")
    st.stop()

state.bootstrap()
state.session_id()
extra_init_result = dbx.ensure_sheets()
if not extra_init_result:
    st.warning(f"부가 데이터 시트 준비 실패: {extra_init_result.message}")


def show_errors() -> None:
    """읽기 단계에서 발생한 오류를 사용자에게 알린다."""
    messages = list(db.consume_load_errors()) + list(dbx.consume_load_errors())
    for message in messages:
        st.warning(f"데이터 조회 경고: {message}")


@st.cache_data(ttl=300, show_spinner=False)
def _rates_signature(values: tuple) -> tuple:
    """제비율 변경 감지용 (캐시 키 안정화)."""
    return values


# ═══════════════════════════════════════════════════════════
# 2. 사이드바
# ═══════════════════════════════════════════════════════════
st.sidebar.subheader("설계서 작성")

new_project = st.sidebar.text_input("새 프로젝트명 입력",
                                    placeholder="예: 포스코타워-송도 환경개선")
if st.sidebar.button("새 프로젝트 생성", use_container_width=True):
    ok, message = state.create_project(new_project)
    if ok:
        st.rerun()
    else:
        st.sidebar.warning(message)

names = state.project_names()
selected_project = st.sidebar.selectbox("현재 작업 중인 현장 선택", names,
                                        index=names.index(state.current_project()))
if selected_project != state.current_project():
    state.switch_project(selected_project)
    st.rerun()

if st.sidebar.button("현재 프로젝트 삭제", use_container_width=True):
    if require_edit("현재 프로젝트 삭제"):
        ui.delete_confirmation(state.current_project())

st.sidebar.divider()
st.sidebar.subheader("문서 작성 정보")
st.sidebar.text_input("작성자 / 부서",
                      value=st.session_state.get("writer_name", "포스코타워-송도 (이름/직급)"),
                      key="writer_name",
                      help="견적서 엑셀 상단 제목 블록에 표기됩니다.")

st.sidebar.divider()
st.sidebar.subheader("클라우드 DB 보관소")

if st.sidebar.button("클라우드 목록 갱신/조회", use_container_width=True):
    with st.spinner("구글 시트에서 불러오는 중..."):
        db.get_cloud_projects_list.clear()
        st.session_state.cloud_project_list = db.get_cloud_projects_list()

selected_cloud = None
if st.session_state.cloud_project_list:
    options = {f"{p['name']} ({p['date']})": p["name"]
               for p in st.session_state.cloud_project_list}
    selected_cloud = options[st.sidebar.selectbox("불러올 프로젝트 선택",
                                                  list(options.keys()))]

    if st.sidebar.button("선택 프로젝트 불러오기", use_container_width=True):
        with st.spinner(f"'{selected_cloud}' 데이터를 가져오는 중..."):
            result = db.load_project_from_cloud(selected_cloud)
        if result:
            loaded_df, version = result.data
            state.replace_project(selected_cloud, loaded_df, version=version)
            st.rerun()
        else:
            st.sidebar.error(result.message)

    if st.sidebar.button("클라우드에서 삭제", use_container_width=True):
        if require_edit("클라우드 삭제"):
            ui.delete_cloud_confirmation(selected_cloud)

if st.sidebar.button("현재 프로젝트 클라우드 저장", use_container_width=True,
                     type="primary"):
    if require_edit("클라우드 저장"):
        project = state.current_project()
        with st.spinner("기록 중..."):
            result = db.save_project_to_cloud(
                project, state.get_estimate(),
                expected_version=state.get_version(project))
        if result:
            state.set_version(project, result.data)
            audit("프로젝트 저장", project)
            st.sidebar.success("클라우드 저장 완료!")
        elif result.code == "conflict":
            ui.overwrite_conflict_dialog(project, str(result.data))
        else:
            st.sidebar.error(result.message)

if _AUTH:
    try:
        auth.render_sidebar_login()
    except Exception:
        log.exception("권한 위젯 표시 실패")

show_errors()

# ═══════════════════════════════════════════════════════════
# 3. 공통 데이터 로드 (탭 간 공유)
# ═══════════════════════════════════════════════════════════
master_df = db.get_all_master_items_combined()
price_index = boq.build_price_index(master_df)
set_index = boq.build_set_index(dbx.get_set_sheet())
resolutions = boq.resolve_all_sets(set_index, price_index) if set_index else {}

tabs = st.tabs(["대시보드", "설계 및 원가계산", "일위대가", "수량산출",
                "공정표", "설계변경", "기초 데이터 관리"])
tab_dash, tab_est, tab_boq, tab_tko, tab_sch, tab_chg, tab_db = tabs

# ═══════════════════════════════════════════════════════════
# TAB 1: 대시보드
# ═══════════════════════════════════════════════════════════
with tab_dash:
    st.subheader(f"{state.current_project()} 종합 대시보드")
    df_dash = state.get_estimate()

    if df_dash.empty:
        st.info("추가된 내역이 없습니다. '설계 및 원가계산' 탭에서 품목을 추가하세요.")
    else:
        df_dash["비목"] = config.cost_group_series(df_dash).fillna("미분류")
        totals = df_dash.groupby("비목")["합계"].sum()

        columns = st.columns(4)
        columns[0].metric("총 직접공사비", f"{df_dash['합계'].sum():,.0f} 원")
        for i, group in enumerate(config.COST_GROUPS, start=1):
            columns[i].metric(f"{group}비 총액", f"{totals.get(group, 0):,.0f} 원")

        if "미분류" in totals.index:
            unknown_rows = int((df_dash["비목"] == "미분류").sum())
            st.warning(
                f"구분을 인식할 수 없는 내역 {unknown_rows}건"
                f"(합계 {totals['미분류']:,.0f}원)이 원가계산에서 제외됩니다. "
                f"'구분'을 {', '.join(config.GUBUN_OPTIONS)} 중 하나로 수정하세요.")

        st.divider()
        left, right = st.columns(2)
        with left:
            st.markdown("**비목별 금액 비중**")
            st.plotly_chart(
                px.pie(df_dash, values="합계", names="비목", hole=0.4,
                       color_discrete_sequence=px.colors.qualitative.Pastel),
                use_container_width=True)
        with right:
            st.markdown("**주요 공종별 투입 금액**")
            st.plotly_chart(
                px.bar(df_dash, x="공종명", y="합계", color="비목", text_auto=".2s",
                       color_discrete_sequence=px.colors.qualitative.Pastel),
                use_container_width=True)

# ═══════════════════════════════════════════════════════════
# TAB 2: 설계 및 원가계산
# ═══════════════════════════════════════════════════════════
with tab_est:
    st.subheader("1. 품목 단가 추가")
    add_columns = st.columns(len(config.MASTER_SHEET_NAMES))
    for column, sheet_name in zip(add_columns, config.MASTER_SHEET_NAMES):
        ui.render_add_item_column(column, sheet_name, editable=can_edit())
    show_errors()

    st.divider()
    st.subheader(f"2. 세부 내역서 (을지) - {state.current_project()}")

    display_df = state.get_estimate()
    display_df.index = range(1, len(display_df) + 1)
    display_df.index.name = "NO."

    edited_df = st.data_editor(
        display_df,
        column_order=config.ESTIMATE_COLUMNS,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=False,
        key="estimate_editor",
        disabled=not can_edit(),
        column_config={
            "구분": st.column_config.SelectboxColumn(
                "구분", options=config.GUBUN_OPTIONS, required=True),
            "공종명": st.column_config.TextColumn("공종명"),
            "규격": st.column_config.TextColumn("규격"),
            "단위": st.column_config.SelectboxColumn("단위", options=config.UNIT_OPTIONS),
            "단가": st.column_config.NumberColumn("단가(원)", format="%d", min_value=0),
            "수량": st.column_config.NumberColumn("수량", format="%.2f", step=0.1,
                                                min_value=0.0),
            "합계": st.column_config.NumberColumn("합계(원)", format="%d", disabled=True),
            "시작일": st.column_config.DateColumn("시작일", format="YYYY-MM-DD"),
            "종료일": st.column_config.DateColumn("종료일", format="YYYY-MM-DD"),
        })

    if state.has_changed(edited_df):
        state.set_estimate(edited_df)
        st.rerun()

    st.info("항목 삭제: 표 왼쪽 NO. 칸을 클릭해 행을 선택한 후 키보드 Delete 키 "
            "또는 우측 상단 휴지통 아이콘을 누르세요.")

    _, delete_column = st.columns([7, 3])
    with delete_column:
        if st.button("전체 내역 비우기", type="primary", use_container_width=True,
                     key="clear_all") and require_edit("전체 내역 삭제"):
            ui.delete_all_confirmation()

    st.divider()
    st.subheader("3. 조달청 기준 원가계산서 (갑지)")
    st.caption("제비율과 산식은 적용 기준·연도에 따라 달라집니다. "
               "계약·입찰 제출 전 최신 조달청 기준으로 반드시 재검토하세요.")

    with st.expander("제비율(%) 설정", expanded=True):
        rate_labels = [
            ("indirect_labor", "간접노무비율(%)"), ("sanjae", "산재보험료율(%)"),
            ("goyong", "고용보험료율(%)"), ("health", "국민건강보험료율(%)"),
            ("elderly", "노인장기요양보험료율(%)"), ("pension", "국민연금보험료율(%)"),
            ("retire", "퇴직공제부금비율(%)"), ("safety", "산업안전보건비율(%)"),
            ("env", "환경보전비율(%)"), ("etc_exp", "기타경비율(%)"),
            ("general_admin", "일반관리비율(%)"), ("profit", "이윤율(%)"),
            ("tax", "부가가치세율(%)"),
        ]
        rate_columns = st.columns(4)
        rates = {}
        for i, (key, label) in enumerate(rate_labels):
            with rate_columns[i % 4]:
                rates[key] = st.number_input(label, value=config.DEFAULT_RATES[key],
                                             step=0.1, key=f"rate_{key}")

    estimate_df = state.get_estimate()

    # ── 일위대가 전개 ─────────────────────────────────────
    if set_index:
        left, right = st.columns([1, 3])
        with left:
            explode = st.checkbox("세트 전개", value=True, key="chk_explode",
                                  help="세트를 구성품(자재·노무·장비)으로 펼쳐 "
                                       "원가를 정확히 계산합니다.")
        with right:
            st.caption("전개를 끄면 세트의 노무비가 자재비로 계상되어 "
                       "간접노무비·보험료가 과소 산출됩니다.")

        calc_df, boq_issues = boq.expand_estimate(
            estimate_df, set_index, price_index,
            mode="explode" if explode else "price")

        boq_report = boq.validate(resolutions, boq_issues)
        boq_errors = boq_report[boq_report["수준"] == "오류"]
        if not boq_errors.empty:
            st.error(f"일위대가 오류 {len(boq_errors)}건 — 단가가 누락된 구성품이 있습니다.")
            st.dataframe(boq_errors, use_container_width=True, hide_index=True)
        boq_warns = boq_report[boq_report["수준"] == "주의"]
        if not boq_warns.empty:
            with st.expander(f"일위대가 주의 {len(boq_warns)}건"):
                st.dataframe(boq_warns, use_container_width=True, hide_index=True)
    else:
        calc_df = estimate_df
        st.caption(f"'{boq.SET_SHEET}' 시트에 구성을 등록하면 일위대가 자동 산출을 쓸 수 있습니다. "
                   "('일위대가' 탭 참고)")

    # ── 구분 미인식 경고 ──────────────────────────────────
    audit_result = calc.audit_categories(calc_df)
    if audit_result["unknown_rows"]:
        detail = ", ".join(f"'{k}' {v:,}원" for k, v in audit_result["unknown"].items())
        st.error(f"구분 미인식 {audit_result['unknown_rows']}건이 원가계산에서 "
                 f"제외되었습니다 ({detail}). 내역서에서 '구분'을 수정하세요.")

    summary_df = pd.DataFrame(calc.calculate_cost_summary(calc_df, rates))
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

    # ── 산출물 다운로드 ──────────────────────────────────
    if not estimate_df.empty:
        st.markdown("##### 4. 견적서 산출물 다운로드")
        left, right = st.columns([1, 3])
        with left:
            include_rates = st.checkbox("제비율 시트 포함", value=True, key="chk_rates")
        with right:
            st.caption("갑지(원가계산서)·을지(세부내역서) 2개 시트로 구성되며 "
                       "A4 인쇄 서식이 적용되어 있습니다.")

        try:
            with st.spinner("엑셀 생성 중..."):
                excel_bytes = calc.generate_excel_bytes(
                    estimate_df=calc_df[config.ESTIMATE_COLUMNS]
                    if set(config.ESTIMATE_COLUMNS).issubset(calc_df.columns) else calc_df,
                    summary_df=summary_df,
                    project_name=state.current_project(),
                    writer_name=st.session_state.get("writer_name", "시설관리팀"),
                    rates=rates if include_rates else None)
            st.download_button(
                "견적서 엑셀 다운로드", data=excel_bytes,
                file_name=f"{state.current_project()}_원가계산서_{datetime.now():%Y%m%d}.xlsx",
                mime=XLSX_MIME, type="primary", use_container_width=True,
                key="download_estimate")
        except Exception as exc:
            log.exception("엑셀 생성 실패")
            st.error(f"엑셀 생성 중 오류가 발생했습니다: {type(exc).__name__} - {exc}")
    else:
        st.info("세부 내역서에 항목을 1건 이상 입력하면 견적서 엑셀을 다운로드할 수 있습니다.")

# ═══════════════════════════════════════════════════════════
# TAB 3: 일위대가
# ═══════════════════════════════════════════════════════════
with tab_boq:
    st.subheader("일위대가(세트) 관리")
    st.caption("세트는 자재+노무+장비가 섞인 복합 단가입니다. 구성품을 등록하면 "
               "단가가 자동 산출되고, 원가계산 시 비목별로 정확히 반영됩니다.")

    set_df = dbx.get_set_sheet()

    if resolutions:
        st.markdown("##### 세트 요약")
        st.dataframe(boq.summarize(resolutions), use_container_width=True,
                     hide_index=True)

        report = boq.validate(resolutions)
        errors = report[report["수준"] == "오류"]
        if not errors.empty:
            st.error(f"확인 필요 {len(errors)}건")
            st.dataframe(errors, use_container_width=True, hide_index=True)

        picked = st.multiselect("일위대가표에 포함할 세트", list(resolutions.keys()),
                                default=list(resolutions.keys())[:10])
        if picked:
            st.markdown("##### 일위대가표")
            ilwi_df = boq.build_ilwidaega_table(resolutions, only=picked)
            st.dataframe(ilwi_df, use_container_width=True, hide_index=True)
    else:
        st.info(f"등록된 세트가 없습니다. 아래 표에 구성품을 입력하고 저장하세요.")

    st.divider()
    st.markdown("##### 세트구성 편집")
    st.caption("소요량은 세트 1단위당 필요량입니다. 구분이 '세트'인 행은 "
               "품명에 하위 세트명을 적으면 중첩됩니다.")

    edited_sets = st.data_editor(
        set_df if not set_df.empty else boq.sample_set_sheet(),
        num_rows="dynamic", use_container_width=True, key="set_editor",
        column_config={
            "구분": st.column_config.SelectboxColumn(
                "구분", options=config.GUBUN_OPTIONS, required=True),
            "소요량": st.column_config.NumberColumn("소요량", format="%.4f",
                                                 min_value=0.0),
            "할증률": st.column_config.NumberColumn("할증률(%)", format="%.2f",
                                                 min_value=0.0),
            "seq": st.column_config.NumberColumn("순번", format="%d"),
        })

    if st.button("세트구성 저장", type="primary", use_container_width=True,
                 key="save_sets"):
        if require_edit("세트구성 저장"):
            with st.spinner("저장 중..."):
                result = dbx.save(boq.SET_SHEET, edited_sets)
            if result:
                audit("세트구성 저장", f"{len(edited_sets)}행")
                st.success(result.message)
                st.rerun()
            else:
                st.error(result.message)

# ═══════════════════════════════════════════════════════════
# TAB 4: 수량산출
# ═══════════════════════════════════════════════════════════
with tab_tko:
    st.subheader("수량산출서")
    st.caption("산출식 또는 치수(가로·세로·높이·개소) 중 하나만 채우면 됩니다. "
               "개구부 등은 '공제' 열에 표시하면 음수로 처리됩니다.")

    takeoff_sheet = dbx.get_takeoff_sheet()
    computed, takeoff_issues = tko.compute_takeoff(takeoff_sheet)
    takeoff_report = tko.validate(takeoff_issues)

    errors = takeoff_report[takeoff_report["수준"] == "오류"]
    if not errors.empty:
        st.error(f"산출식 오류 {len(errors)}건 — 해당 행은 수량 0으로 처리됩니다.")
        st.dataframe(errors, use_container_width=True, hide_index=True)
    warns = takeoff_report[takeoff_report["수준"] == "주의"]
    if not warns.empty:
        with st.expander(f"주의 {len(warns)}건"):
            st.dataframe(warns, use_container_width=True, hide_index=True)

    if not computed.empty:
        left, right = st.columns(2)
        with left:
            st.markdown("##### 공종별 집계")
            st.dataframe(tko.aggregate(computed), use_container_width=True,
                         hide_index=True)
        with right:
            st.markdown("##### 층별/구역별 물량")
            st.dataframe(tko.pivot_by_location(computed), use_container_width=True,
                         hide_index=True)

        st.markdown("##### 수량산출서")
        takeoff_report_df = tko.build_takeoff_report(computed)
        st.dataframe(takeoff_report_df, use_container_width=True, hide_index=True)

        if st.button("산출 수량을 내역서에 반영", type="primary",
                     use_container_width=True, key="apply_takeoff"):
            if require_edit("산출 수량 반영"):
                applied, apply_issues = tko.apply_to_estimate(state.get_estimate(), computed)
                matched = int((applied["수량출처"] == "수량산출서").sum())
                state.set_estimate(applied.drop(columns=["수량출처"], errors="ignore"))
                st.success(f"{matched}개 항목의 수량을 산출서 값으로 반영했습니다.")
                unused = tko.validate(apply_issues)
                if not unused.empty:
                    st.info("아래 항목은 확인이 필요합니다.")
                    st.dataframe(unused, use_container_width=True, hide_index=True)
    else:
        st.info("산출 내역이 없습니다. 아래 표에 입력하고 저장하세요.")

    st.divider()
    st.markdown("##### 산출 내역 편집")
    edited_takeoff = st.data_editor(
        takeoff_sheet if not takeoff_sheet.empty else tko.sample_takeoff_sheet(),
        num_rows="dynamic", use_container_width=True, key="takeoff_editor",
        column_config={
            "산출식": st.column_config.TextColumn(
                "산출식", help="예: 12.5 × 8.4  또는  (15+8)*2*2.7"),
            "공제": st.column_config.SelectboxColumn("공제", options=["", "공제"]),
            "단위": st.column_config.SelectboxColumn("단위", options=config.UNIT_OPTIONS),
        })

    if st.button("수량산출 저장", type="primary", use_container_width=True,
                 key="save_takeoff"):
        if require_edit("수량산출 저장"):
            with st.spinner("저장 중..."):
                result = dbx.save(tko.TAKEOFF_SHEET, edited_takeoff)
            if result:
                audit("수량산출 저장", f"{len(edited_takeoff)}행")
                st.success(result.message)
                st.rerun()
            else:
                st.error(result.message)

# ═══════════════════════════════════════════════════════════
# TAB 5: 공정표
# ═══════════════════════════════════════════════════════════
with tab_sch:
    st.subheader("공정표 (CPM)")
    st.caption("공기는 영업일 기준입니다. 주말과 공휴일은 자동으로 제외됩니다.")

    option_columns = st.columns(4)
    with option_columns[0]:
        project_start = st.date_input("착수일", value=date.today(), key="sch_start")
    with option_columns[1]:
        work_saturday = st.checkbox("토요일 근무", value=False, key="sch_sat")
    with option_columns[2]:
        use_deadline = st.checkbox("목표 준공일 사용", value=False, key="sch_use_dl")
    with option_columns[3]:
        deadline = st.date_input("목표 준공일", value=date.today(),
                                 key="sch_dl", disabled=not use_deadline)

    holiday_sheet = sch.normalize_holiday_sheet(dbx.get_holiday_sheet())
    holidays = holiday_sheet or sch.default_holidays()

    if not holiday_sheet:
        with st.expander("공휴일 기본값 사용 중 — 검증이 필요한 항목이 있습니다"):
            st.caption("아래 날짜는 공개 자료 간 내용이 상충합니다. 공기 산정은 "
                       "지체상금과 직결되므로, '공휴일' 시트에 발주처 확정 기준을 "
                       "입력해 대체하시기 바랍니다.")
            st.dataframe(sch.uncertain_holidays(), use_container_width=True,
                         hide_index=True)

    schedule_sheet = dbx.get_schedule_sheet()
    schedule_result = sch.compute_schedule(
        schedule_sheet, project_start=project_start, holidays=holidays,
        work_saturday=work_saturday, df_amounts=state.get_estimate(),
        deadline=deadline if use_deadline else None)

    schedule_report = sch.validate(schedule_result["issues"])
    errors = schedule_report[schedule_report["수준"] == "오류"]
    if not errors.empty:
        st.error(f"일정 오류 {len(errors)}건")
        st.dataframe(errors, use_container_width=True, hide_index=True)
    warns = schedule_report[schedule_report["수준"] == "주의"]
    if not warns.empty:
        with st.expander(f"주의 {len(warns)}건"):
            st.dataframe(warns, use_container_width=True, hide_index=True)

    summary = schedule_result["summary"]
    schedule_table = schedule_result["table"]

    if summary.get("활동수"):
        metrics = st.columns(4)
        metrics[0].metric("총 공기(영업일)", f"{summary.get('총공기(영업일)', 0)}일")
        metrics[1].metric("총 공기(달력일)", f"{summary.get('총공기(달력일)', 0)}일")
        metrics[2].metric("준공 예정", str(summary.get("준공일", "-")))
        metrics[3].metric("주공정 활동", f"{summary.get('주공정활동', 0)}개")
        if summary.get("주공정선"):
            st.caption(f"주공정선: {summary['주공정선']}")

    valid_schedule = (schedule_table.dropna(subset=["시작일", "종료일"])
                      if not schedule_table.empty else schedule_table)

    if not valid_schedule.empty:
        figure = px.timeline(valid_schedule, x_start="시작일", x_end="종료일",
                             y="공종명", color="주공정",
                             color_discrete_map={"★": "#C00000", "": "#8EA9C1"},
                             hover_data=["ID", "공기", "여유일", "선행공정"])
        figure.update_yaxes(autorange="reversed")
        st.plotly_chart(figure, use_container_width=True)

        st.markdown("##### 공정 일람")
        st.dataframe(schedule_table, use_container_width=True, hide_index=True)

        critical = sch.critical_path_table(schedule_table)
        if not critical.empty:
            with st.expander(f"주공정선 {len(critical)}개 (공기 단축 협의 자료)"):
                st.dataframe(critical, use_container_width=True, hide_index=True)

        curve = sch.build_s_curve(schedule_table, schedule_result["calendar"], freq="W")
        if not curve.empty:
            st.markdown("##### 계획 진도율 (S-Curve)")
            st.plotly_chart(px.line(curve, x="기준일", y="누적진도율(%)", markers=True),
                            use_container_width=True)
            with st.expander("주별 계획 금액"):
                st.dataframe(curve, use_container_width=True, hide_index=True)
    else:
        st.info("공정 계획이 없습니다. 아래 표에 입력하고 저장하세요.")

    st.divider()
    st.markdown("##### 공정계획 편집")
    st.caption("선행공정 표기: A10(종료 후) / A10FS+2(2일 후) / A10SS(동시 착수) / "
               "A10FF-1 · 복수는 쉼표로 구분합니다.")

    edited_schedule = st.data_editor(
        schedule_sheet if not schedule_sheet.empty else sch.sample_schedule_sheet(),
        num_rows="dynamic", use_container_width=True, key="schedule_editor",
        column_config={
            "공기": st.column_config.NumberColumn("공기(영업일)", format="%d",
                                                min_value=0),
            "마일스톤": st.column_config.SelectboxColumn("마일스톤", options=["", "Y"]),
            "고정시작일": st.column_config.TextColumn(
                "고정시작일", help="비우면 선행공정에 따라 자동 계산 (예: 2026-08-03)"),
        })

    if st.button("공정계획 저장", type="primary", use_container_width=True,
                 key="save_schedule"):
        if require_edit("공정계획 저장"):
            with st.spinner("저장 중..."):
                result = dbx.save(sch.SCHEDULE_SHEET, edited_schedule)
            if result:
                audit("공정계획 저장", f"{len(edited_schedule)}행")
                st.success(result.message)
                st.rerun()
            else:
                st.error(result.message)

# ═══════════════════════════════════════════════════════════
# TAB 6: 설계변경
# ═══════════════════════════════════════════════════════════
with tab_chg:
    st.subheader("설계변경 대비표")
    st.caption("클라우드에 저장된 당초본과 현재 내역을 비교합니다. "
               "신규·삭제 항목이 자동으로 드러나고 총액 검증이 함께 수행됩니다.")

    cloud_list = st.session_state.cloud_project_list or db.get_cloud_projects_list()
    if not cloud_list:
        st.info("클라우드에 저장된 프로젝트가 있어야 당초본을 불러올 수 있습니다. "
                "사이드바에서 '클라우드 목록 갱신/조회'를 먼저 실행하세요.")
    else:
        base_names = [p["name"] for p in cloud_list]
        base_name = st.selectbox("당초본 선택 (클라우드)", base_names, key="chg_base")
        if st.button("현재 내역과 비교", type="primary", use_container_width=True,
                     key="do_compare"):
            with st.spinner(f"'{base_name}' 불러오는 중..."):
                result = db.load_project_from_cloud(base_name)
            if result:
                before_df, _ = result.data
                st.session_state["_change_before"] = before_df
                st.session_state["_change_base_name"] = base_name
            else:
                st.error(result.message)

    before_df = st.session_state.get("_change_before")
    if before_df is not None:
        st.caption(f"당초본: {st.session_state.get('_change_base_name', '-')}  →  "
                   f"변경본: {state.current_project()} (현재 작업 중)")
        hide_same = st.checkbox("변동없음 항목 숨기기", value=True, key="chg_hide_same")

        change_table, change_issues = chg.compare(
            before_df, state.get_estimate(),
            df_reasons=dbx.get_reason_sheet(), include_same=not hide_same)

        change_report = chg.validate(change_issues)
        errors = change_report[change_report["수준"] == "오류"]
        if not errors.empty:
            st.error("총액 검증 실패 — 증감액 합계가 총액 차이와 일치하지 않습니다.")
            st.dataframe(errors, use_container_width=True, hide_index=True)

        contract_table = chg.compare_contract_price(
            before_df, state.get_estimate(), config.DEFAULT_RATES,
            calc.calculate_cost_summary)

        st.markdown("##### 임원보고 요약")
        st.dataframe(chg.build_executive_summary(
            change_table, project_name=state.current_project(),
            contract_table=contract_table), use_container_width=True, hide_index=True)

        left, right = st.columns(2)
        with left:
            st.markdown("##### 변경유형별")
            st.dataframe(chg.summarize_by_type(change_table),
                         use_container_width=True, hide_index=True)
        with right:
            st.markdown("##### 비목별 원가 영향")
            st.dataframe(chg.summarize_by_cost_group(change_table),
                         use_container_width=True, hide_index=True)

        st.markdown("##### 대비표")
        st.dataframe(change_table, use_container_width=True, hide_index=True)

        st.markdown("##### 도급액 증감 (제비율 반영)")
        st.dataframe(contract_table, use_container_width=True, hide_index=True)

        warns = change_report[change_report["수준"] == "주의"]
        if not warns.empty:
            with st.expander(f"변경사유 미기재 {len(warns)}건"):
                st.dataframe(warns, use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("##### 변경사유 편집")
    reason_sheet = dbx.get_reason_sheet()
    edited_reasons = st.data_editor(
        reason_sheet if not reason_sheet.empty else chg.sample_reason_sheet(),
        num_rows="dynamic", use_container_width=True, key="reason_editor")

    if st.button("변경사유 저장", type="primary", use_container_width=True,
                 key="save_reasons"):
        if require_edit("변경사유 저장"):
            with st.spinner("저장 중..."):
                result = dbx.save(chg.REASON_SHEET, edited_reasons)
            if result:
                audit("변경사유 저장", f"{len(edited_reasons)}행")
                st.success(result.message)
                st.rerun()
            else:
                st.error(result.message)

# ═══════════════════════════════════════════════════════════
# TAB 7: 기초 데이터 관리
# ═══════════════════════════════════════════════════════════
with tab_db:
    st.subheader("기초 데이터 관리")

    # ── 설계서 일괄 다운로드 ──────────────────────────────
    st.markdown("### 설계서 일괄 다운로드")
    st.caption("수량산출서·일위대가표·공정표·대비표를 한 엑셀 파일로 내려받습니다.")

    try:
        appendix = io.BytesIO()
        sheet_count = 0
        with pd.ExcelWriter(appendix, engine="openpyxl") as writer:
            takeoff_computed, _ = tko.compute_takeoff(dbx.get_takeoff_sheet())
            if not takeoff_computed.empty:
                tko.build_takeoff_report(takeoff_computed).to_excel(
                    writer, index=False, sheet_name="수량산출서")
                sheet_count += 1
            if resolutions:
                boq.build_ilwidaega_table(resolutions).to_excel(
                    writer, index=False, sheet_name="일위대가표")
                sheet_count += 1
            appendix_schedule = sch.compute_schedule(
                dbx.get_schedule_sheet(), project_start=date.today(),
                holidays=sch.default_holidays(), df_amounts=state.get_estimate())
            if not appendix_schedule["table"].empty:
                appendix_schedule["table"].to_excel(
                    writer, index=False, sheet_name="공정표")
                sheet_count += 1
            if sheet_count == 0:
                pd.DataFrame([{"안내": "출력할 부속 서류가 없습니다."}]).to_excel(
                    writer, index=False, sheet_name="안내")

        st.download_button(
            f"설계서 부속서류 다운로드 ({sheet_count}종)",
            data=appendix.getvalue(),
            file_name=f"{state.current_project()}_설계서부속_{datetime.now():%Y%m%d}.xlsx",
            mime=XLSX_MIME, use_container_width=True, key="download_appendix",
            disabled=sheet_count == 0)
    except Exception as exc:
        log.exception("부속서류 생성 실패")
        st.warning(f"부속서류 생성 중 오류: {type(exc).__name__} - {exc}")

    st.divider()
    st.markdown("### 통합 데이터 확인 및 개별 관리")

    search_column, count_column, _ = st.columns([1.2, 1, 2])
    search_keyword = search_column.text_input("항목명 검색 키워드",
                                              placeholder="예: 철근, 굴착기")

    master_view = db.get_all_master_items_combined(search_keyword=search_keyword)
    show_errors()

    master_view.index = range(1, len(master_view) + 1)
    master_view.index.name = "NO."
    count_column.caption(f"검색 결과: **{len(master_view):,}건**")

    edited_master = st.data_editor(
        master_view, num_rows="dynamic", use_container_width=True, key="master_editor",
        column_config={
            "구분": st.column_config.SelectboxColumn(
                "구분 (필수)", options=config.MASTER_SHEET_NAMES, required=True),
            "unit_price": st.column_config.NumberColumn("unit_price", format="%d",
                                                        min_value=0),
        })

    if st.button("전체 변경사항 구글 시트에 자동 분리 저장", type="primary",
                 use_container_width=True, key="save_master"):
        if not require_edit("마스터 데이터 저장"):
            pass
        elif search_keyword:
            st.warning("검색어가 입력된 상태에서는 검색되지 않은 항목이 유실됩니다. "
                       "검색어를 비우고 저장해주세요.")
        else:
            with st.spinner("저장 중... (원자적 교체 방식으로 안전하게 기록합니다)"):
                final_df = edited_master.dropna(subset=["item_name", "구분"])
                final_df = final_df[
                    final_df["구분"].astype(str).str.strip() != ""].reset_index(drop=True)
                result = db.upload_combined_dataframe_to_master(final_df)
            if result:
                audit("마스터 저장", f"{len(final_df)}건")
                st.success(result.message)
                st.rerun()
            else:
                st.error(result.message)

    with st.expander("마스터 데이터 백업 및 복구"):
        backup_ids = db.get_master_backup_ids()
        if backup_ids:
            selected_backup = st.selectbox("복구할 백업 시점", backup_ids,
                                           format_func=lambda b: b.replace("_", " ", 1))
            confirmed = st.checkbox(
                "현재 마스터 데이터를 선택한 백업으로 덮어쓰는 것을 확인했습니다.",
                key="confirm_restore")
            if st.button("선택 백업으로 복구", use_container_width=True, key="do_restore"):
                if not require_edit("백업 복구"):
                    pass
                elif not confirmed:
                    st.warning("복구 전 확인란을 선택해주세요.")
                else:
                    with st.spinner("복구 중..."):
                        result = db.restore_master_backup(selected_backup)
                    if result:
                        audit("백업 복구", selected_backup)
                        st.success(result.message)
                        st.rerun()
                    else:
                        st.error(result.message)
        else:
            st.caption("아직 생성된 마스터 데이터 백업이 없습니다. "
                       "저장할 때마다 최근 10개 백업이 자동 보관됩니다.")

    st.divider()
    st.markdown("### 통합 데이터 대량 업로드 (Excel / CSV)")

    template_df = pd.DataFrame(columns=["구분"] + config.MASTER_ALL_COLUMNS)
    template_buffer = io.BytesIO()
    with pd.ExcelWriter(template_buffer, engine="openpyxl") as writer:
        template_df.to_excel(writer, index=False, sheet_name="통합DB양식")
    st.download_button("통합 DB 양식 다운로드", data=template_buffer.getvalue(),
                       file_name="master_template.xlsx", mime=XLSX_MIME,
                       key="download_template")
    st.caption(f"'구분' 열 허용 값: {', '.join(config.MASTER_SHEET_NAMES)} "
               "(자재/노무/장비 같은 축약 표기도 자동 인식됩니다)")

    uploaded_file = st.file_uploader("작성된 통합 엑셀 파일 또는 조달청 CSV 파일 업로드",
                                     type=["xlsx", "csv"])
    if uploaded_file and st.button("통합 일괄 업로드 및 자동 분배 실행", type="primary",
                                   use_container_width=True, key="do_upload"):
        if require_edit("대량 업로드"):
            with st.spinner("데이터 분석 및 병합 중..."):
                try:
                    if uploaded_file.name.lower().endswith(".csv"):
                        try:
                            upload_df = pd.read_csv(uploaded_file, encoding="cp949")
                        except UnicodeDecodeError:
                            uploaded_file.seek(0)
                            upload_df = pd.read_csv(uploaded_file, encoding="utf-8")
                    else:
                        upload_df = pd.read_excel(uploaded_file)

                    if "공통자재구분" in upload_df.columns and "자원명" in upload_df.columns:
                        st.info("조달청 형식을 감지하여 '자재비'로 자동 변환합니다.")
                        upload_df = pd.DataFrame({
                            "구분": "자재비", "category_large": "자재비",
                            "category_mid": upload_df["공통자재구분"],
                            "item_name": upload_df["자원명"],
                            "spec": upload_df["자원규격명"],
                            "unit": upload_df["단위"],
                            "unit_price": upload_df["재료비단가"],
                            "source": "조달청"})

                    if "unit_price" in upload_df.columns:
                        upload_df["unit_price"] = pd.to_numeric(
                            upload_df["unit_price"].astype(str).str.replace(
                                ",", "", regex=False), errors="coerce")

                    if "구분" not in upload_df.columns:
                        st.error("'구분' 컬럼이 없습니다. 양식을 다운로드해 확인하세요.")
                    else:
                        upload_df["구분"] = (upload_df["구분"]
                                           .map(config.normalize_sheet_name)
                                           .fillna(upload_df["구분"]))
                        upload_df = upload_df.dropna(subset=["item_name", "unit_price"])
                        combined = pd.concat(
                            [db.get_all_master_items_combined(), upload_df],
                            ignore_index=True)
                        combined = combined.drop_duplicates(
                            subset=["구분", "item_name", "spec"], keep="last")
                        result = db.upload_combined_dataframe_to_master(combined)
                        if result:
                            audit("대량 업로드", uploaded_file.name)
                            st.balloons()
                            st.success(result.message)
                            st.rerun()
                        else:
                            st.error(result.message)
                except Exception as exc:
                    log.exception("대량 업로드 실패")
                    st.error(f"업로드 처리 중 오류: {type(exc).__name__} - {exc}")
