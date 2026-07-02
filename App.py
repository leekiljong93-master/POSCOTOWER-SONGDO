import streamlit as st
import pandas as pd
import sqlite3
import os
import io

st.set_page_config(page_title="공사비 산출 자동화 PRO", layout="wide")
st.title("🏗️ 공사비 산출 시스템 (PRO 버전)")

# --- [1] 내역서(장바구니) 메모리 공간 만들기 ---
if 'bill_of_quantities' not in st.session_state:
    st.session_state.bill_of_quantities = pd.DataFrame(columns=[
        "품목코드", "품명", "규격", "단위", "수량",
        "재료비단가", "노무비단가", "경비단가",
        "재료비합계", "노무비합계", "경비합계", "합계금액"
    ])


# DB 불러오기
def load_data():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(current_dir, "cost_data.db")
    conn = sqlite3.connect(db_path)
    query = "SELECT item_code, item_name, specification, unit, material_price, labor_price, expense_price FROM unit_prices"
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df


try:
    df_prices = load_data()
except:
    st.error("DB를 찾을 수 없습니다.")
    df_prices = pd.DataFrame()

# --- [1-2] 🚀 신규: 일위대가(세트 메뉴) 템플릿 임시 정의 ---
# 실무에서는 이 데이터도 DB로 빼지만, 지금은 프로그램 내부에 세트로 정의해둡니다.
ASSEMBLIES = {
    "기초 콘크리트 타설 (1m3 당)": [
        {"code": "MAT-001", "qty": 5.0},  # 시멘트 5포
        {"code": "LAB-001", "qty": 0.2},  # 인부 0.2명
        {"code": "EQU-001", "qty": 0.1}  # 장비 0.1시간
    ]
}

# --- [2] 검색 및 수량 입력 영역 ---
st.subheader("🔍 1. 자재/단가 및 일위대가 입력")

# 탭(Tab)을 나누어 단일 품목과 일위대가를 구분합니다.
tab1, tab2 = st.tabs(["개별 단가 검색", "일위대가(조립) 검색"])

# [탭 1: 개별 자재 추가]
with tab1:
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        item_list = df_prices['item_code'] + " | " + df_prices['item_name'] + " (" + df_prices['specification'] + ")"
        selected_item = st.selectbox("개별 항목을 선택하세요:", item_list)
    with col2:
        quantity = st.number_input("수량", min_value=0.1, value=1.0, step=0.1, key="single_qty")
    with col3:
        st.write("")
        st.write("")
        if st.button("➕ 개별 항목 추가"):
            code = selected_item.split(" | ")[0]
            item_data = df_prices[df_prices['item_code'] == code].iloc[0]

            new_row = pd.DataFrame([{
                "품목코드": item_data['item_code'], "품명": item_data['item_name'], "규격": item_data['specification'],
                "단위": item_data['unit'], "수량": quantity,
                "재료비단가": item_data['material_price'], "노무비단가": item_data['labor_price'],
                "경비단가": item_data['expense_price'],
                "재료비합계": int(item_data['material_price'] * quantity),
                "노무비합계": int(item_data['labor_price'] * quantity),
                "경비합계": int(item_data['expense_price'] * quantity),
                "합계금액": int(
                    (item_data['material_price'] + item_data['labor_price'] + item_data['expense_price']) * quantity)
            }])
            st.session_state.bill_of_quantities = pd.concat([st.session_state.bill_of_quantities, new_row],
                                                            ignore_index=True)
            st.success("추가 완료!")

# [탭 2: 일위대가(세트) 추가]
with tab2:
    col_a, col_b, col_c = st.columns([2, 1, 1])
    with col_a:
        selected_assembly = st.selectbox("일위대가(공종)를 선택하세요:", list(ASSEMBLIES.keys()))
    with col_b:
        assembly_qty = st.number_input("시공 수량 (m3, m2 등)", min_value=0.1, value=1.0, step=0.1, key="assy_qty")
    with col_c:
        st.write("")
        st.write("")
        if st.button("🚀 세트 일괄 추가"):
            items_to_add = ASSEMBLIES[selected_assembly]
            rows_list = []
            for item in items_to_add:
                code = item["code"]
                # 세트 기준수량 x 입력수량
                final_qty = item["qty"] * assembly_qty
                item_data = df_prices[df_prices['item_code'] == code].iloc[0]

                rows_list.append({
                    "품목코드": item_data['item_code'], "품명": f"[{selected_assembly}] " + item_data['item_name'],
                    "규격": item_data['specification'], "단위": item_data['unit'], "수량": final_qty,
                    "재료비단가": item_data['material_price'], "노무비단가": item_data['labor_price'],
                    "경비단가": item_data['expense_price'],
                    "재료비합계": int(item_data['material_price'] * final_qty),
                    "노무비합계": int(item_data['labor_price'] * final_qty),
                    "경비합계": int(item_data['expense_price'] * final_qty),
                    "합계금액": int((item_data['material_price'] + item_data['labor_price'] + item_data[
                        'expense_price']) * final_qty)
                })

            new_rows_df = pd.DataFrame(rows_list)
            st.session_state.bill_of_quantities = pd.concat([st.session_state.bill_of_quantities, new_rows_df],
                                                            ignore_index=True)
            st.success(f"{selected_assembly} ({assembly_qty}) 세트 추가 완료!")

# --- [3] 산출 내역서(을지) ---
st.divider()
st.subheader("📝 2. 세부 내역서 (을지)")

if not st.session_state.bill_of_quantities.empty:
    st.dataframe(st.session_state.bill_of_quantities, use_container_width=True)

    # 직접공사비 합계
    mat_sum = int(st.session_state.bill_of_quantities['재료비합계'].sum())
    lab_sum = int(st.session_state.bill_of_quantities['노무비합계'].sum())
    exp_sum = int(st.session_state.bill_of_quantities['경비합계'].sum())
    direct_cost_sum = mat_sum + lab_sum + exp_sum

    if st.button("🗑️ 내역서 비우기"):
        st.session_state.bill_of_quantities = st.session_state.bill_of_quantities.iloc[0:0]
        st.rerun()

    # --- [4] 🚀 신규: 원가계산서(갑지) 세부 제비율 적용 ---
    st.divider()
    st.subheader("📊 3. 원가계산서 (갑지 - 제비율 상세)")

    # 요율 설정
    c1, c2, c3, c4 = st.columns(4)
    rate_indirect_lab = c1.number_input("간접노무비율(%)", value=10.0, step=0.1)
    rate_sanjae = c2.number_input("산재보험료율(%)", value=3.8, step=0.1)
    rate_safety = c3.number_input("안전관리비율(%)", value=1.5, step=0.1)
    rate_profit = c4.number_input("이윤(%)", value=15.0, step=0.1)

    # 제비율 수식 계산 (실제 법정 방식 모사)
    indirect_lab = int(lab_sum * (rate_indirect_lab / 100))
    sanjae_ins = int((lab_sum + indirect_lab) * (rate_sanjae / 100))
    safety_cost = int((mat_sum + lab_sum) * (rate_safety / 100))
    profit = int((lab_sum + indirect_lab + exp_sum) * (rate_profit / 100))

    total_cost = direct_cost_sum + indirect_lab + sanjae_ins + safety_cost + profit

    # 갑지(원가계산서) 데이터프레임 만들기
    summary_data = {
        "비목": ["재료비", "직접노무비", "기계경비", "소계 (직접공사비)", "간접노무비", "산재보험료", "산업안전보건관리비", "이윤", "총 공사비"],
        "금액(원)": [mat_sum, lab_sum, exp_sum, direct_cost_sum, indirect_lab, sanjae_ins, safety_cost, profit, total_cost]
    }
    df_summary = pd.DataFrame(summary_data)

    # 화면에 갑지 요약본 보여주기
    st.table(df_summary.style.format({"금액(원)": "{:,.0f}"}))

    # --- [5] 🚀 신규: 갑지/을지 분리된 엑셀 다운로드 ---
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        # 첫 번째 시트: 원가계산서 (갑지)
        df_summary.to_excel(writer, index=False, sheet_name='원가계산서(갑지)')
        # 두 번째 시트: 내역서 (을지)
        st.session_state.bill_of_quantities.to_excel(writer, index=False, sheet_name='내역서(을지)')

    st.download_button(
        label="📥 프로페셔널 엑셀 내역서 다운로드 (갑지/을지 포함)",
        data=buffer.getvalue(),
        file_name="공사비_최종내역서_PRO.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary"
    )

else:
    st.info("아직 추가된 항목이 없습니다.")