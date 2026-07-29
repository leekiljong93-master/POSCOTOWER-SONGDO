import pandas as pd
import io

def calculate_cost_summary(df_calc, rates):
    """조달청 기준 원가계산서(갑지) 산출 순수 연산 로직"""
    direct_material = df_calc[df_calc['구분'] == '자재']['합계'].sum() if not df_calc.empty else 0
    direct_labor = df_calc[df_calc['구분'] == '노무']['합계'].sum() if not df_calc.empty else 0
    equipment_exp = df_calc[df_calc['구분'] == '장비']['합계'].sum() if not df_calc.empty else 0
    direct_cost_total = direct_material + direct_labor + equipment_exp

    indirect_labor = int(direct_labor * (rates['indirect_labor'] / 100))
    total_labor = direct_labor + indirect_labor

    sanjae_ins = int(direct_labor * (rates['sanjae'] / 100))
    goyong_ins = int(direct_labor * (rates['goyong'] / 100))
    health_ins = int(direct_labor * (rates['health'] / 100))
    elderly_ins = int(health_ins * (rates['elderly'] / 100))
    pension_ins = int(direct_labor * (rates['pension'] / 100))
    retire_deduct = int(direct_labor * (rates['retire'] / 100))
    env_cost = int(direct_cost_total * (rates['env'] / 100))
    safety_base = int((direct_material + direct_labor) * (rates['safety'] / 100))

    safety_mgt = 0 if direct_cost_total < 20000000 else safety_base
    safety_calc_reason = "총 공사금액 2천만 원 미만 제외" if direct_cost_total < 20000000 else f"(재료비+직접노무비) × {rates['safety']}%"

    etc_exp = int((direct_material + total_labor) * (rates['etc_exp'] / 100))
    total_expense = equipment_exp + sanjae_ins + goyong_ins + health_ins + elderly_ins + pension_ins + retire_deduct + safety_mgt + env_cost + etc_exp

    net_construction_cost = direct_material + total_labor + total_expense
    general_admin = int(net_construction_cost * (rates['general_admin'] / 100))
    profit = int((total_labor + total_expense + general_admin) * (rates['profit'] / 100))

    supply_value = net_construction_cost + general_admin + profit
    vat = int(supply_value * (rates['tax'] / 100))
    total_contract_price = supply_value + vat

    return [
        {"비목": "1. 재료비", "금액(원)": f"{direct_material:,}", "산출근거": "직접재료비 합계"},
        {"비목": " └ 직접재료비", "금액(원)": f"{direct_material:,}", "산출근거": "직접재료비 총액"},
        {"비목": "2. 노무비", "금액(원)": f"{total_labor:,}", "산출근거": "직접노무비 + 간접노무비"},
        {"비목": " └ 직접노무비", "금액(원)": f"{direct_labor:,}", "산출근거": "직접노무비 총액"},
        {"비목": " └ 간접노무비", "금액(원)": f"{indirect_labor:,}", "산출근거": f"직접노무비 × {rates['indirect_labor']}%"},
        {"비목": "3. 경비", "금액(원)": f"{total_expense:,}", "산출근거": "기계경비 + 제보험료 + 제비용 + 기타경비"},
        {"비목": " └ 기계경비(장비비)", "금액(원)": f"{equipment_exp:,}", "산출근거": "기계경비 총액"},
        {"비목": " └ 산재보험료", "금액(원)": f"{sanjae_ins:,}", "산출근거": f"직접노무비 × {rates['sanjae']}%"},
        {"비목": " └ 고용보험료", "금액(원)": f"{goyong_ins:,}", "산출근거": f"직접노무비 × {rates['goyong']}%"},
        {"비목": " └ 국민건강보험료", "금액(원)": f"{health_ins:,}", "산출근거": f"직접노무비 × {rates['health']}%"},
        {"비목": " └ 노인장기요양보험료", "금액(원)": f"{elderly_ins:,}", "산출근거": f"국민건강보험료 × {rates['elderly']}%"},
        {"비목": " └ 국민연금보험료", "금액(원)": f"{pension_ins:,}", "산출근거": f"직접노무비 × {rates['pension']}%"},
        {"비목": " └ 퇴직공제부금비", "금액(원)": f"{retire_deduct:,}", "산출근거": f"직접노무비 × {rates['retire']}%"},
        {"비목": " └ 산업안전보건관리비", "금액(원)": f"{safety_mgt:,}", "산출근거": safety_calc_reason},
        {"비목": " └ 환경보전비", "금액(원)": f"{env_cost:,}", "산출근거": f"직접공사비 × {rates['env']}%"},
        {"비목": " └ 기타경비", "금액(원)": f"{etc_exp:,}", "산출근거": f"(재료비+노무비) × {rates['etc_exp']}%"},
        {"비목": "▶ 순공사원가 (1+2+3)", "금액(원)": f"{net_construction_cost:,}", "산출근거": "재료비 + 노무비 + 경비"},
        {"비목": "4. 일반관리비", "금액(원)": f"{general_admin:,}", "산출근거": f"순공사원가 × {rates['general_admin']}%"},
        {"비목": "5. 이윤", "금액(원)": f"{profit:,}", "산출근거": f"(노무비+경비+일반관리비) × {rates['profit']}%"},
        {"비목": "▶ 공급가액", "금액(원)": f"{supply_value:,}", "산출근거": "순공사원가 + 일반관리비 + 이윤"},
        {"비목": "6. 부가가치세", "금액(원)": f"{vat:,}", "산출근거": f"공급가액 × {rates['tax']}%"},
        {"비목": "■ 총 공사예정금액(도급액)", "금액(원)": f"{total_contract_price:,}", "산출근거": "공급가액 + 부가가치세"},
    ]

def generate_excel_bytes(estimate_df, summary_df):
    """세부내역서와 원가계산서를 포함하는 엑셀 바이너리 생성"""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        estimate_df.to_excel(writer, sheet_name='세부내역서(을지)', index=False)
        summary_df.to_excel(writer, sheet_name='원가계산서(갑지)', index=False)
    return output.getvalue()
