import streamlit as st
import pandas as pd
import plotly.express as px
import io

import config
import db_manager as db
import logic_calculator as calc
import ui_components as ui

# --- 1. 페이지 설정 및 초기화 ---
st.set_page_config(
    page_title=config.PAGE_TITLE,
    page_icon=config.PAGE_ICON,
    layout="wide"
)
st.title(config.APP_TITLE)

db.init_db()
config.init_session_state()

# --- 2. 클라우드 로드 함수 ---
def load_project_from_cloud(project_name):
    try:
        ws = db.get_sheet().worksheet("프로젝트저장소")
        for row in ws.get_all_values()[1:]:
            if row[0] == project_name and row[2]:
                return pd.read_json(io.StringIO(row[2]), orient='records')
        return None
    except Exception as e:
        return str(e)

# --- 3. 사이드바 (프로젝트 및 클라우드 관리) ---
st.sidebar.subheader("📁 설계서 작성")
new_project = st.sidebar.text_input("새 프로젝트명 입력", placeholder="예: 포스코타워-송도 환경개선")
if st.sidebar.button("➕ 새 프로젝트 생성", use_container_width=True) and new_project:
    if new_project not in st.session_state.projects:
        st.session_state.projects[new_project] = pd.DataFrame(columns=["공종명", "구분", "단위", "단가", "수량", "합계", "시작일", "종료일"])
        st.session_state.current_project = new_project
        st.session_state.estimate_data = st.session_state.projects[new_project].copy()
        st.rerun()
    else:
        st.sidebar.warning("이미 존재하는 프로젝트입니다.")

project_list = list(st.session_state.projects.keys())
selected_project = st.sidebar.selectbox("현재 작업 중인 현장 선택", project_list, index=project_list.index(st.session_state.current_project))
if selected_project != st.session_state.current_project:
    st.session_state.current_project = selected_project
    st.session_state.estimate_data = st.session_state.projects[selected_project].copy()
    st.rerun()

st.sidebar.button(
    "🗑️ 현재 프로젝트 삭제",
    use_container_width=True,
    disabled=(len(st.session_state.projects) <= 1),
    on_click=ui.delete_confirmation,
    args=(st.session_state.current_project,)
)

st.sidebar.divider()
st.sidebar.subheader("☁️ 클라우드 DB 보관소")
if st.sidebar.button("🔄 클라우드 목록 갱신/조회", use_container_width=True):
    with st.spinner("구글 시트에서 불러오는 중..."):
        db.get_cloud_projects_list.clear()
        st.session_state.cloud_project_list = db.get_cloud_projects_list()

if st.session_state.cloud_project_list:
    project_options = {f"📂 {proj['name']} ({proj['date']})": proj['name'] for proj in st.session_state.cloud_project_list}
    selected_cloud_proj = project_options[st.sidebar.selectbox("불러올 프로젝트 선택", list(project_options.keys()))]

    if st.sidebar.button("📥 선택 프로젝트 불러오기", use_container_width=True):
        with st.spinner(f"'{selected_cloud_proj}' 데이터를 가져오는 중..."):
            loaded_df = load_project_from_cloud(selected_cloud_proj)
            if isinstance(loaded_df, pd.DataFrame):
                st.session_state.projects[selected_cloud_proj] = loaded_df
                st.session_state.current_project = selected_cloud_proj
                st.session_state.estimate_data = loaded_df.copy()
                st.rerun()
            else:
                st.sidebar.error("데이터를 찾을 수 없거나 불러오기 실패했습니다.")
                
    if st.sidebar.button("🗑️ 클라우드에서 삭제", use_container_width=True):
        ui.delete_cloud_confirmation(selected_cloud_proj)

if st.sidebar.button("💾 현재 프로젝트 클라우드 저장", use_container_width=True, type="primary"):
    with st.spinner("기록 중..."):
        st.session_state.projects[st.session_state.current_project] = st.session_state.estimate_data.copy()
        res = db.save_project_to_cloud(st.session_state.current_project, st.session_state.estimate_data)
        if res is True:
            st.sidebar.success("클라우드 저장 완료!")
        else:
            st.sidebar.error(f"저장 실패: {res}")

# --- 4. 메인 탭 영역 ---
tab_dash, tab1, tab2, tab3 = st.tabs(["🏠 대시보드", "📝 설계 및 원가계산", "📊 자동 공정표", "⚙️ 기초 데이터 관리"])

# TAB 1: 대시보드
with tab_dash:
    st.subheader(f"🏠 {st.session_state.current_project} 종합 대시보드")
    if st.session_state.estimate_data.empty:
        st.info("추가된 내역이 없습니다.")
    else:
        df_dash = st.session_state.estimate_data.copy()
        df_dash["합계"] = pd.to_numeric(df_dash["합계"], errors="coerce").fillna(0)
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("총 직접공사비", f"{df_dash['합계'].sum():,.0f} 원")
        c2.metric("자재비 총액", f"{df_dash[df_dash['구분'] == '자재']['합계'].sum():,.0f} 원")
        c3.metric("노무비 총액", f"{df_dash[df_dash['구분'] == '노무']['합계'].sum():,.0f} 원")
        c4.metric("장비비 총액", f"{df_dash[df_dash['구분'] == '장비']['합계'].sum():,.0f} 원")
        
        st.divider()
        col_chart1, col_chart2 = st.columns(2)
        with col_chart1:
            st.markdown("**📊 자재/노무/장비 금액 비중**")
            st.plotly_chart(px.pie(df_dash, values='합계', names='구분', hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel), use_container_width=True)
        with col_chart2:
            st.markdown("**📈 주요 공종별 투입 금액**")
            st.plotly_chart(px.bar(df_dash, x='공종명', y='합계', color='구분', text_auto='.2s', color_discrete_sequence=px.colors.qualitative.Pastel), use_container_width=True)

# TAB 2: 설계 및 원가계산
with tab1:
    st.subheader("🔍 1. 품목 단가 추가")
    col1, col2, col3, col4 = st.columns(4)
    
    ui.render_add_item_column(col1, "자재비", "자재비", "자재", "식", "수량", "🧱")
    ui.render_add_item_column(col2, "인건비", "인건비", "노무", "인", "인원", "👷")
    ui.render_add_item_column(col3, "장비비", "장비비", "장비", "시간", "시간", "🏗️")
    ui.render_add_item_column(col4, "세트", "세트", "자재", "식", "", "📦")

    st.divider()
    st.subheader(f"📄 2. 세부 내역서 (을지) - {st.session_state.current_project}")

    display_df = st.session_state.estimate_data.copy()
    for col_name in ["단가", "수량", "합계"]:
        if col_name in display_df.columns:
            display_df[col_name] = pd.to_numeric(display_df[col_name], errors='coerce').fillna(0)
    for col_name in ["시작일", "종료일"]:
        if col_name in display_df.columns:
            display_df[col_name] = pd.to_datetime(display_df[col_name], errors='coerce')
    
    display_df.index = range(1, len(display_df) + 1)

    edited_df = st.data_editor(
        display_df, num_rows="dynamic", use_container_width=True,
        column_config={
            "단위": st.column_config.SelectboxColumn("단위", options=["일", "시간", "식", "m3", "ton", "EA", "인", "대", "포", "장"]),
            "단가": st.column_config.NumberColumn("단가(원)", format="%d"),
            "수량": st.column_config.NumberColumn("수량", format="%.2f", step=0.1),
            "합계": st.column_config.NumberColumn("합계(원)", disabled=True),
            "시작일": st.column_config.DateColumn("시작일", format="YYYY-MM-DD"),
            "종료일": st.column_config.DateColumn("종료일", format="YYYY-MM-DD"),
        }
    )

    if not edited_df.empty:
        edited_df = edited_df.reset_index(drop=True)
        edited_df["합계"] = (edited_df["단가"] * edited_df["수량"]).astype(int)
        if not edited_df.equals(st.session_state.estimate_data):
            st.session_state.estimate_data = edited_df
            st.rerun()

    if st.button("🗑️ 현재 프로젝트 내역 전체 비우기"):
        st.session_state.estimate_data = pd.DataFrame(columns=["공종명", "구분", "단위", "단가", "수량", "합계", "시작일", "종료일"])
        st.rerun()

    st.divider()
    st.subheader("📊 3. 조달청 기준 원가계산서 (갑지)")

    with st.expander("⚙️ 제비율(%) 설정", expanded=True):
        r1, r2, r3, r4 = st.columns(4)
        rates = {}
        with r1:
            rates['indirect_labor'] = st.number_input("간접노무비율(%)", value=config.DEFAULT_RATES['indirect_labor'], step=0.1)
            rates['sanjae'] = st.number_input("산재보험료율(%)", value=config.DEFAULT_RATES['sanjae'], step=0.1)
            rates['goyong'] = st.number_input("고용보험료율(%)", value=config.DEFAULT_RATES['goyong'], step=0.1)
        with r2:
            rates['health'] = st.number_input("국민건강보험료율(%)", value=config.DEFAULT_RATES['health'], step=0.1)
            rates['elderly'] = st.number_input("노인장기요양보험료율(%)", value=config.DEFAULT_RATES['elderly'], step=0.1)
            rates['pension'] = st.number_input("국민연금보험료율(%)", value=config.DEFAULT_RATES['pension'], step=0.1)
        with r3:
            rates['retire'] = st.number_input("퇴직공제부금비율(%)", value=config.DEFAULT_RATES['retire'], step=0.1)
            rates['safety'] = st.number_input("산업안전보건비율(%)", value=config.DEFAULT_RATES['safety'], step=0.1)
            rates['env'] = st.number_input("환경보전비율(%)", value=config.DEFAULT_RATES['env'], step=0.1)
        with r4:
            rates['etc_exp'] = st.number_input("기타경비율(%)", value=config.DEFAULT_RATES['etc_exp'], step=0.1)
            rates['general_admin'] = st.number_input("일반관리비율(%)", value=config.DEFAULT_RATES['general_admin'], step=0.1)
            rates['profit'] = st.number_input("이윤율(%)", value=config.DEFAULT_RATES['profit'], step=0.1)
            rates['tax'] = st.number_input("부가가치세율(%)", value=config.DEFAULT_RATES['tax'], step=0.1)

    summary_df = pd.DataFrame(calc.calculate_cost_summary(st.session_state.estimate_data, rates))
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

    if not st.session_state.estimate_data.empty:
        excel_bytes = calc.generate_excel_bytes(st.session_state.estimate_data, summary_df)
        st.download_button(
            "📊 견적서 엑셀 다운로드",
            data=excel_bytes,
            file_name=f"{st.session_state.current_project}_견적서.xlsx"
        )

# TAB 3: 자동 공정표
with tab2:
    st.subheader(f"📅 자동 공정표 - {st.session_state.current_project}")
    if not st.session_state.estimate_data.empty:
        df_gantt = st.session_state.estimate_data.copy()
        df_gantt['시작일'] = pd.to_datetime(df_gantt['시작일'], errors='coerce')
        df_gantt['종료일'] = pd.to_datetime(df_gantt['종료일'], errors='coerce')
        fig = px.timeline(df_gantt, x_start="시작일", x_end="종료일", y="공종명", color="구분")
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, use_container_width=True)

# TAB 4: 기초 데이터 관리
with tab3:
    st.subheader("⚙️ 기초 데이터 관리")
    st.markdown("### 1. 통합 데이터 확인 및 개별 관리")
    col_search, col_count, _ = st.columns([1.2, 1, 2])
    search_kw = col_search.text_input("항목명 검색 키워드", placeholder="예: 철근, 굴착기")

    df_master = db.get_all_master_items_combined(search_keyword=search_kw)
    df_master.index = range(1, len(df_master) + 1)
    col_count.caption(f"\n🔎 검색 결과: **{len(df_master):,}건**")

    edited_master = st.data_editor(
        df_master, num_rows="dynamic", use_container_width=True,
        column_config={"구분": st.column_config.SelectboxColumn("구분 (필수)", options=["자재비", "인건비", "장비비", "세트"], required=True)}
    )

    if st.button("💾 전체 변경사항 구글 시트에 자동 분리 저장", type="primary", use_container_width=True):
        if search_kw:
            st.warning("⚠️ 검색어가 입력된 상태에서는 데이터가 유실될 수 있습니다. 검색어를 비우고 저장해주세요.")
        else:
            with st.spinner("저장 중..."):
                final_df = edited_master.dropna(subset=["item_name", "구분"])
                final_df = final_df[final_df["구분"].str.strip() != ""].reset_index(drop=True)
                res = db.upload_combined_dataframe_to_master(final_df)
                if res["status"] == "success":
                    st.success(res["message"])
                    st.rerun()
                else:
                    st.error(res["message"])

    st.divider()
    st.markdown("### 2. 통합 데이터 대량 업로드 (Excel / CSV)")
    
    template_df = pd.DataFrame(columns=["구분", "category_large", "category_mid", "item_name", "spec", "unit", "unit_price", "source"])
    output_template = io.BytesIO()
    template_df.to_excel(pd.ExcelWriter(output_template, engine='openpyxl'), index=False)
    st.download_button("⬇️ 통합 DB 양식 다운로드", data=output_template.getvalue(), file_name="master_template.xlsx")

    uploaded_file = st.file_uploader("작성된 통합 엑셀 파일 또는 조달청 CSV 파일 업로드", type=["xlsx", "csv"])
    if uploaded_file and st.button("🚀 통합 일괄 업로드 및 자동 분배 실행", type="primary", use_container_width=True):
        with st.spinner("데이터 분석 및 병합 중..."):
            try:
                up_df = pd.read_csv(uploaded_file, encoding='cp949' if uploaded_file.name.endswith('.csv') else 'utf-8') if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
                
                if "공통자재구분" in up_df.columns and "자원명" in up_df.columns:
                    st.info("💡 조달청 형식을 감지하여 '자재비'로 자동 변환합니다.")
                    up_df = pd.DataFrame({
                        '구분': '자재비', 'category_large': '자재비', 'category_mid': up_df['공통자재구분'],
                        'item_name': up_df['자원명'], 'spec': up_df['자원규격명'], 'unit': up_df['단위'],
                        'unit_price': up_df['재료비단가'], 'source': '조달청'
                    })

                if 'unit_price' in up_df.columns:
                    up_df['unit_price'] = pd.to_numeric(up_df['unit_price'].astype(str).str.replace(',', ''), errors='coerce')

                if "구분" not in up_df.columns:
                    st.error("⚠️ '구분' 컬럼이 없습니다.")
                else:
                    up_df = up_df.dropna(subset=["item_name", "unit_price"])
                    combined_df = pd.concat([db.get_all_master_items_combined(), up_df], ignore_index=True)
                    combined_df = combined_df.drop_duplicates(subset=['구분', 'item_name', 'spec'], keep='last')
                    
                    res = db.upload_combined_dataframe_to_master(combined_df)
                    if res["status"] == "success":
                        st.balloons()
                        st.success("🎉 성공적으로 병합되었습니다.")
                        st.rerun()
                    else:
                        st.error(res["message"])
            except Exception as e:
                st.error(f"⚠️ 업로드 실패: {e}")
