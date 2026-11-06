# Google Cloud Console UI 메뉴 기반 단계별 구성 Guide (`No-Script / Console UI Walkthrough`)

본 문서는 별도의 `Python Script`나 로컬 개발 환경 설치 없이, **순수하게 `Google Cloud Console` 웹 메뉴(`UI`)를 클릭하여 `Gemini Enterprise (GE)` 및 `NotebookLM Enterprise`의 3계층 민감정보 보호(`SDP Content Policy` + `Model Armor` + `GCS` 사전 마스킹) 및 `BigQuery` 감사 로깅을 처음부터 끝까지 구성하는 단계별 매뉴얼**입니다.

---

## 한눈에 보는 `Google Cloud Console` 메뉴 구성 흐름도

```mermaid
flowchart TD
    classDef menu fill:#E8F0FE,stroke:#1A73E8,stroke-width:2px,color:#202124
    classDef security fill:#E6F4EA,stroke:#34A853,stroke-width:2px,color:#202124
    classDef ge fill:#FEF7E0,stroke:#FBBC04,stroke-width:2px,color:#202124
    classDef verify fill:#FCE8E6,stroke:#EA4335,stroke-width:2px,color:#202124

    M1["Step 1. IAM & Admin > IAM<br/>(Service Agent 권한 부여: roles/dlp.user, roles/bigquery.dataEditor)"]:::menu
    M2["Step 2. BigQuery > SQL Workspace<br/>(SDP 판정 감사 로그 저장용 Dataset 생성)"]:::menu
    M3["Step 3. Security > Sensitive Data Protection<br/>1) Inspect / De-identify Template 생성<br/>2) Content Policy 생성 (Fallback=Block, BigQuery 연동)"]:::security
    M4["Step 4. Security > Model Armor > Templates<br/>(SDP Filter + Prompt Injection Filter 활성화 Template 생성)"]:::security
    M5["Step 5. Gemini Enterprise > Security & Apps<br/>1) Security > Sensitive Data Protection configuration (Assistant & NotebookLM 연결)<br/>2) Apps > Configurations > Assistant (GE App Model Armor 연결)"]:::ge
    M6["Step 6. Cloud Storage & Sensitive Data Protection Jobs<br/>(Raw Bucket -> DLP De-identification Job -> Masked Bucket -> GE Data Store 연동)"]:::ge
    M7["Step 7. BigQuery & Logs Explorer<br/>(파일 Upload 차단 및 Chat 마스킹 감사 로그 확인)"]:::verify

    M1 --> M2 --> M3 --> M4 --> M5 --> M6 --> M7
```

> **[!IMPORTANT] `Console UI` 지원 범위 안내**
> - 아래 **전체 구성의 95% 이상**(`IAM`, `BigQuery`, `SDP Template`, `SDP Content Policy`, `GCS DLP De-identification Job`, `Model Armor Template`, `GE App Assistant 설정`, `NotebookLM Upload SDP 연결`)은 **`Google Cloud Console` 웹 메뉴만으로 100% 설정 가능**합니다.
> - 단, **`NotebookLM Enterprise`의 대화창(`Chat`)에 `Model Armor Template`을 바인딩하는 항목(`notebooklmConfig.modelArmorConfig`)**만 현재 `Google Cloud` 사양상 `Console UI` 메뉴가 제공되지 않으므로, `Step 5.3`에 안내된 것처럼 브라우저 우측 상단의 **`Cloud Shell` 아이콘(`>_`)을 눌러 명령어 1회만 붙여넣기**하면 모든 구성이 완결됩니다. **`[확인됨 / Verified: Screen prompts and responses using Model Armor in Gemini Notebook Enterprise]`**

---

## Step 1. `IAM & Admin` 메뉴에서 필수 `Service Agent` 권한 부여

`Gemini Enterprise`/`NotebookLM`이 `Sensitive Data Protection (SDP)` 정책을 실행한 뒤 판정 결과를 `BigQuery`에 기록할 수 있도록 2개의 기본 `Service Agent`에 권한을 부여합니다.

1. `Google Cloud Console` 좌측 탐색 메뉴(`☰`)에서 **`IAM & Admin` > `IAM`**으로 이동합니다.
2. 화면 우측 상단의 **`Include Google-provided role grants` (Google에서 제공하는 역할 부여 포함)** 체크박스를 **반드시 체크**합니다.
3. **1) `Discovery Engine Service Agent` 권한 추가**:
   - 목록에서 `service-{PROJECT_NUMBER}@gcp-sa-discoveryengine.iam.gserviceaccount.com` 계정을 찾아 우측 연필 아이콘(**`Edit principal`**)을 클릭합니다.
   - **`+ ADD ANOTHER ROLE`**을 클릭하고 **`DLP User`** (`roles/dlp.user`)를 검색하여 선택한 뒤 **`SAVE`**를 클릭합니다.
4. **2) `Cloud Data Loss Prevention Service Agent` 권한 추가 (`BigQuery` 로깅용)**:
   - 목록에서 `service-{PROJECT_NUMBER}@dlp-api.iam.gserviceaccount.com` 계정을 찾아 우측 연필 아이콘(**`Edit principal`**)을 클릭합니다.
   - **`+ ADD ANOTHER ROLE`**을 클릭하고 **`BigQuery Data Editor`** (`roles/bigquery.dataEditor`)를 선택한 뒤 **`SAVE`**를 클릭합니다.

---

## Step 2. `BigQuery` 메뉴에서 `SDP` 감사 로그용 `Dataset` 준비

`SDP Content Policy`가 파일을 스캔할 때마다 차단(`BLOCK`)/허용(`ALLOW`) 판정 이력을 자동 적재할 `BigQuery Dataset`을 생성합니다.

1. 좌측 메뉴(`☰`)에서 **`BigQuery` > `Studio` (`SQL Workspace`)**로 이동합니다.
2. `Explorer` 패널에서 현재 `Project ID` 우측의 점 3개(`⋮`) 아이콘을 클릭하고 **`Create dataset`**을 선택합니다.
3. 다음 항목을 입력하고 **`CREATE DATASET`**을 클릭합니다:
   - **`Dataset ID`**: `sdp_audit_logs`
   - **`Location type`**: **`Multi-region`** 선택 후 **`US (multiple regions in United States)`** 지정 *(참고: `SDP Content Policy`가 자동으로 하위 `Table`을 생성하거나 지정한 `Table`에 스트리밍 적재합니다.)*

---

## Step 3. `Security > Sensitive Data Protection` 메뉴에서 `Template` 및 `Content Policy` 생성

### 3.1 `Inspection Template` 및 `De-identification Template` 생성 (`Model Armor` 및 `GCS` 마스킹 연동용)
1. 좌측 메뉴(`☰`)에서 **`Security` > `Sensitive Data Protection`**으로 이동합니다.
2. 상단 탭에서 **`CONFIGURATION` > `Templates`** 탭을 클릭한 뒤 **`+ CREATE TEMPLATE`**을 클릭합니다.
3. **1) `Inspect Template` 생성**:
   - **`Template type`**: `Inspect` 선택
   - **`Template ID`**: `ge-notebooklm-inspect-tmpl`
   - **`Location type`**: **`Multi-region`** 또는 **`Global`** 중 보호 대상 `Gemini Enterprise`/`NotebookLM`의 `Location` (`global` 또는 `us`)과 **동일한 위치** 선택
   - **`Configure detection` (`InfoTypes`)**: **`MANAGE INFOTYPES`**를 클릭하여 다음 항목을 체크합니다:
     - `CREDIT_CARD_NUMBER` (신용카드 번호 — `Luhn Checksum` 검증 기반)
     - `KOREA_RRN` (대한민국 주민등록번호)
     - `PHONE_NUMBER` (전화번호)
   - **`Minimum likelihood`**: `Possible` 선택 후 **`CREATE`**를 클릭합니다.
4. **2) `De-identification Template` 생성**:
   - 다시 **`+ CREATE TEMPLATE`**을 클릭하고 **`Template type`**에서 `De-identify`를 선택합니다.
   - **`Template ID`**: `ge-notebooklm-deid-tmpl`, **`Location`**: 위와 동일하게(`global` 또는 `us`) 설정합니다.
   - **`Transformation`** 방식에서 **`InfoType` transformation**을 선택한 뒤 규칙(`Rule`)으로 **`Replace with InfoType name`** (예: 카드번호를 `[CREDIT_CARD_NUMBER]`로 치환) 또는 **`Mask with character`** (`*` 마스킹)를 지정해 **`CREATE`**를 클릭합니다.

### 3.2 `Content Policy` 생성 (`File Upload` 및 `Data Connector` 스캔용)
1. `Sensitive Data Protection` 화면 상단에서 **`CONFIGURATION` > `Content policies`** 탭을 클릭하고 **`+ CREATE POLICY`**를 클릭합니다.
2. **Step 1 (`Name policy`)**:
   - **`Policy ID`**: `ge-notebooklm-sdp-policy`
   - **`Region` (`Location`)**: 대상 `Gemini Enterprise` 및 `NotebookLM`이 위치한 **`global` 또는 `us`** 선택 *(중요: 반드시 실제 사용하는 `NotebookLM`의 `Location`과 일치해야 합니다!)*
3. **Step 2 (`Add rules`)**:
   - **`+ ADD RULE`**을 클릭합니다.
   - **`InfoTypes`**에서 `CREDIT_CARD_NUMBER`, `KOREA_RRN` 등을 선택하고 **`Minimum likelihood`**를 `Possible` (또는 `Likely`)로 설정합니다.
   - **`Action`**에서 **`Block`** (차단)을 선택합니다.
4. **Step 3 (`Specify fallback actions` — 대용량 파일 우회 방지 핵심 설정)**:
   - 기본값이 `Allow`로 되어 있는 예외 처리 항목을 다음과 같이 변경합니다:
     - **`Input exceeds the size limit` (`FALLBACK_ACTION_INPUT_TOO_LARGE`)**: **`Block`** 선택
     - **`Sensitive Data Protection error`**: **`Block`** 선택
     - **`Unsupported file type`**: 보안 정책에 따라 `Allow` 또는 `Block` 선택
5. **Step 4 (`Add logging`)**:
   - **`Log to BigQuery`** 토글을 활성화합니다.
   - **`Project ID`**, **`Dataset ID`** (`sdp_audit_logs`), **`Table ID`** (`content_policy_action_logs`)를 입력하고 **`CREATE`**를 클릭합니다.

---

## Step 4. `Security > Model Armor` 메뉴에서 `Template` 생성

`GE Assistant Chat`과 `NotebookLM Chat`에서 질문(`Prompt`), `GCS` 검색 문맥(`Grounded Context`), 답변(`Response`) 내 민감정보를 실시간 마스킹/차단할 `Model Armor Template`을 생성합니다.

1. 좌측 메뉴(`☰`)에서 **`Security` > `Model Armor`** (또는 상단 검색창에서 `Model Armor` 검색)로 이동합니다.
2. **`+ CREATE TEMPLATE`**을 클릭합니다.
3. 기본 정보를 입력합니다:
   - **`Template ID`**: `ge-notebooklm-armor-tmpl`
   - **`Region` (`Location`)**:
     - `GE Assistant`가 `global`인 경우 `global`에 1개 생성합니다.
     - **[필수 주의사항]** **`NotebookLM Enterprise`는 `NotebookLM` `Instance`가 `global`에 있더라도 반드시 `Multi-region > us` (또는 `eu`)에 생성된 `Model Armor Template`만 허용**합니다 (`locations/global` 템플릿을 `NotebookLM`에 연결하면 백엔드에서 `Allowed locations: [us, eu]` 예외가 발생하여 스캔이 무시됨). 따라서 **`us` (`Multi-region > US`)에도 동일한 이름(`ge-notebooklm-armor-tmpl`)으로 템플릿을 반드시 생성**해야 합니다 (사전에 `Step 3.1`의 `Inspect` / `De-identify Template`도 `us`에 함께 생성).
4. **`Filters` 구성**:
   - **`Prompt injection and jailbreak detection`**: 체크 활성화 (`Confidence level`: `Medium and above`)
   - **`Sensitive Data Protection (SDP)`**: 체크 활성화
     - **`Configuration mode`**: **`Advanced`** 선택
     - **`Inspect template`**: 해당 `Location`(`global` 또는 `us`)에 생성한 `projects/{PROJECT_ID}/locations/{LOCATION}/inspectTemplates/ge-notebooklm-inspect-tmpl` 입력
     - **`De-identify template`**: 해당 `Location`(`global` 또는 `us`)에 생성한 `projects/{PROJECT_ID}/locations/{LOCATION}/deidentifyTemplates/ge-notebooklm-deid-tmpl` 입력
5. **`Logging` 구성**:
   - 하단의 **`Log sanitize operations` (살균/검열 작업 로깅)** 체크박스를 활성화하고 **`CREATE`**를 클릭합니다.

---

## Step 5. `Gemini Enterprise` 메뉴에서 `GE App` 및 `NotebookLM`에 정책 연결

이제 생성한 `SDP Content Policy`와 `Model Armor Template`을 **`GE App`**과 **`NotebookLM Enterprise`** 양쪽 제어 계층에 각각 연결합니다.

| 설정 메뉴 위치 (`Console Navigation Path`) | 적용 대상 서비스 | 연결할 보안 리소스 | `Console UI` 지원 여부 |
| :--- | :--- | :--- | :---: |
| **`Gemini Enterprise` > `Security` > `Sensitive Data Protection configuration`** | 1) `GE Assistant` 첨부파일<br/>2) **`NotebookLM` 직접 `Upload` 파일** | `Step 3.2`의 `SDP Content Policy`<br/>(`ge-notebooklm-sdp-policy`) | **100% `UI` 지원** |
| **`Gemini Enterprise` > `Apps` > `[대상 App]` > `Configurations` > `Assistant`** | `GE Assistant Chat` (`Prompt`, `GCS` 검색 문맥, `Response`) | `Step 4`의 `Model Armor Template`<br/>(`locations/global` 또는 `us`) | **100% `UI` 지원** |
| **`Console` 우측 상단 `Cloud Shell` (`>_`) 1회 실행** | **`NotebookLM Chat` 및 요약** (`Prompt` & `Response`) | `Step 3.2` `SDP Policy` + `Step 4` `Model Armor Template` (**`locations/us` 필수**) | `Cloud Shell` 1줄 실행 |

### 5.1 `Console UI`에서 `Assistant` 및 `NotebookLM` 업로드용 `SDP Content Policy` 연결
1. 좌측 메뉴(`☰`)에서 **`Gemini Enterprise` (또는 `AI Applications` / `Agentspace`) > `Security`** 메뉴로 이동합니다.
2. **`Sensitive Data Protection configuration`** 탭을 선택해 주세요.
3. 상단 **`Region`** 드롭다운에서 사용 중인 `Location` (**`global`** 및 **`us`**)을 각각 선택하여 아래 설정을 적용합니다.
4. **1) `Assistant setting` 섹션**:
   - **`Edit`**를 클릭하고 `Step 3.2`에서 생성한 `ge-notebooklm-sdp-policy`를 선택하여 저장합니다.
5. **2) `NotebookLM setting` 섹션 (핵심!)**:
   - 하단 `NotebookLM setting`의 **`Edit`**를 클릭합니다.
   - **`Enable Sensitive Data Protection for uploads`** 체크박스를 **반드시 체크**해야 합니다.
   - 드롭다운에서 `ge-notebooklm-sdp-policy`를 선택하고 **`Save`**를 클릭합니다.

### 5.2 `Console UI`에서 `GE App`에 `Model Armor Template` 연결
1. **`Gemini Enterprise` > `Apps`**로 이동하여 사용 중인 `GE App`을 클릭합니다.
2. 좌측 하위 메뉴에서 **`Configurations` > `Assistant`** 탭으로 이동해 주세요.
3. **`Model Armor`** 설정 영역에서 **`Edit`**를 클릭합니다.
4. **`Prompt template`** 및 **`Response template`** 드롭다운에서 `Step 4`에서 생성한 `ge-notebooklm-armor-tmpl`을 선택하고 **`Save`**를 클릭합니다.

### 5.3 `NotebookLM`에 `SDP Policy` 및 `us` `Model Armor Template` 동시 바인딩 (`Console` 내 `Cloud Shell` 1회 실행)
`NotebookLM Enterprise`에서 `SDP Policy`와 `Model Armor`가 누락 없이 동작하도록 하려면, `Google Cloud Console` 우측 상단의 **`Activate Cloud Shell` (`>_`)** 버튼을 클릭하고 아래 명령어를 복사해 붙여넣어 주세요.

> **[!IMPORTANT] `NotebookLM` `projects.patch` 호출 시 필수 주의사항 2가지**
> 1. **`failureMode` 필드 제외 필수**: `GE Assistant`와 달리 `notebooklmConfig.modelArmorConfig` 스키마는 `userPromptTemplate`과 `responseTemplate`만 지원하며 `"failureMode"` 필드를 지원하지 않습니다. `"failureMode": "FAIL_CLOSED"`를 포함하면 `HTTP 400 Invalid JSON payload received. Unknown name "failureMode"` 오류가 발생하여 **`SDP Policy`를 포함한 전체 설정이 거부(`{}`)**됩니다.
> 2. **`Model Armor Template`은 반드시 `locations/us` (또는 `eu`) 경로 지정**: `NotebookLM`이 `global`에 배포되어 있더라도 `modelArmorConfig`의 템플릿 경로는 반드시 `projects/${PROJECT_ID}/locations/us/templates/ge-notebooklm-armor-tmpl`을 지정해야 합니다.

```bash
export PROJECT_ID=$(gcloud config get-value project)
export PROJECT_NUMBER=$(gcloud projects describe ${PROJECT_ID} --format="value(projectNumber)")

# global 및 us 양쪽 Location 모두에 안전하게 바인딩
for LOC in global us; do
  if [ "${LOC}" = "global" ]; then
    API_ENDPOINT="https://discoveryengine.googleapis.com"
  else
    API_ENDPOINT="https://${LOC}-discoveryengine.googleapis.com"
  fi

  curl -s -X PATCH \
    -H "Authorization: Bearer $(gcloud auth print-access-token)" \
    -H "Content-Type: application/json" \
    -H "X-Goog-User-Project: ${PROJECT_ID}" \
    "${API_ENDPOINT}/v1alpha/projects/${PROJECT_NUMBER}?update_mask=customerProvidedConfig.notebooklmConfig" \
    -d "{
      \"customerProvidedConfig\": {
        \"notebooklmConfig\": {
          \"dataProtectionPolicy\": {
            \"sensitiveDataProtectionPolicy\": {
              \"policy\": \"projects/${PROJECT_ID}/locations/${LOC}/contentPolicies/ge-notebooklm-sdp-policy\"
            }
          },
          \"modelArmorConfig\": {
            \"userPromptTemplate\": \"projects/${PROJECT_ID}/locations/us/templates/ge-notebooklm-armor-tmpl\",
            \"responseTemplate\": \"projects/${PROJECT_ID}/locations/us/templates/ge-notebooklm-armor-tmpl\"
          }
        }
      }
    }" | jq .
done
```

> **[!NOTE] 설정 반영 대기 시간 (최대 10분)**
> `NotebookLM Enterprise`에 정책을 연결한 직후에는 백엔드 설정 캐시(`CustomerConfigurationCache`)가 갱신되기까지 **최대 10분**이 소요될 수 있습니다. 아래 `Step 6`을 구성한 뒤 테스트를 진행하면 자연스럽게 캐시 갱신 시간이 경과합니다.

---

## Step 6. `Cloud Storage` 및 `Sensitive Data Protection Job` 메뉴로 `GCS` 사전 마스킹 구성

`NotebookLM`에서 `"Add content to..."`로 `GCS Data Store` 문서를 가져올 때 민감정보가 노출되지 않도록, `Console UI`의 **무코드(`No-Code`) `DLP De-identification Job`**을 사용하여 마스킹된 버킷을 구성합니다.

1. **`Cloud Storage` > `Buckets`**로 이동하여 두 개의 `Bucket`을 생성합니다:
   - 원본 스테이징 버킷 (`Raw Bucket`): `<PROJECT_ID>-ge-sdp-raw-docs` (여기에 샘플 파일인 `sample_data/vip_customer_claim_raw.txt` 및 `store_operation_policy_clean.txt` 업로드)
   - 마스킹 완료 버킷 (`Masked Bucket`): `<PROJECT_ID>-ge-sdp-masked-docs` (`GE Data Store`에 실제로 연결할 버킷)
2. **`Security` > `Sensitive Data Protection`**으로 이동하여 상단 **`INSPECTION` > `Jobs and job triggers`** 탭을 클릭하고 **`+ CREATE JOB OR TRIGGER`**를 선택해 주세요.
3. **`Choose input data`**:
   - **`Storage type`**: `Cloud Storage` 선택
   - **`Include URL`**: `gs://<PROJECT_ID>-ge-sdp-raw-docs/` 지정
4. **`Configure detection`**:
   - **`Inspection template`**: `Step 3.1`에서 만든 `ge-notebooklm-inspect-tmpl` 선택
5. **`Add actions` (`Make a de-identified copy` 활성화)**:
   - **`Make a de-identified copy`** (비식별화된 사본 만들기) 토글을 **ON**으로 켭니다.
   - **`Cloud Storage output bucket`**: `gs://<PROJECT_ID>-ge-sdp-masked-docs` 입력
   - **`Default transformation template`**: `Step 3.1`에서 만든 `ge-notebooklm-deid-tmpl` 입력
   - **`File types to transform`**: `TEXT_FILE` 등 대상 파일 유형 선택 후 **`CREATE`**를 클릭하여 작업을 실행합니다.
6. 작업이 완료되면 `gs://<PROJECT_ID>-ge-sdp-masked-docs` 버킷에 신용카드 번호(`4532-0151-1283-0366`)와 주민번호가 `[CREDIT_CARD_NUMBER]`, `[KOREA_RRN]`으로 마스킹된 사본 파일이 자동 생성됩니다.
7. **`Gemini Enterprise` > `Data Stores`** 메뉴에서 `GCS Data Store`의 소스 경로를 `gs://<PROJECT_ID>-ge-sdp-masked-docs`로 연결(또는 `Sync` 실행)해 주세요.

---

## Step 7. `Console UI`에서 차단 동작 및 감사 로그(`Audit Logs`) 검증

### 7.1 `NotebookLM Enterprise UI` 및 `GE Assistant Chat` 테스트
1. **`NotebookLM` 직접 `Upload` 차단 확인**:
   - `NotebookLM Enterprise` 웹 화면에서 새 `Notebook`을 열고 **`+ Add source`**를 클릭합니다.
   - 유효한 `Luhn Checksum` 신용카드 번호가 포함된 로컬 문서(`vip_customer_claim_raw.txt` 또는 `.pdf`)를 업로드하면 **`SDP Content Policy`에 의해 업로드가 차단(`BLOCK`)**됩니다.
   - 반면 민감정보가 없는 `store_operation_policy_clean.txt`를 업로드하면 정상적으로 추가(`ALLOW`)됩니다.
2. **`GCS` `"Add content to..."` 및 `Chat` 보호 확인**:
   - `GE` 검색 결과에서 `GCS Data Store` 문서를 `"Add content to..."`로 `NotebookLM`에 가져오면 이미 `[CREDIT_CARD_NUMBER]`로 마스킹된 안전한 본문만 유입됩니다.
   - 또한 `NotebookLM Chat`이나 `GE Assistant Chat`에 직접 카드번호(`4532-0151-1283-0366`)를 입력하여 질문하면 `Model Armor`가 실시간으로 탐지·마스킹합니다.

### 7.2 `BigQuery Studio`에서 `SDP Content Policy` 판정 로그 확인
1. **`BigQuery` > `Studio`**로 이동하여 **`+ SQL query`** 버튼을 클릭합니다.
2. 아래 `SQL Query`를 붙여넣고 **`RUN`**을 클릭하면 파일별 `BLOCK` / `ALLOW` 판정 결과와 탐지된 `InfoType` (`CREDIT_CARD_NUMBER`, `KOREA_RRN`)이 즉시 조회됩니다:
   ```sql
   SELECT
     timestamp,
     returned_verdict,
     matching_info_types,
     policy_rule,
     fallback_action,
     document_id,
     container_id,
     correlation_id
   FROM
     `<PROJECT_ID>.sdp_audit_logs.content_policy_action_logs`
   ORDER BY
     timestamp DESC
   LIMIT 20;
   ```

### 7.3 `Logging > Logs Explorer`에서 `Model Armor` 실행 로그 확인
1. 좌측 메뉴(`☰`)에서 **`Logging` > `Logs Explorer`**로 이동합니다.
2. 쿼리 입력창에 아래 필터를 입력하고 **`Run query`**를 클릭하면 `GE Chat` 및 `NotebookLM Chat`에서 수행된 실시간 `Prompt`/`Response` 스캔 내역이 조회됩니다:
   ```text
   resource.type="modelarmor.googleapis.com/Template"
   ```

---

## 8. 개인 `PC` 저장 문서 `Upload` 시 `SDP` 미작동 원인 분석 및 조치 `Guide`

가이드에 따라 설정을 완료했음에도 개인 `PC`에 저장된 문서(`File`)를 `NotebookLM Enterprise`에 `Upload`할 때 `SDP` 차단이 작동하지 않는 경우, 아래 핵심 원인을 점검해 즉시 격리하고 조치할 수 있습니다.

### 8.1 파일 `Format`(`.txt`/`.md` vs `.pdf`/`.docx`/`.pptx`/`.xlsx`)별 `Backend` 스캔 경로 차이 (`[확인됨 / Verified]`)
`NotebookLM Enterprise`의 `Source Upload` `Pipeline`은 내부적으로 **1차 `Blobstore Queue Receiver`(`ProcessingQueueReceiver`)**와 **2차 `Orchestration Server`(`AddSourcesAction`)**의 2단계로 구성되어 있습니다.
- **`.txt`, `.md` 파일 및 `Copied Text` (`Text` 기반 `Source`)**:
  - 2차 관문의 텍스트 콘텐츠 검사 조건이 충족되어 텍스트 단위로 즉시 `SDP` 검사 및 차단이 수행됩니다.
- **`.pdf`, `.docx`, `.pptx`, `.xlsx` 파일 (`Document` / `Multimodal` 기반 `Source`)**:
  - `Document` / `Multimodal` 객체로 변환되어 2차 관문으로 전달되므로, 1차 관문(`Byte` 단위 `DlpService.ApplyContentPolicy` 호출)에서만 검사됩니다.
  - **조치 방안**:
    1. **검증 분리**: 동일한 민감정보가 포함된 **`.txt` 파일(또는 `Copied Text`)**과 **`.pdf`/`.docx` 파일**을 각각 `Upload`하여 `.txt`는 차단되고 `.pdf`/`.docx`만 통과하는지 비교합니다.
    2. **`Model Armor` 동시 바인딩 (필수 다계층 방어)**: `.pdf`/`.docx` 파일이 1차 `Upload` 관문을 통과하더라도, `NotebookLM`에 **`locations/us` `Model Armor Template`(`userPromptTemplate` / `responseTemplate`, `SDP Filter` 활성화)**을 함께 바인딩하면 문서 인덱싱 직후 자동 생성되는 `Notebook Guide`/요약 및 사용자 `Chat` 질의응답 시점에 `Model Armor`가 작동해 민감정보 노출을 차단합니다.

### 8.2 `API Payload` 필드명 오류(`sdpPolicy` vs `policy`) 및 덮어쓰기(`Overwrite`) 현상
- `Console UI`에서 `NotebookLM` `SDP`를 설정한 뒤, `projects.patch` `API`를 호출할 때 `sensitiveDataProtectionPolicy` 하위 필드명을 `"policy"`가 아닌 `"sdpPolicy"`로 전달했거나 `modelArmorConfig`만 포함하여 호출하면 기존 `policy` 값이 빈 문자열(`""`)로 초기화됩니다.
- **확인 및 조치 명령**:
  ```bash
  # 현재 프로젝트에 실제 저장된 notebooklmConfig 조회 (Location이 us인 경우 us-discoveryengine.googleapis.com 사용)
  curl -s -X GET \
    -H "Authorization: Bearer $(gcloud auth print-access-token)" \
    "https://discoveryengine.googleapis.com/v1alpha/projects/${PROJECT_NUMBER}" | jq '.customerProvidedConfig.notebooklmConfig'
  ```
  출력 결과에서 `dataProtectionPolicy.sensitiveDataProtectionPolicy.policy` 값이 `"projects/.../locations/.../contentPolicies/..."` 형태로 정확히 들어있는지 확인한 뒤 비어 있다면 `make apply-policy` 또는 `Console UI`에서 재저장합니다.

### 8.3 `Location` (`global` vs `us` / `eu`) 불일치
- `NotebookLM Enterprise`는 **`Notebook`이 생성된 `Location`과 동일한 `Location`의 `Customer` 설정(`notebooklmConfig`)**만 참조합니다.
- `Policy`는 `global`에 바인딩했으나 실제 `NotebookLM` `Instance`가 `us` `Multi-Region`(또는 그 반대)에 생성된 경우 정책이 적용되지 않으므로 두 `Location`이 일치하는지 확인해야 합니다.

### 8.4 테스트 문서 내 민감정보 데이터 형식 (`Luhn Checksum` 및 `Likelihood` 조건)
- **`CREDIT_CARD_NUMBER` (`Luhn Checksum` 검증)**: `1234-5678-1234-5678`과 같이 `Luhn` 알고리즘을 만족하지 않는 임의의 16자리 숫자는 `SDP`가 신용카드 번호로 탐지하지 않습니다. 반드시 유효한 테스트 번호(예: `4532-0151-1283-0366`)를 포함해야 합니다.
- **한글 문서 내 `KOREA_RRN` 및 주변 `Context`**: 주민등록번호(`880101-1234567`) 단독 기재 시 `Likelihood`가 `POSSIBLE`로 평가될 수 있으므로, `Content Policy`의 `Minimum Likelihood`를 `POSSIBLE`로 낮추거나 `'주민등록번호'`, `'RRN'` 등 주변 `Context` 단어를 함께 기재해 테스트합니다.
- **스캔 이미지(`Image-only PDF`)**: 텍스트 레이어 없이 통짜 이미지로 스캔된 `PDF`는 `OCR` 전 바이트 스트림에서 정규식/사전 매칭이 일어나지 않을 수 있으므로 텍스트 선택(드래그)이 가능한 문서로 테스트합니다.

### 8.5 서버 설정 `Cache` 전파 지연 (`b/564947655`)
- `NotebookLM` 서버는 프로젝트의 `notebooklmConfig`를 인메모리 `Cache`에 보관합니다.
- 특히 `SDP Policy`를 연결하기 전에 이미 해당 프로젝트에서 `NotebookLM`을 호출한 적이 있는 경우, 기존 서버가 빈 정책(`policy: ""`)을 캐시하고 있을 수 있습니다 (`b/564947655`).

---

## 9. `.txt` 파일조차 차단되지 않을 때 고객 환경 즉시 실행 4단계 조치 `Guide`

고객 환경에서 `.pdf`/`.docx`뿐만 아니라 **일반 텍스트(`File` `Format`: `.txt`)조차 차단되지 않는 경우**, 아래 **Step 1부터 Step 4까지** 순서대로 실행하여 원인을 격리하고 조치합니다.

### Step 1. 현재 `notebooklmConfig` 바인딩 상태 진단 (`global` & `us` 동시 조회)
`Step 5.3` 또는 이전 스크립트로 `projects.patch` 호출 시 `notebooklmConfig.modelArmorConfig` 내부에 `"failureMode": "FAIL_CLOSED"`가 포함되어 있었다면, `API`가 `HTTP 400 Unknown name "failureMode"` 오류로 요청 전체를 거부해 `SDP Policy`까지 빈 상태(`{}`)로 남게 됩니다.

`Cloud Shell`에서 아래 명령어로 `global`과 `us` 양쪽의 실제 저장 상태를 조회합니다:
```bash
export PROJECT_ID=$(gcloud config get-value project)
export PROJECT_NUMBER=$(gcloud projects describe ${PROJECT_ID} --format="value(projectNumber)")

echo "=== [1] global Location에 저장된 notebooklmConfig ==="
curl -s -X GET -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "X-Goog-User-Project: ${PROJECT_ID}" \
  "https://discoveryengine.googleapis.com/v1alpha/projects/${PROJECT_NUMBER}" \
  | jq '.customerProvidedConfig.notebooklmConfig'

echo "=== [2] us Location에 저장된 notebooklmConfig ==="
curl -s -X GET -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "X-Goog-User-Project: ${PROJECT_ID}" \
  "https://us-discoveryengine.googleapis.com/v1alpha/projects/${PROJECT_NUMBER}" \
  | jq '.customerProvidedConfig.notebooklmConfig'
```
- **조치**: 출력 결과가 `null`이거나 `policy` 필드가 비어 있다면, 최신 `Repository`에서 `git pull` 후 `make apply-policy`를 실행하거나 위 **`Step 5.3`의 표준 `curl` 명령(`failureMode` 제거본)**을 실행해 `global`과 `us` 양쪽에 모두 바인딩합니다.

### Step 2. `SDP Content Policy` 자체 판정(`Verdict`) 단독 검증
`Console UI`에서 `Content Policy` 생성 시 기본값인 **`Allow (Alert only)`**가 선택되어 있으면 `.txt` 파일도 차단되지 않고 허용(`ALLOW`)됩니다. 아래 명령어로 `DLP API`에 직접 `.txt` 샘플 `Payload`를 보내 **`"verdict": "BLOCK"`**이 반환되는지 확인합니다:
```bash
curl -s -X POST \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  -H "X-Goog-User-Project: ${PROJECT_ID}" \
  "https://dlp.googleapis.com/v2/projects/${PROJECT_ID}/locations/global:applyContentPolicy" \
  -d "{
    \"contentPolicyName\": \"projects/${PROJECT_ID}/locations/global/contentPolicies/ge-notebooklm-sdp-policy\",
    \"byteContentItem\": {
      \"type\": \"TEXT_UTF8\",
      \"data\": \"$(echo -n 'VIP 고객 카드번호: 4532-0151-1283-0366, 주민번호: 880101-1234567' | base64 -w 0)\"
    }
  }" | jq .
```
- **조치**:
  - 만약 `"verdict": "ALLOW"`가 출력된다면 **`Security > Sensitive Data Protection > Configurations > Policy`** 메뉴에서 `ge-notebooklm-sdp-policy`를 열어 **`Determine verdict`**를 **`Block`**으로 변경하고 **`Fallback action`**도 **`Block`**으로 지정한 뒤 저장합니다.
  - **`"verdict": "BLOCK"`**이 출력된다면 고객사의 `SDP Content Policy`와 `Template` 구성은 정상입니다.

### Step 3. `global`/`us` 양쪽 `Policy` 바인딩 및 `locations/us` `Model Armor Template` 구성
`NotebookLM Enterprise`는 `global` `Instance`이더라도 **`locations/us` (또는 `eu`)에 생성된 `Model Armor Template`만 호출을 허용**합니다 (`locations/global` 템플릿 연결 시 내부 예외 발생 후 생략됨).

1. **자동화 `Repository` 사용 시**: `git pull origin main && make apply-policy`를 실행하면 `global` 및 `us` 양쪽에 `DLP Template`, `Content Policy`, 그리고 **`locations/us` `Model Armor Template`**을 생성하여 `notebooklmConfig`에 바인딩합니다.
2. **`Console UI` 직접 구성 시**:
   - `Step 3.1`의 `Inspect` / `De-identify Template`을 **`us` (`Multi-region > US`)**에 생성합니다.
   - `Step 4`의 `Model Armor Template`(`ge-notebooklm-armor-tmpl`)을 **`us` (`Multi-region > US`)**에 생성합니다.
   - `Step 5.3`의 `Cloud Shell` 명령어로 `locations/us/templates/ge-notebooklm-armor-tmpl`을 `notebooklmConfig.modelArmorConfig`에 바인딩합니다.

### Step 4. `Copied text` vs `Upload files (.txt)` 교차 검증 및 실시간 보호 확인
`Step 3` 설정을 마친 뒤 새 `Notebook`을 열고 **`+ Add source` > `Copied text` (`복사된 텍스트`)**와 **`+ Add source` > `Upload files` (`.txt` 파일 업로드)**에 각각 아래 문장을 넣어 비교합니다:
```text
VIP 고객 카드번호: 4532-0151-1283-0366, 주민번호: 880101-1234567
```
- **Case 1 (`Copied text`와 `Upload files .txt`가 모두 즉시 차단되는 경우)**: `Step 1~3`에서 교정한 `"failureMode"` 오류 또는 `Allow` 판정 옵션, `Location` 불일치가 원인이었으며 정상 해결된 상태입니다.
- **Case 2 (`Copied text`는 즉시 차단되나 `Upload files .txt`만 통과하는 경우)**: 파일 업로드 큐를 처리하는 `Backend` 서비스의 `SDP` 검사 `Flag` 비활성화 이슈(`b/574535099`)에 해당합니다.
- **Case 3 (`Copied text`와 `Upload files .txt` 모두 통과하고 `BigQuery` 감사 로그에도 기록이 없는 경우)**: `Backend`의 `AddSources` `SDP` `Flag` 비활성화(`b/492615742`) 또는 설정 `Cache` 갱신 지연(`b/564947655`)에 해당합니다.
- **실시간 마스킹 작동 확인**: `Case 2` 또는 `Case 3`으로 인해 파일이 `Source` 목록에 추가되더라도, `Step 3`에서 연결한 **`locations/us` `Model Armor Template`**이 `Notebook` 요약 및 모든 `Chat` 질의응답 시점에 작동해 카드번호와 주민번호를 `[CREDIT_CARD_NUMBER]`, `[KOREA_RRN]`으로 즉시 마스킹합니다 (`Logging > Logs Explorer`에서 `resource.type="modelarmor.googleapis.com/Template"`로 확인 가능). `Upload` 단계 차단까지 활성화하려면 `Google Cloud Support Case`에 `Project Number`와 함께 내부 참조 번호(`b/574535099`, `b/492615742`, `b/564947655`)를 전달해 `Backend Flag` 활성화를 요청해 주시기 바랍니다.


