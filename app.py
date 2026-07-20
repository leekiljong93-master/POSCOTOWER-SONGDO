import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import date, datetime
import io
import os
import db_manager as db

st.set_page_config(page_title="포타송 설계서 작성(Ver.260720)", page_icon="🏗️", layout="wide")
st.title("🏗️ 포타송 설계서 작성(by.PI_Lee)")

db.init_db()


def save_project_to_cloud(project_name, df):
    try:
        doc = db.get_sheet()
        ws = doc.worksheet("프로젝트저장소")
        data_json = df.to_json(orient='records', force_ascii=False)

        records = ws.get_all_records()
        row_idx = -1
        for i, r in enumerate(records):
            if str(r.get('project_name', '')) == str(project_name):
                row_idx = i + 2
                break

        if row_idx != -1:
            ws.update(f"A{row_idx}:C{row_idx}",
                      [[project_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), data_json]])
        else:
            ws.append_row([project_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), data_json])
        return True
    except Exception as e:
        return str(e)


def load_project_from_cloud(project_name):
    try:
        doc = db.get_sheet()
        ws = doc.worksheet("프로젝트저장소")
        rows = ws.get_all_values()
        for row in rows[1:]:
            if row[0] == project_name:
                data_json = row[2]
                if not data_json: return None
                return pd.read_json(io.StringIO(data_json), orient='records')
        return None
    except Exception as e:
        return str(e)


@st.dialog("⚠️ 프로젝트 삭제 확인")
def delete_confirmation(project_name):
    st.markdown(f"### 🗑️ 프로젝트 삭제")
    st.error(f"**'{project_name}'** 프로젝트를 정말로 삭제하시겠습니까?\n\n삭제된 데이터와 클라우드 DB 기록은 **절대 복구할 수 없습니다.**")

    st.write("")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("🔥 정말 삭제하기", use_container_width=True):
            if project_name in st.session_state.projects:
                del st.session_state.projects[project_name]

            res = db.delete_project_from_cloud(project_name)

            if len(st.session_state.projects) > 0:
                st.session_state.current_project = list(st.session_state.projects.keys())[0]
                st.session_state.estimate_data = st.session_state.projects[st.session_state.current_project].copy()
            else:
                st.session_state.projects = {
                    "기본 프로젝트": pd.DataFrame(columns=["공종명", "구분", "단위", "단가", "수량", "합계", "시작일", "종료일"])}
                st.session_state.current_project = "기본 프로젝트"
                st.session_state.estimate_data = st.session_state.projects["기본 프로젝트"].copy()

            st.rerun()

    with col2:
        if st.button("취소", use_container_width=True):
            st.rerun()


@st.dialog("⚠️ 클라우드 프로젝트 삭제 확인")
def delete_cloud_confirmation(project_name):
    st.warning(f"정말로 클라우드(구글 시트) 보관소에서 '{project_name}'을 삭제하시겠습니까?")
    st.write("이 작업은 구글 시트에서 데이터를 영구히 지우며, 다른 사용자도 더 이상 이 프로젝트를 볼 수 없습니다.")

    col1, col2 = st.columns(2)
    if col1.button("클라우드에서 완전히 삭제", width="stretch"):
        with st.spinner("클라우드 데이터를 삭제하는 중..."):
            res = db.delete_project_from_cloud(project_name)
            if res is True:
                st.success("클라우드 보관소에서 성공적으로 삭제되었습니다!")
                st.session_state.cloud_project_list = db.get_cloud_projects_list()
                st.rerun()
            else:
                st.error(f"삭제 실패: {res}")

    if col2.button("취소", width="stretch"):
        st.rerun()


if 'projects' not in st.session_state:
    st.session_state.projects = {
        "기본 프로젝트": pd.DataFrame(columns=["공종명", "구분", "단위", "단가", "수량", "합계", "시작일", "종료일"])
    }
    st.session_state.current_project = "기본 프로젝트"
    st.session_state.estimate_data = st.session_state.projects["기본 프로젝트"].copy()

if 'current_project' in st.session_state and 'estimate_data' in st.session_state:
    st.session_state.projects[st.session_state.current_project] = st.session_state.estimate_data.copy()

st.sidebar.subheader("📁 설계서 작성")
new_project = st.sidebar.text_input("새 프로젝트명 입력", placeholder="예: 포스코타워-송도 환경개선")
if st.sidebar.button("➕ 새 프로젝트 생성", width="stretch") and new_project:
    if new_project not in st.session_state.projects:
        st.session_state.projects[new_project] = pd.DataFrame(
            columns=["공종명", "구분", "단위", "단가", "수량", "합계", "시작일", "종료일"])
        st.session_state.current_project = new_project
        st.session_state.estimate_data = st.session_state.projects[new_project].copy()
        st.rerun()
    else:
        st.sidebar.warning("이미 존재하는 프로젝트입니다.")

project_list = list(st.session_state.projects.keys())
selected_project = st.sidebar.selectbox("현재 작업 중인 현장 선택", project_list,
                                        index=project_list.index(st.session_state.current_project))

if selected_project != st.session_state.current_project:
    st.session_state.current_project = selected_project
    st.session_state.estimate_data = st.session_state.projects[selected_project].copy()
    st.rerun()

if len(st.session_state.projects) > 1:
    if st.sidebar.button("🗑️ 현재 프로젝트 삭제", width="stretch"):
        delete_confirmation(st.session_state.current_project)
else:
    st.sidebar.button("🗑️ 현재 프로젝트 삭제", disabled=True, width="stretch", help="프로젝트가 1개일 때는 삭제할 수 없습니다.")

if "cloud_project_list" not in st.session_state:
    st.session_state.cloud_project_list = []

st.sidebar.divider()
st.sidebar.subheader("☁️ 클라우드 DB 보관소")

if st.sidebar.button("🔄 클라우드 목록 갱신/조회", width="stretch"):
    with st.spinner("구글 시트에서 프로젝트 목록을 불러오는 중..."):
        st.session_state.cloud_project_list = db.get_cloud_projects_list()
        if not st.session_state.cloud_project_list:
            st.sidebar.info("클라우드에 저장된 프로젝트가 없습니다.")
        else:
            st.sidebar.success(f"총 {len(st.session_state.cloud_project_list)}개의 프로젝트를 불러왔습니다!")

if st.session_state.cloud_project_list:
    project_options = {
        f"📂 {proj['name']} ({proj['date']})": proj['name']
        for proj in st.session_state.cloud_project_list
    }
    selected_option = st.sidebar.selectbox("불러올 프로젝트 선택", options=list(project_options.keys()))
    selected_project_name = project_options[selected_option]

    if st.sidebar.button("📥 선택한 프로젝트 불러오기", width="stretch"):
        with st.spinner(f"'{selected_project_name}' 데이터를 가져오는 중..."):
            loaded_df = load_project_from_cloud(selected_project_name)
            if loaded_df is None:
                st.sidebar.warning("해당 프로젝트의 데이터를 찾을 수 없습니다.")
            elif isinstance(loaded_df, str):
                st.sidebar.error(f"불러오기 실패: {loaded_df}")
            else:
                st.session_state.projects[selected_project_name] = loaded_df
                st.session_state.current_project = selected_project_name
                st.session_state.estimate_data = loaded_df.copy()
                st.sidebar.success(f"'{selected_project_name}' 로드 완료!")
                st.rerun()
            if st.sidebar.button("🗑️ 선택한 프로젝트 클라우드에서 삭제", width="stretch"):
                delete_cloud_confirmation(selected_project_name)
else:
    st.sidebar.info("👆 위 '목록 갱신/조회' 버튼을 눌러 프로젝트 목록을 확인하세요.")

if st.sidebar.button("💾 현재 프로젝트 클라우드에 저장", width="stretch"):
    with st.spinner("구글 시트에 안전하게 기록 중입니다..."):
        st.session_state.projects[st.session_state.current_project] = st.session_state.estimate_data.copy()
        res = save_project_to_cloud(st.session_state.current_project, st.session_state.estimate_data)
        if res is True:
            st.sidebar.success("클라우드 저장이 완료되었습니다!")
        else:
            st.sidebar.error(f"저장 실패: {res}")

st.sidebar.divider()

tab_dash, tab1, tab2, tab3 = st.tabs(["🏠 대시보드", "📝 설계 및 원가계산", "📊 자동 공정표", "⚙️ 기초 데이터 관리"])

with tab_dash:
    st.subheader(f"🏠 {st.session_state.current_project} 종합 대시보드")

    if st.session_state.estimate_data.empty:
        st.info("아직 추가된 내역이 없습니다. '설계 및 원가계산' 탭에서 데이터를 입력해 주세요.")
    else:
        df_dash = st.session_state.estimate_data.copy()
        df_dash["합계"] = pd.to_numeric(df_dash["합계"], errors="coerce").fillna(0)

        total_cost = df_dash["합계"].sum()
        mat_cost = df_dash[df_dash["구분"] == "자재"]["합계"].sum()
        labor_cost = df_dash[df_dash["구분"] == "노무"]["합계"].sum()
        equip_cost = df_dash[df_dash["구분"] == "장비"]["합계"].sum()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("총 직접공사비", f"{total_cost:,.0f} 원")
        c2.metric("자재비 총액", f"{mat_cost:,.0f} 원")
        c3.metric("노무비 총액", f"{labor_cost:,.0f} 원")
        c4.metric("장비비 총액", f"{equip_cost:,.0f} 원")

        st.divider()

        col_chart1, col_chart2 = st.columns(2)
        with col_chart1:
            st.markdown("**📊 자재/노무/장비 금액 비중**")
            fig_pie = px.pie(df_dash, values='합계', names='구분', hole=0.4,
                             color_discrete_sequence=px.colors.qualitative.Pastel)
            st.plotly_chart(fig_pie, width="stretch")

        with col_chart2:
            st.markdown("**📈 주요 공종별 투입 금액**")
            fig_bar = px.bar(df_dash, x='공종명', y='합계', color='구분', text_auto='.2s',
                             color_discrete_sequence=px.colors.qualitative.Pastel)
            st.plotly_chart(fig_bar, width="stretch")

with tab1:
    st.subheader("🔍 1. 자재 / 인건비 / 장비 / 세트 입력")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown("##### 🧱 자재")
        df_mat = db.get_filtered_master_items(category_large="자재비")
        mat_names = df_mat['item_name'].tolist() if not df_mat.empty else ["데이터 없음"]
        m_sel = st.selectbox("품목 선택", mat_names, key="mat_select")
        m_qty = st.number_input("수량", min_value=0.0, key="mat_qty")
        if st.button("자재 추가", key="mat_add"):
            u_price = db.get_unit_price(m_sel)
            new_row = pd.DataFrame({
                "공종명": [m_sel], "구분": ["자재"], "단위": ["식"],
                "단가": [u_price], "수량": [m_qty], "합계": [u_price * m_qty],
                "시작일": [date.today()], "종료일": [date.today()]
            })
            st.session_state.estimate_data = pd.concat([st.session_state.estimate_data, new_row], ignore_index=True)
            st.rerun()

    with col2:
        st.markdown("##### 👷 인건비")
        df_lab = db.get_filtered_master_items(category_large="인건비")
        lab_names = df_lab['item_name'].tolist() if not df_lab.empty else ["데이터 없음"]
        l_sel = st.selectbox("직종 선택", lab_names, key="lab_select")
        l_qty = st.number_input("인원", min_value=0.0, key="lab_qty")
        if st.button("인건비 추가", key="lab_add"):
            u_price = db.get_unit_price(l_sel)
            new_row = pd.DataFrame({
                "공종명": [l_sel], "구분": ["노무"], "단위": ["인"],
                "단가": [u_price], "수량": [l_qty], "합계": [u_price * l_qty],
                "시작일": [date.today()], "종료일": [date.today()]
            })
            st.session_state.estimate_data = pd.concat([st.session_state.estimate_data, new_row], ignore_index=True)
            st.rerun()

    with col3:
        st.markdown("##### 🏗️ 장비")
        df_eq = db.get_filtered_master_items(category_large="장비비")
        eq_names = df_eq['item_name'].tolist() if not df_eq.empty else ["데이터 없음"]
        e_sel = st.selectbox("장비 선택", eq_names, key="eq_select")
        e_qty = st.number_input("시간", min_value=0.0, key="eq_qty")
        if st.button("장비 추가", key="eq_add"):
            u_price = db.get_unit_price(e_sel)
            new_row = pd.DataFrame({
                "공종명": [e_sel], "구분": ["장비"], "단위": ["시간"],
                "단가": [u_price], "수량": [e_qty], "합계": [u_price * e_qty],
                "시작일": [date.today()], "종료일": [date.today()]
            })
            st.session_state.estimate_data = pd.concat([st.session_state.estimate_data, new_row], ignore_index=True)
            st.rerun()

    with col4:
        st.markdown("##### 📦 세트")
        df_set = db.get_filtered_master_items(category_large="세트")
        set_names = df_set['item_name'].tolist() if not df_set.empty else ["데이터 없음"]
        s_sel = st.selectbox("세트 선택", set_names, key="set_select")
        st.write("")
        st.write("")
        if st.button("세트 추가", key="set_add"):
            u_price = db.get_unit_price(s_sel)
            new_row = pd.DataFrame({
                "공종명": [s_sel], "구분": ["자재"], "단위": ["식"],
                "단가": [u_price], "수량": [1.0], "합계": [u_price * 1.0],
                "시작일": [date.today()], "종료일": [date.today()]
            })
            st.session_state.estimate_data = pd.concat([st.session_state.estimate_data, new_row], ignore_index=True)
            st.rerun()

    st.divider()

    st.subheader(f"📄 2. 세부 내역서 (을지) - {st.session_state.current_project}")
    st.info("💡 표 맨 왼쪽의 인덱스(번호) 부분을 클릭하여 체크한 후, 키보드의 'Delete' 키를 누르면 해당 항목이 삭제됩니다.")

    if not st.session_state.estimate_data.empty:
        for col in ["단가", "수량", "합계"]:
            if col in st.session_state.estimate_data.columns:
                st.session_state.estimate_data[col] = pd.to_numeric(st.session_state.estimate_data[col],
                                                                    errors='coerce').fillna(0)

        for col in ["시작일", "종료일"]:
            if col in st.session_state.estimate_data.columns:
                st.session_state.estimate_data[col] = pd.to_datetime(st.session_state.estimate_data[col],
                                                                     errors='coerce')

    edited_df = st.data_editor(
        st.session_state.estimate_data,
        num_rows="dynamic",
        column_config={
            "단위": st.column_config.SelectboxColumn("단위",
                                                   options=["일", "시간", "식", "m3", "ton", "EA", "인", "대", "포", "장"]),
            "단가": st.column_config.NumberColumn("단가(원)", format="%d ₩"),
            "수량": st.column_config.NumberColumn("수량 (소수점)", format="%.2f", step=0.1),
            "합계": st.column_config.NumberColumn("합계(원)", disabled=True),
            "시작일": st.column_config.DateColumn("시작일", format="YYYY-MM-DD"),
            "종료일": st.column_config.DateColumn("종료일", format="YYYY-MM-DD"),
        },
        width="stretch",
        hide_index=False
    )

    if not edited_df.empty:
        edited_df["단가"] = pd.to_numeric(edited_df["단가"], errors="coerce").fillna(0)
        edited_df["수량"] = pd.to_numeric(edited_df["수량"], errors="coerce").fillna(0)
        edited_df["합계"] = (edited_df["단가"] * edited_df["수량"]).astype(int)

        if not edited_df.equals(st.session_state.estimate_data):
            st.session_state.estimate_data = edited_df
            st.rerun()

    col_clear, col_blank = st.columns([1, 4])
    with col_clear:
        if st.button("🗑️ 현재 프로젝트 내역 전체 비우기"):
            st.session_state.estimate_data = pd.DataFrame(columns=["공종명", "구분", "단위", "단가", "수량", "합계", "시작일", "종료일"])
            st.rerun()

    st.divider()

    st.subheader("📊 3. 조달청 기준 원가계산서 (갑지 - 제비율 상세)")

    with st.expander("⚙️ 제비율(%) 설정 (클릭하여 수정 가능)", expanded=True):
        st.caption("조달청 건축공사 원가계산 간접공사비 적용기준에 따른 항목들입니다.")
        r1, r2, r3, r4 = st.columns(4)
        with r1:
            rate_indirect_labor = st.number_input("간접노무비율(%)", value=14.5, step=0.1)
            rate_sanjae = st.number_input("산재보험료율(%)", value=3.7, step=0.1)
            rate_goyong = st.number_input("고용보험료율(%)", value=1.15, step=0.1)
        with r2:
            rate_health = st.number_input("국민건강보험료율(%)", value=3.545, step=0.1)
            rate_elderly = st.number_input("노인장기요양보험료율(%)", value=12.95, step=0.1)
            rate_pension = st.number_input("국민연금보험료율(%)", value=4.5, step=0.1)
        with r3:
            rate_retire = st.number_input("퇴직공제부금비율(%)", value=2.31, step=0.1)
            rate_safety = st.number_input("산업안전보건비율(%)", value=1.86, step=0.1)
            rate_env = st.number_input("환경보전비율(%)", value=0.9, step=0.1)
        with r4:
            rate_etc_exp = st.number_input("기타경비율(%)", value=5.5, step=0.1)
            rate_general_admin = st.number_input("일반관리비율(%)", value=5.0, step=0.1)
            rate_profit = st.number_input("이윤율(%)", value=10.0, step=0.1)
            rate_tax = st.number_input("부가가치세율(%)", value=10.0, step=0.1)

    df_calc = st.session_state.estimate_data
    direct_material = df_calc[df_calc['구분'] == '자재']['합계'].sum() if not df_calc.empty else 0
    direct_labor = df_calc[df_calc['구분'] == '노무']['합계'].sum() if not df_calc.empty else 0
    equipment_exp = df_calc[df_calc['구분'] == '장비']['합계'].sum() if not df_calc.empty else 0
    direct_cost_total = direct_material + direct_labor + equipment_exp

    indirect_labor = int(direct_labor * (rate_indirect_labor / 100))
    total_labor = direct_labor + indirect_labor

    sanjae_ins = int(direct_labor * (rate_sanjae / 100))
    goyong_ins = int(direct_labor * (rate_goyong / 100))
    health_ins = int(direct_labor * (rate_health / 100))
    elderly_ins = int(health_ins * (rate_elderly / 100))
    pension_ins = int(direct_labor * (rate_pension / 100))
    retire_deduct = int(direct_labor * (rate_retire / 100))
    env_cost = int(direct_cost_total * (rate_env / 100))

    safety_base = int((direct_material + direct_labor) * (rate_safety / 100))
    temp_expense = equipment_exp + sanjae_ins + goyong_ins + health_ins + elderly_ins + pension_ins + retire_deduct + env_cost
    temp_etc = int((direct_material + total_labor) * (rate_etc_exp / 100))
    temp_net = direct_cost_total + indirect_labor + temp_expense + temp_etc
    temp_admin = int(temp_net * (rate_general_admin / 100))
    temp_supply = temp_net + temp_admin + int(
        (total_labor + temp_expense + temp_etc + temp_admin) * (rate_profit / 100))

    if temp_supply < 20000000:
        safety_mgt = 0
        safety_calc_reason = "총 공사금액 2천만 원 미만 제외"
    else:
        safety_mgt = safety_base
        safety_calc_reason = f"(재료비+직접노무비) × {rate_safety}%"

    etc_exp = int((direct_material + total_labor) * (rate_etc_exp / 100))
    total_expense = equipment_exp + sanjae_ins + goyong_ins + health_ins + elderly_ins + pension_ins + retire_deduct + safety_mgt + env_cost + etc_exp

    net_construction_cost = direct_material + total_labor + total_expense
    general_admin = int(net_construction_cost * (rate_general_admin / 100))
    profit = int((total_labor + total_expense + general_admin) * (rate_profit / 100))

    supply_value = net_construction_cost + general_admin + profit
    vat = int(supply_value * (rate_tax / 100))
    total_contract_price = supply_value + vat

    summary_data = [
        {"비목": "1. 재료비", "금액(원)": f"{direct_material:,}", "산출근거": "직접재료비 합계"},
        {"비목": " └ 직접재료비", "금액(원)": f"{direct_material:,}", "산출근거": "직접재료비 총액"},
        {"비목": "2. 노무비", "금액(원)": f"{total_labor:,}", "산출근거": "직접노무비 + 간접노무비"},
        {"비목": " └ 직접노무비", "금액(원)": f"{direct_labor:,}", "산출근거": "직접노무비 총액"},
        {"비목": " └ 간접노무비", "금액(원)": f"{indirect_labor:,}", "산출근거": f"직접노무비 × {rate_indirect_labor}%"},
        {"비목": "3. 경비", "금액(원)": f"{total_expense:,}", "산출근거": "기계경비 + 제보험료 + 제비용 + 기타경비"},
        {"비목": " └ 기계경비(장비비)", "금액(원)": f"{equipment_exp:,}", "산출근거": "기계경비 총액"},
        {"비목": " └ 산재보험료", "금액(원)": f"{sanjae_ins:,}", "산출근거": f"직접노무비 × {rate_sanjae}%"},
        {"비목": " └ 고용보험료", "금액(원)": f"{goyong_ins:,}", "산출근거": f"직접노무비 × {rate_goyong}%"},
        {"비목": " └ 국민건강보험료", "금액(원)": f"{health_ins:,}", "산출근거": f"직접노무비 × {rate_health}%"},
        {"비목": " └ 노인장기요양보험료", "금액(원)": f"{elderly_ins:,}", "산출근거": f"국민건강보험료 × {rate_elderly}%"},
        {"비목": " └ 국민연금보험료", "금액(원)": f"{pension_ins:,}", "산출근거": f"직접노무비 × {rate_pension}%"},
        {"비목": " └ 퇴직공제부금비", "금액(원)": f"{retire_deduct:,}", "산출근거": f"직접노무비 × {rate_retire}%"},
        {"비목": " └ 산업안전보건관리비", "금액(원)": f"{safety_mgt:,}", "산출근거": safety_calc_reason},
        {"비목": " └ 환경보전비", "금액(원)": f"{env_cost:,}", "산출근거": f"직접공사비 × {rate_env}%"},
        {"비목": " └ 기타경비", "금액(원)": f"{etc_exp:,}", "산출근거": f"(재료비+노무비) × {rate_etc_exp}%"},
        {"비목": "▶ 순공사원가 (1+2+3)", "금액(원)": f"{net_construction_cost:,}", "산출근거": "재료비 + 노무비 + 경비"},
        {"비목": "4. 일반관리비", "금액(원)": f"{general_admin:,}", "산출근거": f"순공사원가 × {rate_general_admin}%"},
        {"비목": "5. 이윤", "금액(원)": f"{profit:,}", "산출근거": f"(노무비+경비+일반관리비) × {rate_profit}%"},
        {"비목": "▶ 공급가액", "금액(원)": f"{supply_value:,}", "산출근거": "순공사원가 + 일반관리비 + 이윤"},
        {"비목": "6. 부가가치세", "금액(원)": f"{vat:,}", "산출근거": f"공급가액 × {rate_tax}%"},
        {"비목": "■ 총 공사예정금액(도급액)", "금액(원)": f"{total_contract_price:,}", "산출근거": "공급가액 + 부가가치세"},
    ]

    summary_df = pd.DataFrame(summary_data)

    st.dataframe(
        summary_df,
        width="stretch",
        hide_index=True,
        column_config={
            "비목": st.column_config.TextColumn("비목 (Category)", width="medium"),
            "금액(원)": st.column_config.TextColumn("금액(원)", width="small"),
            "산출근거": st.column_config.TextColumn("산출근거", width="large"),
        }
    )

    if not st.session_state.estimate_data.empty:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            st.session_state.estimate_data.to_excel(writer, sheet_name='세부내역서(을지)', index=False)
            summary_df.to_excel(writer, sheet_name='원가계산서(갑지)', index=False)
        st.download_button(label="📊 견적서 엑셀 다운로드 (.xlsx)", data=output.getvalue(),
                           file_name=f"{st.session_state.current_project}_견적서.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with tab2:
    st.subheader(f"📅 자동 공정표 - {st.session_state.current_project}")
    if not st.session_state.estimate_data.empty:
        df_gantt = st.session_state.estimate_data.copy()
        df_gantt['시작일'] = pd.to_datetime(df_gantt['시작일'], errors='coerce')
        df_gantt['종료일'] = pd.to_datetime(df_gantt['종료일'], errors='coerce')

        fig = px.timeline(df_gantt, x_start="시작일", x_end="종료일", y="공종명", color="구분", title="프로젝트 세부 공정표")
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, width="stretch")
    else:
        st.warning("먼저 '설계 및 원가계산' 탭에서 공종을 추가해 주세요.")

with tab3:
    st.subheader("⚙️ 기초 데이터 관리")

    # 1. 데이터 동기화 섹션
    st.markdown("### 1. 현재 데이터 동기화")
    st.info("💡 엑셀 파일('data/master_data.xlsx')의 내용을 서버 DB와 최신 상태로 동기화합니다.")
    if st.button("🔄 마스터 데이터 DB 동기화 실행", type="primary", use_container_width=True):
        excel_path = os.path.join("data", "master_data.xlsx")
        result = db.sync_master_data_from_excel(excel_path)
        if result["status"] == "success":
            st.success(result["message"])
        else:
            st.error(result["message"])

    st.divider()

    # 2. 데이터 확인 및 개별 관리 (추가/삭제)
    st.markdown("### 2. 동기화 데이터 확인 및 개별 관리")

    col_f1, col_f2 = st.columns([1, 3])
    with col_f1:
        cat_filter = st.selectbox("대분류 필터", ["전체", "인건비", "자재비", "장비비", "세트"])
    with col_f2:
        search_kw = st.text_input("항목명 또는 중분류 키워드 검색")

    df_master = db.get_filtered_master_items(category_large=cat_filter, search_keyword=search_kw)
    st.dataframe(df_master, width="stretch", hide_index=True)

    # 개별 추가/삭제 UI
    col_add, col_del = st.columns(2)
    with col_add:
        with st.expander("➕ 개별 항목 추가", expanded=False):
            with st.form("add_form", clear_on_submit=True):
                a_cat = st.selectbox("대분류", ["자재비", "인건비", "장비비", "세트"])
                a_mid = st.text_input("중분류")
                a_name = st.text_input("품목명")
                a_spec = st.text_input("규격")
                a_unit = st.text_input("단위")
                a_price = st.number_input("단가", min_value=0)
                a_src = st.text_input("출처")
                if st.form_submit_button("항목 추가"):
                    res = db.add_single_master_item(a_cat, a_mid, a_name, a_spec, a_unit, a_price, a_src)
                    if res["status"] == "success":
                        st.success("추가 완료!"); st.rerun()
                    else:
                        st.error(res["message"])

    with col_del:
        with st.expander("🗑️ 개별 항목 삭제", expanded=False):
            del_target = st.selectbox("삭제할 항목 선택",
                                      df_master['item_name'].tolist() if not df_master.empty else ["데이터 없음"])
            if st.button("선택 항목 삭제", type="primary"):
                res = db.delete_master_item(del_target)
                if res["status"] == "success":
                    st.success(res["message"]); st.rerun()
                else:
                    st.error(res["message"])

    st.divider()

    # 3. 대량 업로드
    st.markdown("### 3. 데이터 대량 업로드")
    st.markdown("엑셀 파일을 통해 한 번에 많은 데이터를 업데이트합니다.")

    # 엑셀 양식 다운로드 버튼
    template_df = pd.DataFrame(
        columns=["category_large", "category_mid", "item_name", "spec", "unit", "unit_price", "source"])
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        template_df.to_excel(writer, index=False)

    st.download_button("⬇️ 기본 양식 다운로드 (Excel)", data=output.getvalue(), file_name="master_template.xlsx",
                       mime="application/vnd.ms-excel")

    uploaded_file = st.file_uploader("작성된 엑셀 파일 업로드", type=["xlsx"])
    if uploaded_file and st.button("🚀 일괄 업로드 실행"):
        up_df = pd.read_excel(uploaded_file)
        res = db.upload_dataframe_to_master(up_df)
        if res["status"] == "success":
            st.success(res["message"]); st.rerun()
        else:
            st.error(res["message"])