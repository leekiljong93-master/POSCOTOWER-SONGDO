import pandas as pd

# 1. 조달청 CSV 파일 불러오기 (공공데이터는 보통 cp949 인코딩을 사용함)
# 파일 이름은 실제 다운받은 파일명으로 바꿔줘!
df = pd.read_csv('조달청_공사원가_정기자재단가_20250911.csv', encoding='cp949')

# 2. 우리 프로그램(DB) 양식에 맞춰서 새로운 데이터프레임 생성
df_mapped = pd.DataFrame({
    'category_large': df['공통자재구분'],
    'category_mid': df['공통자재구분'],  # 마땅한 중분류가 없어서 대분류로 퉁침!
    'item_name': df['자원명'],
    'spec': df['자원규격명'],
    'unit': df['단위'],
    'unit_price': df['재료비단가'],
    'source': '조달청_250911'  # 출처는 조달청으로 일괄 고정
})

# 3. 데이터 정제 (단가에 콤마가 섞여 있다면 빼고, 완벽한 숫자로 변환)
# 혹시 단가가 비어있는 행이 있다면 문자열 변환 시 에러가 날 수 있으니 결측치 먼저 제거
df_mapped = df_mapped.dropna(subset=['unit_price'])
df_mapped['unit_price'] = df_mapped['unit_price'].astype(str).str.replace(',', '').astype(float)

# 4. 쓸데없는 빈칸(결측치) 날려버리고 최종 엑셀로 저장
df_mapped = df_mapped.dropna(subset=['item_name'])
df_mapped.to_excel('최종_자재비_DB.xlsx', index=False)

print("🎉 수만 개의 조달청 데이터가 우리 DB 양식으로 완벽하게 변환되었어!")