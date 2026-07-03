import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import date, timedelta
import io

# import db_manager as db  # 실제 DB 연동 시 주석 해제

# 1. 페이지 설정 및 타이틀 (유지)
st.set_page_config(
    page_title="포타송 설계서 작성(Ver.260703)",
    page_icon="🏗️",
    layout="wide"
)
st.title("🏗️ 포타송 설계서 작성(Ver.260703)")

# --- 세션 상태(임시 저장소) 초기화 ---
if 'estimate_data' not in st.session_state:
    st.session_state.estimate_data = pd.DataFrame(columns=["공종명", "구분", "단가", "수량", "합계", "시작일", "종료일"])

# 화면을 3개의 탭으로 나눔
tab1, tab2, tab3 = st.tabs(["📝 설계 및 원가계산", "📊 자동 공정표", "⚙️ 기초 데이터(노임/세트) 관리"])

# ==========================================
# 탭 1: 설계 내역 및 원가계산서 (기능 통합 및 제비율 강화)
# ==========================================
with tab1:
    st.subheader("🔍 1. 자재/품셈 단가 및 세트 입력")

    col1, col2 = st.columns(2)
    # 개별 항목 추가
    with col1:
        st.markdown("**🔹 개별 항목 추가**")
        item_sel = st.selectbox("개별 항목을 선택하세요:", ["터파기(기계)", "보통인부", "시멘트", "굴삭기"])
        qty_sel = st.number_input("수량", min_value=1.0, value=1.0, step=1.0, key="qty1")
        if st.button("➕ 개별 항목 추가"):
            new_row = {"공종명": item_sel, "구분": "단일", "단가": 2475, "수량": qty_sel, "합계": 2475 * qty_sel,
                       "시작일": date.today(), "종료일": date.today() + timedelta(days=3)}
            st.session_state.estimate_data = pd.concat([st.session_state.estimate_data, pd.DataFrame([new_row])],
                                                       ignore_index=True)
            st.success(f"'{item_sel}' 추가 완료!")

    # 세트(일위대가) 일괄 추가
    with col2:
        st.markdown("**📦 세트(일위대가) 일괄 추가**")
        set_sel = st.selectbox("세트 공종을 선택하세요:", ["콘크리트 타설 세트", "거푸집 설치 세트", "비계 설치 세트"])
        set_qty = st.number_input("세트 수량(규모)", min_value=1.0, value=1.0, step=1.0, key="qty2")
        if st.button("➕ 세트 일괄 추가"):
            if set_sel == "콘크리트 타설 세트":
                set_items = [
                    {"공종명": "굴삭기(장비)", "구분": "장비", "단가": 500000, "수량": 1 * set_qty, "합계": 500000 * set_qty,
                     "시작일": date.today(), "종료일": date.today() + timedelta(days=2)},
                    {"공종명": "보통인부(노무)", "구분": "노무", "단가": 150000, "수량": 3 * set_qty, "합계": 450000 * set_qty,
                     "시작일": date.today(), "종료일": date.today() + timedelta(days=2)},
                    {"공종명": "시멘트(자재)", "구분": "자재", "단가": 50000, "수량": 10 * set_qty, "합계": 500000 * set_qty,
                     "시작일": date.today(), "종료일": date.today() + timedelta(days=2)}
                ]
                st.session_state.estimate_data = pd.concat([st.session_state.estimate_data, pd.DataFrame(set_items)],
                                                           ignore_index=True)
                st.success(f"'{set_sel}' 관련 하위 항목 자동 추가 완료!")

    st.divider()

    # 세부 내역서 (을지)
    st.subheader("📄 2. 세부 내역서 (을지)")
    st.dataframe(st.session_state.estimate_data, use_container_width=True)

    col_clear, col_blank = st.columns([1, 4])
    with col_clear:
        if st.button("🗑️ 현재 프로젝트 내역 전체 비우기"):
            st.session_state.estimate_data = pd.DataFrame(columns=["공종명", "구분", "단가", "수량", "합계", "시작일", "종료일"])
            st.rerun()

    st.divider()

    # 단단해진 제비율표 (갑지)
    st.subheader("📊 3. 원가계산서 (갑지 - 제비율 상세)")
    st.write("실무 기준에 맞춰 세분화된 제비율을 적용합니다. 비율을 수정하면 하단 금액이 실시간으로 변동됩니다.")

    # 제비율 입력(4열 배치로 깔끔하게)
    r1, r2, r3, r4 = st.columns(4)
    with r1:
        rate_indirect_labor = st.number_input("간접노무비율(%)", value=14.5, step=0.1)
        rate_health = st.number_input("국민건강보험료율(%)", value=3.4, step=0.1)
    with r2:
        rate_accident = st.number_input("산재보험료율(%)", value=3.7, step=0.1)
        rate_pension = st.number_input("국민연금보험료율(%)", value=4.5, step=0.1)
    with r3:
        rate_safety = st.number_input("안전관리비율(%)", value=1.97, step=0.1)
        rate_env = st.number_input("환경보전비율(%)", value=0.9, step=0.1)
    with r4:
        rate_profit = st.number_input("이윤율(%)", value=15.0, step=0.1)
        rate_tax = st.number_input("부가가치세율(%)", value=10.0, step=0.1)

    # 실시간 금액 계산 로직
    direct_cost = st.session_state.estimate_data['합계'].sum() if not st.session_state.estimate_data.empty else 0

    # 각 비목별 계산
    indirect_labor = int(direct_cost * (rate_indirect_labor / 100))
    health_ins = int(direct_cost * (rate_health / 100))
    accident_ins = int(direct_cost * (rate_accident / 100))
    pension_ins = int(direct_cost * (rate_pension / 100))
    safety_cost = int(direct_cost * (rate_safety / 100))
    env_cost = int(direct_cost * (rate_env / 100))

    pure_total = direct_cost + indirect_labor + health_ins + accident_ins + pension_ins + safety_cost + env_cost
    profit = int(pure_total * (rate_profit / 100))
    supply_value = pure_total + profit
    vat = int(supply_value * (rate_tax / 100))
    grand_total = supply_value + vat

    # 원가계산서 데이터프레임 생성
    summary_df = pd.DataFrame({
        "비목": ["직접공사비", "간접노무비", "산재보험료", "국민건강보험료", "국민연금보험료", "안전관리비", "환경보전비", "순공사원가", "이윤", "공급가액", "부가가치세",
               "총 원가 합계"],
        "금액(원)": [f"{direct_cost:,}", f"{indirect_labor:,}", f"{accident_ins:,}", f"{health_ins:,}", f"{pension_ins:,}",
                  f"{safety_cost:,}", f"{env_cost:,}", f"{pure_total:,}", f"{profit:,}", f"{supply_value:,}",
                  f"{vat:,}", f"{grand_total:,}"]
    })

    st.table(summary_df)

    # ==========================================
    # 🌟 엑셀 다운로드 (견적서 출력)
    # ==========================================
    st.markdown("### 📥 최종 내역서 다운로드")
    if not st.session_state.estimate_data.empty:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # 1번 시트: 세부내역서
            st.session_state.estimate_data.to_excel(writer, sheet_name='세부내역서(을지)', index=False)
            # 2번 시트: 원가계산서(갑지)
            summary_df.to_excel(writer, sheet_name='원가계산서(갑지)', index=False)

        st.download_button(
            label="📊 견적서 엑셀 다운로드 (.xlsx)",
            data=output.getvalue(),
            file_name="포타송_설계견적서.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.info("설계 내역을 추가하시면 엑셀 다운로드 버튼이 활성화됩니다.")

# ==========================================
# 탭 2: 자동 공정표 (Gantt Chart) - 유지됨
# ==========================================
with tab2:
    st.subheader("📅 세부 내역 기반 자동 공정표")
    st.info("💡 탭 1에서 추가한 내역을 바탕으로 공정표가 자동 생성됩니다.")

    if not st.session_state.estimate_data.empty:
        df_gantt = st.session_state.estimate_data.copy()
        df_gantt['시작일'] = pd.to_datetime(df_gantt['시작일'])
        df_gantt['종료일'] = pd.to_datetime(df_gantt['종료일'])

        fig = px.timeline(df_gantt, x_start="시작일", x_end="종료일", y="공종명", color="구분", title="프로젝트 세부 공정표")
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("먼저 '설계 및 원가계산' 탭에서 공종을 추가해 주세요.")

# ==========================================
# 탭 3: 기초 데이터 (노임/세트) 관리 및 일괄 업로드
# ==========================================
with tab3:
    st.subheader("⚙️ 기초 데이터 관리 및 일괄 업로드")
    st.write("단건 입력뿐만 아니라, 가지고 계신 방대한 엑셀 데이터를 한 번에 업로드할 수 있습니다.")

    # --- 🌟 1. 수동 단건 입력 (맨 위로 이동됨) ---
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("#### 👷 신규 노임단가 수동 등록")
        new_labor = st.text_input("직종명 (예: 보통인부, 철근공)")
        new_price = st.number_input("일 노임단가(원)", step=1000)
        if st.button("단건 DB에 저장"):
            st.success(f"{new_labor} 단가({new_price}원)가 등록되었습니다.")

    with col_b:
        st.markdown("#### 📦 신규 세트(일위대가) 수동 구성")
        set_name = st.text_input("세트명 (예: 철근 배근 세트)")
        st.write("포함될 하위 항목들을 선택 후 저장하세요.")
        if st.button("세트 DB에 저장"):
            st.success(f"'{set_name}' 세트 구성이 저장되었습니다.")

    st.divider()

    # --- 🌟 2. 사용법/주의사항 및 양식 다운로드 ---
    with st.expander("📢 [필독] 대량 업로드 사용법 및 주의사항", expanded=True):
        st.markdown("""
        **[ 📝 사용법 ]**
        1. 아래의 **'📥 업로드용 DB 양식 다운로드'** 버튼을 눌러 정해진 엑셀 템플릿을 받습니다.
        2. 다운받은 양식의 열(Column) 구조를 유지한 채, 보유하신 기초 데이터(표준품셈, 노임단가 등)를 복사하여 붙여넣습니다.
        3. 작성이 완료된 파일을 저장한 후, 아래 **'📁 기초 DB 엑셀 대량 업로드'** 영역에 드래그 앤 드롭합니다.

        **[ ⚠️ 주의사항 ]**
        - **열 이름 유지:** 첫 번째 행(헤더)의 이름(구분, 공종명, 단가 등)을 임의로 변경하거나 삭제하면 업로드 에러가 발생합니다.
        - **숫자 형식:** '단가' 입력 시 콤마(,)나 원(₩) 기호 없이 **오직 숫자만** 입력해 주세요. (예: 150,000원 ❌ ➔ 150000 ⭕)
        - **빈칸 주의:** 중간에 데이터가 없는 빈 행이 끼어있지 않도록 삭제 후 업로드해 주세요.
        """)

        # 엑셀 양식 데이터프레임 임시 생성
        template_df = pd.DataFrame({
            "구분": ["노무", "자재", "장비", "세트"],
            "공종명": ["보통인부", "시멘트(40kg)", "굴삭기(0.2m3)", "콘크리트 타설 세트"],
            "단가": [150000, 5000, 500000, 0],
            "단위": ["인", "포", "대", "식"],
            "비고": ["2026년 상반기 기준", "", "유류비 별도", "하위 항목 자동 연동"]
        })

        # 엑셀 파일로 변환하여 메모리에 저장
        output_template = io.BytesIO()
        with pd.ExcelWriter(output_template, engine='openpyxl') as writer:
            template_df.to_excel(writer, sheet_name='기초데이터_양식', index=False)

        st.download_button(
            label="📥 업로드용 DB 양식 다운로드 (.xlsx)",
            data=output_template.getvalue(),
            file_name="포타송_업로드양식.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    st.divider()

    # --- 🌟 3. 엑셀 일괄 업로드 기능 ---
    st.markdown("#### 📁 기초 DB 엑셀 대량 업로드 (Bulk Upload)")
    uploaded_file = st.file_uploader("표준품셈, 노임단가 등이 정리된 엑셀(.xlsx, .csv) 파일을 올려주세요.", type=["xlsx", "xls", "csv"])

    if uploaded_file is not None:
        try:
            if uploaded_file.name.endswith('.csv'):
                df_upload = pd.read_csv(uploaded_file)
            else:
                df_upload = pd.read_excel(uploaded_file)

            st.success(f"✅ {len(df_upload)}건의 데이터가 성공적으로 로드되었습니다. 아래 미리보기를 확인하세요.")
            st.dataframe(df_upload.head(10))  # 상위 10개만 미리보기

            if st.button("💾 DB에 일괄 저장"):
                # 실제로는 여기서 db.bulk_insert() 등의 함수를 호출합니다.
                st.balloons()
                st.success("데이터베이스에 성공적으로 일괄 등록되었습니다!")
        except Exception as e:
            st.error(f"파일을 읽는 중 오류가 발생했습니다: {e}")