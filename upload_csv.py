import pandas as pd
import db_manager as db

# 1) CSV 파일 읽기 (같은 폴더에 "인건비_2026상반기.csv"를 저장해두세요)
df = pd.read_csv("인건비_2026상반기.csv", encoding="utf-8-sig")

# 2) unit_price가 빈 값(미조사 직종)인 행은 0으로 채우거나, 그대로 빈칸 유지하려면 문자열 처리
df["unit_price"] = df["unit_price"].fillna("")

print("업로드할 행 수:", len(df))
print(df.head())

# 3) 구글시트 '인건비' 탭에 업로드 (기존 데이터는 전부 지우고 새로 씀 - 주의!)
result = db.upload_dataframe_to_master(df, sheet_name="인건비")
print(result)
