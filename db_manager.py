import sqlite3
import pandas as pd
import os

DB_NAME = "design_system.db"


def init_db():
    # 파일이 없으면 자동으로 생성되고, 테이블이 없으면 생성됨
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS master_data 
                 (category_large TEXT, category_mid TEXT, item_name TEXT, 
                  spec TEXT, unit TEXT, unit_price REAL, source TEXT)''')
    conn.commit()
    conn.close()


def get_filtered_master_items(category_large="전체", search_keyword=""):
    conn = sqlite3.connect(DB_NAME)
    # 한글 컬럼명 대신 DB 테이블의 컬럼명으로 조회
    query = "SELECT * FROM master_data WHERE 1=1"

    if category_large != "전체":
        query += f" AND category_large = '{category_large}'"
    if search_keyword:
        query += f" AND item_name LIKE '%{search_keyword}%'"

    df = pd.read_sql_query(query, conn)
    conn.close()
    return df


def sync_master_data_from_excel(file_path):
    if not os.path.exists(file_path):
        return {"status": "error", "message": "엑셀 파일을 찾을 수 없습니다."}
    try:
        df = pd.read_excel(file_path)
        # 엑셀 헤더를 DB 테이블 컬럼명에 강제 매핑
        df.columns = ['category_large', 'category_mid', 'item_name', 'spec', 'unit', 'unit_price', 'source']

        conn = sqlite3.connect(DB_NAME)
        df.to_sql("master_data", conn, if_exists="replace", index=False)
        conn.close()
        return {"status": "success", "message": "데이터 동기화 완료!"}
    except Exception as e:
        return {"status": "error", "message": f"오류 발생: {str(e)}"}


def get_unit_price(item_name):
    conn = sqlite3.connect(DB_NAME)
    # item_name에 해당하는 단가를 가져오는 쿼리
    query = f"SELECT unit_price FROM master_data WHERE item_name = '{item_name}' LIMIT 1"
    df = pd.read_sql_query(query, conn)
    conn.close()
    return float(df['unit_price'][0]) if not df.empty else 0.0

init_db()