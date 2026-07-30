# 포타송 설계서 작성

건설 프로젝트의 품목 단가 관리, 세부 내역서, 원가계산서, 공정표 및 엑셀 견적서 생성을 지원하는 Streamlit 앱입니다.

## 주요 기능

- 자재·노무·장비·세트 품목을 선택해 내역서 작성
- 품목별 규격, 단가, 수량 및 공정 기간 관리
- 조달청 기준 제비율을 입력한 원가계산서 생성
- 비용 구성 대시보드와 간트 공정표 제공
- Google Sheets 기반 마스터 품목·프로젝트 저장소
- Excel/CSV 기초 데이터 일괄 업로드 및 견적서 다운로드

## 실행 방법

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Google Sheets 설정

앱은 Google Sheets를 기초 데이터와 프로젝트 저장소로 사용합니다.

1. Google Cloud에서 서비스 계정을 만들고 Google Sheets 및 Drive API를 활성화합니다.
2. 서비스 계정에 대상 스프레드시트 편집 권한을 부여합니다.
3. 아래 둘 중 하나로 인증 정보를 설정합니다.

### Streamlit secrets 사용

`.streamlit/secrets.toml` 파일을 만들고 다음 값을 넣습니다. 이 파일은 Git에 올리지 마세요.

```toml
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/..."

[GOOGLE_CREDENTIALS]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n"
client_email = "..."
client_id = "..."
token_uri = "https://oauth2.googleapis.com/token"
```

### 로컬 서비스 계정 파일 사용

프로젝트 루트에 `service_account.json`을 두고, `.streamlit/secrets.toml`에는 `SPREADSHEET_URL`만 설정합니다.

## 데이터 보호

- **현재 프로젝트 삭제**는 현재 브라우저의 작업 목록에서만 제거합니다. Google Sheets에 저장된 프로젝트는 유지됩니다.
- 저장된 프로젝트를 영구적으로 삭제하려면 사이드바의 **클라우드에서 삭제**를 사용하세요.
- 마스터 데이터를 저장하기 전, 자재비·인건비·장비비·세트 시트의 스냅샷이 자동 생성됩니다.
- 기초 데이터 관리 탭의 **마스터 데이터 백업 및 복구**에서 최근 10개 백업 중 하나를 선택해 복구할 수 있습니다. 복구 전 현재 상태도 자동 백업됩니다.

## 주의

제비율과 원가계산 결과는 프로젝트 조건 및 적용 기준에 따라 달라질 수 있습니다. 계약·입찰에 사용하기 전 최신 기준과 산식은 반드시 검토하세요.
