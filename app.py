# -*- coding: utf-8 -*-
"""
app.py
─────────────────────────────────────────────────────────────
포타송 설계서 작성 - 메인 엔트리

적용 패치
  ① 원자적 저장 + 동시 저장 충돌 감지 (db_manager)
  ② 오류 침묵 제거 → 읽기 실패 사유를 화면에 표시
  ③ Result 타입 단일 처리 (res / res.message)
  ④ 구분 체계 config 일원화 + 원가 미반영 행 경고
  ⑤ estimate_data 제거 → state_manager 단일 상태
"""

import io
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

import config
import db_manager as db
import logic_calculator as calc
import state_manager as state
import ui_components as ui

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
log = config.get_logger("app")

# ═══════════════════════════════════════════════════════════
# 1. 페이지 설정 및 초기화
# ═══════════════════════════════════════════════════════════
st.set_page_config(page_title=config.PAGE_TITLE, page_icon=config.PAGE_ICON, layout="wide")
st.title(config.APP_TITLE)

init_result = db.init_db()
if not init_result:                                    # [패치 ③]
    st.error("⚠️ Google Sheets에 연결할 수 없습니다.")
    st.caption(f"상세 사유: {init_result.message}")     # [패치 ②] 사유 노출
    st.info(
        "관리자에게 다음 설정을 확인해 달라고 요청하세요: "
        "Streamlit secrets의 GOOGLE_CREDENTIALS·SPREADSHEET_URL, "
        "서비스 계정의 스프레드시트 편집 권한, 그리고 Google Sheets API 활성화 여부."
    )
    st.stop()

state.bootstrap()                                      # [패치 ⑤]
state.session_id()                                     # 잠금 소유자 식별용


def show_load_errors():
    """[패치 ②] 읽기 단계에서 발생한 오류를 사용자에게 알린다."""
    for message in db.consume_load_errors():
        st.warning(f"⚠️ 데이터 조회 경고: {message}")


# ═══════════════════════════════════════════════════════════
# 2. 사이드바
# ═══════════════════════════════════════════════════════════
st.sidebar.subheader("📁 설계서 작성")

new_project = st.sidebar.text_input("새 프로젝트명 입력", placeholder="예: 포스코타워-송도 환경개선")
if st.sidebar.button("➕ 새 프로젝트 생성", use_container_width=True):
    ok, msg = state.create_project(new_project)
    if ok:
        st.rerun()
    else:
        st.sidebar.warning(msg)

names = state.project_names()
selected_project = st.sidebar.selectbox(
    "현재 작업 중인 현장 선택", names, index=names.index(state.current_project())
)
if selected_project != state.current_project():
    state.switch_project(selected_project)
    st.rerun()

st.sidebar.button(
    "🗑️ 현재 프로젝트 삭제",
    use_container_width=True,
    on_click=ui.delete_confirmation,
    args=(state.current_project(),),
)

st.sidebar.divider()
st.sidebar.subheader("📝 문서 작성 정보")
st.sidebar.text_input(
    "작성자 / 부서",
    value=st.session_state.get("writer_name", "포스코타워-송도 (이름/직급)"),
    key="writer_name",
    help="견적서 엑셀 상단 제목 블록에 표기됩니다.",
)

st.sidebar.divider()
st.sidebar.subheader("☁️ 클라우드 DB 보관소")

if st.sidebar.button("🔄 클라우드 목록 갱신/조회", use_container_width=True):
    with st.spinner("구글 시트에서 불러오는 중..."):
        db.get_cloud_projects_list.clear()
        st.session_state.cloud_project_list = db.get_cloud_projects_list()

selected_cloud_proj = None
if st.session_state.cloud_project_list:
    options = {f"📂 {p['name']} ({p['date']})": p["name"]
               for p in st.session_state.cloud_project_list}
    selected_cloud_proj = options[st.sidebar.selectbox("불러올 프로젝트 선택", list(options.keys()))]

    if st.sidebar.button("📥 선택 프로젝트 불러오기", use_container_width=True):
        with st.spinner(f"'{selected_cloud_proj}' 데이터를 가져오는 중..."):
            res = db.load_project_from_cloud(selected_cloud_proj)
        if res:                                        # [패치 ③]
            loaded_df, version = res.data
            state.replace_project(selected_cloud_proj, loaded_df, version=version)
            st.rerun()
        else:
            st.sidebar.error(res.message)

    if st.sidebar.button("🗑️ 클라우드에서 삭제", use_container_width=True):
        ui.delete_cloud_confirmation(selected_cloud_proj)

if st.sidebar.button("💾 현재 프로젝트 클라우드 저장", use_container_width=True, type="primary"):
    project = state.current_project()
    with st.spinner("기록 중..."):
        res = db.save_project_to_cloud(
            project, state.get_estimate(), expected_version=state.get_version(project)
        )
    if res:
        state.set_version(project, res.data)
        st.sidebar.success("클라우드 저장 완료!")
    elif res.code == "conflict":                       # [패치 ①] 덮어쓰기 사고 차단
        ui.overwrite_conflict_dialog(project, str(res.data))
    else:
        st.sidebar.error(res.message)

show_load_errors()

# ═══════════════════════════════════════════════════════════
# 3. 메인 탭
# ═══════════════════════════════════════════════════════════
tab_dash, tab1, tab2, tab3 = st.tabs(
    ["🏠 대시보드", "📝 설계 및 원가계산", "📊 자동 공정표", "⚙️ 기초 데이터 관리"]
)

# ── TAB 1: 대시보드 ────────────────────────────────────────
with tab_dash:
    st.subheader(f"🏠 {state.current_project()} 종합 대시보드")
    df_dash = state.get_estimate()

    if df_dash.empty:
        st.info("추가된 내역이 없습니다.")
    else:
        # [패치 ④] 표기 차이와 무관하게 비목별로 집계
        df_dash["비목"] = config.cost_group_series(df_dash).fillna("미분류")
        totals = df_dash.groupby("비목")["합계"].sum()

        cols = st.columns(4)
        cols[0].metric("총 직접공사비", f"{df_dash['합계'].sum():,.0f} 원")
        for i, group in enumerate(config.COST_GROUPS, start=1):
            cols[i].metric(f"{group}비 총액", f"{totals.get(group, 0):,.0f} 원")

        if "미분류" in totals.index:
            st.warning(
                f"⚠️ 구분을 인식할 수 없는 내역 {int((df_dash['비목'] == '미분류').sum())}건"
                f"(합계 {totals['미분류']:,.0f}원)이 원가계산에서 제외됩니다. "
                f"'구분'을 {', '.join(config.GUBUN_OPTIONS)} 중 하나로 수정하세요."
            )

        st.divider()
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**📊 비목별 금액 비중**")
            st.plotly_chart(
                px.pie(df_dash, values="합계", names="비목", hole=0.4,
                       color_discrete_sequence=px.colors.qualitative.Pastel),
                use_container_width=True,
            )
        with c2:
            st.markdown("**📈 주요 공종별 투입 금액**")
            st.plotly_chart(
                px.bar(df_dash, x="공종명", y="합계", color="비목", text_auto=".2s",
                       color_discrete_sequence=px.colors.qualitative.Pastel),
                use_container_width=True,
            )

# ── TAB 2: 설계 및 원가계산 ───────────────────────────────
with tab1:
    st.subheader("🔍 1. 품목 단가 추가")
    add_cols = st.columns(len(config.MASTER_SHEET_NAMES))
    for col, sheet_name in zip(add_cols, config.MASTER_SHEET_NAMES):
        ui.render_add_item_column(col, sheet_name)     # [패치 ④] 하드코딩 제거
    show_load_errors()

    st.divider()
    st.subheader(f"📄 2. 세부 내역서 (을지) - {state.current_project()}")

    display_df = state.get_estimate()                  # [패치 ⑤] 정규화는 state가 보장
    display_df.index = range(1, len(display_df) + 1)
    display_df.index.name = "NO."

    edited_df = st.data_editor(
        display_df,
        column_order=config.ESTIMATE_COLUMNS,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=False,
        key="estimate_editor",
        column_config={
            "구분": st.column_config.SelectboxColumn("구분", options=config.GUBUN_OPTIONS,
                                                    required=True),
            "공종명": st.column_config.TextColumn("공종명"),
            "규격": st.column_config.TextColumn("규격"),
            "단위": st.column_config.SelectboxColumn("단위", options=config.UNIT_OPTIONS),
            "단가": st.column_config.NumberColumn("단가(원)", format="%d", min_value=0),
            "수량": st.column_config.NumberColumn("수량", format="%.2f", step=0.1, min_value=0.0),
            "합계": st.column_config.NumberColumn("합계(원)", format="%d", disabled=True),
            "시작일": st.column_config.DateColumn("시작일", format="YYYY-MM-DD"),
            "종료일": st.column_config.DateColumn("종료일", format="YYYY-MM-DD"),
        },
    )

    # [패치 ⑤] 변경 판정과 기록을 SSOT 한 곳에서 처리 (합계 재계산 포함)
    if state.has_changed(edited_df):
        state.set_estimate(edited_df)
        st.rerun()

    st.info(
        "💡 **항목 삭제 방법:** 표 맨 왼쪽의 **NO. 칸**을 클릭해 행을 선택한 후 "
        "**키보드 `Delete` 키** 또는 우측 상단 **휴지통 아이콘(🗑️)** 을 누르세요."
    )

    _, col_btn_all = st.columns([7, 3])
    with col_btn_all:
        if st.button("🚨 전체 내역 비우기", type="primary", use_container_width=True,
                     key="del_all_btn"):
            ui.delete_all_confirmation()

    st.divider()
    st.subheader("📊 3. 조달청 기준 원가계산서 (갑지)")
    st.caption(
        "⚠️ 제비율과 산식은 적용 기준·연도에 따라 달라집니다. "
        "계약·입찰 제출 전 최신 조달청 기준으로 반드시 재검토하세요."
    )

    with st.expander("⚙️ 제비율(%) 설정", expanded=True):
        rate_labels = [
            ("indirect_labor", "간접노무비율(%)"), ("sanjae", "산재보험료율(%)"),
            ("goyong", "고용보험료율(%)"), ("health", "국민건강보험료율(%)"),
            ("elderly", "노인장기요양보험료율(%)"), ("pension", "국민연금보험료율(%)"),
            ("retire", "퇴직공제부금비율(%)"), ("safety", "산업안전보건비율(%)"),
            ("env", "환경보전비율(%)"), ("etc_exp", "기타경비율(%)"),
            ("general_admin", "일반관리비율(%)"), ("profit", "이윤율(%)"),
            ("tax", "부가가치세율(%)"),
        ]
        rate_cols = st.columns(4)
        rates = {}
        for i, (key, label) in enumerate(rate_labels):
            with rate_cols[i % 4]:
                rates[key] = st.number_input(label, value=config.DEFAULT_RATES[key],
                                             step=0.1, key=f"rate_{key}")

    estimate_df = state.get_estimate()

    # [패치 ④] 원가계산에 반영되지 못한 금액을 사용자에게 즉시 경고
    audit = calc.audit_categories(estimate_df)
    if audit["unknown_rows"]:
        detail = ", ".join(f"'{k}' {v:,}원" for k, v in audit["unknown"].items())
        st.error(
            f"🚫 구분 미인식 {audit['unknown_rows']}건이 원가계산에서 제외되었습니다 ({detail}). "
            "위 내역서에서 '구분'을 수정한 후 다시 확인하세요."
        )

    summary_df = pd.DataFrame(calc.calculate_cost_summary(estimate_df, rates))
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

    if not estimate_df.empty:
        st.markdown("##### 📥 4. 견적서 산출물 다운로드")
        d1, d2 = st.columns([1, 3])
        with d1:
            include_rates = st.checkbox("제비율 시트 포함", value=True, key="chk_rates_sheet")
        with d2:
            st.caption("갑지(원가계산서) · 을지(세부내역서) 2개 시트로 구성되며, "
                       "A4 인쇄 서식이 적용되어 있습니다.")

        try:
            with st.spinner("엑셀 생성 중..."):
                excel_bytes = calc.generate_excel_bytes(
                    estimate_df=estimate_df,
                    summary_df=summary_df,
                    project_name=state.current_project(),
                    writer_name=st.session_state.get("writer_name", "시설관리팀"),
                    rates=rates if include_rates else None,
                )
            st.download_button(
                "📊 견적서 엑셀 다운로드",
                data=excel_bytes,
                file_name=f"{state.current_project()}_원가계산서_{datetime.now():%Y%m%d}.xlsx",
                mime=XLSX_MIME,
                type="primary",
                use_container_width=True,
                key="dl_estimate_xlsx",
            )
        except Exception as exc:                        # [패치 ②] 침묵 금지
            log.exception("엑셀 생성 실패")
            st.error(f"엑셀 생성 중 오류가 발생했습니다: {type(exc).__name__} - {exc}")
    else:
        st.info("세부 내역서에 항목을 1건 이상 입력하면 견적서 엑셀을 다운로드할 수 있습니다.")

# ── TAB 3: 자동 공정표 ────────────────────────────────────
with tab2:
    st.subheader(f"📅 자동 공정표 - {state.current_project()}")
    df_gantt = state.get_estimate()

    if df_gantt.empty:
        st.info("추가된 내역이 없습니다.")
    else:
        valid = df_gantt.dropna(subset=["시작일", "종료일"])
        missing = len(df_gantt) - len(valid)
        if missing:
            st.warning(f"⚠️ 시작일/종료일이 비어 있는 {missing}건은 공정표에서 제외됩니다.")
        if valid.empty:
            st.info("표시할 수 있는 일정 데이터가 없습니다.")
        else:
            valid = valid.copy()
            valid["비목"] = config.cost_group_series(valid).fillna("미분류")
            fig = px.timeline(valid, x_start="시작일", x_end="종료일", y="공종명", color="비목")
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(fig, use_container_width=True)

# ── TAB 4: 기초 데이터 관리 ───────────────────────────────
with tab3:
    st.subheader("⚙️ 기초 데이터 관리")
    st.markdown("### 1. 통합 데이터 확인 및 개별 관리")

    col_search, col_count, _ = st.columns([1.2, 1, 2])
    search_kw = col_search.text_input("항목명 검색 키워드", placeholder="예: 철근, 굴착기")

    df_master = db.get_all_master_items_combined(search_keyword=search_kw)
    show_load_errors()

    df_master.index = range(1, len(df_master) + 1)
    df_master.index.name = "NO."
    col_count.caption(f"🔎 검색 결과: **{len(df_master):,}건**")

    edited_master = st.data_editor(
        df_master, num_rows="dynamic", use_container_width=True, key="master_editor",
        column_config={
            "구분": st.column_config.SelectboxColumn(
                "구분 (필수)", options=config.MASTER_SHEET_NAMES, required=True),
            "unit_price": st.column_config.NumberColumn("unit_price", format="%d", min_value=0),
        },
    )

    if st.button("💾 전체 변경사항 구글 시트에 자동 분리 저장", type="primary",
                 use_container_width=True, key="save_master_db_btn"):
        if search_kw:
            st.warning("⚠️ 검색어가 입력된 상태에서는 검색되지 않은 항목이 유실됩니다. "
                       "검색어를 비우고 저장해주세요.")
        else:
            with st.spinner("저장 중... (원자적 교체 방식으로 안전하게 기록합니다)"):
                final_df = edited_master.dropna(subset=["item_name", "구분"])
                final_df = final_df[final_df["구분"].astype(str).str.strip() != ""] \
                    .reset_index(drop=True)
                res = db.upload_combined_dataframe_to_master(final_df)
            if res:
                st.success(res.message)
                st.rerun()
            else:
                st.error(res.message)

    with st.expander("🛟 마스터 데이터 백업 및 복구"):
        backup_ids = db.get_master_backup_ids()
        if backup_ids:
            selected_backup = st.selectbox(
                "복구할 백업 시점", backup_ids,
                format_func=lambda b: b.replace("_", " ", 1),
            )
            restore_confirmed = st.checkbox(
                "현재 마스터 데이터를 선택한 백업으로 덮어쓰는 것을 확인했습니다.",
                key="confirm_master_restore",
            )
            if st.button("♻️ 선택 백업으로 복구", use_container_width=True):
                if not restore_confirmed:
                    st.warning("복구 전 확인란을 선택해주세요.")
                else:
                    with st.spinner("복구 중..."):
                        res = db.restore_master_backup(selected_backup)
                    if res:
                        st.success(res.message)
                        st.rerun()
                    else:
                        st.error(res.message)
        else:
            st.caption("아직 생성된 마스터 데이터 백업이 없습니다. "
                       "저장할 때마다 최근 10개 백업이 자동 보관됩니다.")

    st.divider()
    st.markdown("### 2. 통합 데이터 대량 업로드 (Excel / CSV)")

    template_df = pd.DataFrame(columns=["구분"] + config.MASTER_ALL_COLUMNS)
    output_template = io.BytesIO()
    with pd.ExcelWriter(output_template, engine="openpyxl") as tpl_writer:
        template_df.to_excel(tpl_writer, index=False, sheet_name="통합DB양식")
    st.download_button(
        "⬇️ 통합 DB 양식 다운로드",
        data=output_template.getvalue(),
        file_name="master_template.xlsx",
        mime=XLSX_MIME,
        key="dl_master_template",
    )
    st.caption(f"'구분' 열 허용 값: {', '.join(config.MASTER_SHEET_NAMES)} "
               "(자재/노무/장비 같은 축약 표기도 자동 인식됩니다)")

    uploaded_file = st.file_uploader("작성된 통합 엑셀 파일 또는 조달청 CSV 파일 업로드",
                                     type=["xlsx", "csv"])
    if uploaded_file and st.button("🚀 통합 일괄 업로드 및 자동 분배 실행", type="primary",
                                   use_container_width=True):
        with st.spinner("데이터 분석 및 병합 중..."):
            try:
                if uploaded_file.name.lower().endswith(".csv"):
                    try:
                        up_df = pd.read_csv(uploaded_file, encoding="cp949")
                    except UnicodeDecodeError:
                        uploaded_file.seek(0)
                        up_df = pd.read_csv(uploaded_file, encoding="utf-8")
                else:
                    up_df = pd.read_excel(uploaded_file)

                if "공통자재구분" in up_df.columns and "자원명" in up_df.columns:
                    st.info("💡 조달청 형식을 감지하여 '자재비'로 자동 변환합니다.")
                    up_df = pd.DataFrame({
                        "구분": "자재비",
                        "category_large": "자재비",
                        "category_mid": up_df["공통자재구분"],
                        "item_name": up_df["자원명"],
                        "spec": up_df["자원규격명"],
                        "unit": up_df["단위"],
                        "unit_price": up_df["재료비단가"],
                        "source": "조달청",
                    })

                if "unit_price" in up_df.columns:
                    up_df["unit_price"] = pd.to_numeric(
                        up_df["unit_price"].astype(str).str.replace(",", "", regex=False),
                        errors="coerce")

                if "구분" not in up_df.columns:
                    st.error("⚠️ '구분' 컬럼이 없습니다. 양식을 다운로드해 확인하세요.")
                else:
                    # [패치 ④] 업로드 단계에서 구분을 시트명으로 정규화 → 조용한 행 유실 방지
                    up_df["구분"] = up_df["구분"].map(config.normalize_sheet_name) \
                                                 .fillna(up_df["구분"])
                    up_df = up_df.dropna(subset=["item_name", "unit_price"])

                    combined_df = pd.concat(
                        [db.get_all_master_items_combined(), up_df], ignore_index=True)
                    combined_df = combined_df.drop_duplicates(
                        subset=["구분", "item_name", "spec"], keep="last")

                    res = db.upload_combined_dataframe_to_master(combined_df)
                    if res:
                        st.balloons()
                        st.success(res.message)
                        st.rerun()
                    else:
                        st.error(res.message)
            except Exception as exc:
                log.exception("대량 업로드 실패")
                st.error(f"업로드 처리 중 오류: {type(exc).__name__} - {exc}")
