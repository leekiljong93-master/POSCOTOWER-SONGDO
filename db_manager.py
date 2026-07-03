import sqlite3
import pandas as pd

DB_NAME = "design_system.db"


def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS labor_costs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, job_title TEXT UNIQUE, daily_wage REAL, updated_date TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS overhead_rates (
            id INTEGER PRIMARY KEY AUTOINCREMENT, rate_name TEXT UNIQUE, rate_value REAL, base_target TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS standard_estimates (
            id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT, item_name TEXT, spec TEXT, unit TEXT, 
            material_qty REAL, labor_qty REAL, expense_qty REAL)''')

    c.execute('''CREATE TABLE IF NOT EXISTS design_docs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, project_name TEXT, item_name TEXT, quantity REAL, 
            unit_price REAL, total_price REAL)''')

    conn.commit()
    conn.close()


def insert_massive_initial_data():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    today = "2026-07-03"

    # 1. 기초 노임단가 데이터
    labor_data = [
        ("보통인부", 165000), ("특별인부", 200000), ("조적공", 245000), ("건축목공", 255000),
        ("철근공", 260000), ("미장공", 250000), ("도장공", 230000), ("배관공", 240000)
    ]
    for job, wage in labor_data:
        c.execute("INSERT OR IGNORE INTO labor_costs (job_title, daily_wage, updated_date) VALUES (?, ?, ?)",
                  (job, wage, today))

    # 2. 제비율 데이터
    rate_data = [
        ("간접노무비", 0.145, "직접노무비"), ("산재보험료", 0.037, "직접노무비+간접노무비"),
        ("안전관리비", 0.0197, "직접공사비"), ("일반관리비", 0.06, "재료비+노무비+경비"), ("이윤", 0.15, "노무비+경비+일반관리비")
    ]
    for name, val, target in rate_data:
        c.execute("INSERT OR IGNORE INTO overhead_rates (rate_name, rate_value, base_target) VALUES (?, ?, ?)",
                  (name, val, target))

    # 3. 표준품셈 기초 데이터
    estimate_data = [
        ("토공사", "터파기(기계)", "백호 0.7m3", "m3", 0, 0.015, 0.12),
        ("토공사", "되메우기", "인력", "m3", 0, 0.25, 0),
        ("철근콘크리트", "레미콘 타설", "펌프카 사용", "m3", 1.02, 0.08, 0.15),
        ("조적공사", "시멘트벽돌쌓기", "1.0B", "m2", 149, 0.22, 0.02)
    ]
    for cat, item, spec, unit, mat, lab, exp in estimate_data:
        c.execute('''INSERT OR IGNORE INTO standard_estimates 
                  (category, item_name, spec, unit, material_qty, labor_qty, expense_qty) 
                  VALUES (?, ?, ?, ?, ?, ?, ?)''', (cat, item, spec, unit, mat, lab, exp))

    conn.commit()
    conn.close()


# 에러의 원인이었던 함수! DB에서 데이터를 DataFrame으로 읽어옵니다.
def get_table_data(table_name):
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
    conn.close()
    return df


# 파일 실행 시 자동 초기화 및 기초 데이터 삽입
init_db()
insert_massive_initial_data()