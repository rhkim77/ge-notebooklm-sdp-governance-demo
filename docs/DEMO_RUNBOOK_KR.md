# 고객 대면 시연 시나리오 가이드 (`Live Demo Runbook`)

본 문서는 고객사 `Test` 환경(또는 `Sandbox Project`)에서 **`Gemini Enterprise (GE)` 및 `NotebookLM Enterprise`의 민감정보 보호(`SDP` · `Model Armor`) 통합 `Governance`**를 약 15~20분 동안 시연하기 위한 단계별 진행 대본(`Runbook`)입니다.

---

## 0. 시연 전 체크리스트 (`Pre-Demo Checklist` — 시연 15분 전)

1. `.env` 파일에 고객 `Test Project`의 `PROJECT_ID`, `LOCATION` (`global` 또는 `us`), `GE_ENGINE_ID`, `GE_DATA_STORE_ID`가 올바르게 입력되어 있는지 확인합니다.
2. `NotebookLM Enterprise`의 **`CustomerConfigurationCache` (최대 10분 `TTL`)** 특성상, 시연 중 10분을 기다리지 않으려면 다음 두 가지 방법 중 하나를 선택합니다:
   - **방법 A (`Before` 화면 캡처 활용 + 사전 바인딩)**: 시연 10분 전에 `make apply-policy`를 미리 실행해 두어 라이브 시연 시점에는 즉시 `NotebookLM` 파일 `Upload` 차단(`BLOCK`)이 동작하도록 준비합니다.
   - **방법 B (`Early Binding` 순서 진행)**: 시연 초반에 브라우저에서 `NotebookLM UI`를 열기 **전에** `make apply-policy`를 먼저 실행하면, 첫 `UI` 접근 시점에 최신 설정이 캐시에 적재되어 대기 시간 없이 즉시 정책이 발효됩니다.

---

## 1. `Step 1`: 테스트 자산 및 유효 `Luhn Checksum` 샘플 문서 준비 (3분)

### 실행 명령어
```bash
make prepare-assets
```

### 화면 확인 및 발표 포인트
- 터미널에 출력되는 **`Sample Credit Card Luhn Checksum Verification`** 표를 고객에게 보여줍니다.
- **설명 포인트**:
  > "`Cloud DLP`의 `CREDIT_CARD_NUMBER` `InfoType`은 오탐(`False Positive`)을 줄이기 위해 단순 16자리 숫자 배열이 아닌 **`Luhn Checksum` 알고리즘을 통과하는 실제 카드번호 형식**만 탐지합니다. 오늘 시연에서는 `Luhn Checksum` 검증을 통과한 테스트용 카드번호(`4532-0151-1283-0366`)와 주민등록번호(`880514-1234567`)가 포함된 `vip_customer_claim_raw.pdf` 문서와, 민감정보가 없는 일반 규정 문서인 `store_operation_policy_clean.pdf` 두 가지를 사용합니다."
- 동시에 `Raw GCS Bucket` (`gs://<PROJECT_ID>-ge-sdp-raw-docs`), `Masked GCS Bucket` (`gs://<PROJECT_ID>-ge-sdp-masked-docs`), 그리고 감사 로그가 적재될 `BigQuery` `Table` (`sdp_audit_logs.content_policy_action_logs`)이 준비되었음을 확인합니다.

---

## 2. `Step 2`: `Control Plane` 분리 구조 진단 — 왜 `NotebookLM`만 `SDP`가 빠졌는가? (4분)

### 실행 명령어
```bash
make inspect
```

### 화면 확인 및 발표 포인트
- 터미널에 출력되는 **`Control Plane Binding Comparison: Gemini Enterprise App vs. NotebookLM Enterprise`** 비교 표를 확인합니다.
- **설명 포인트**:
  > "표에서 보시는 것처럼 `Gemini Enterprise Assistant Chat`은 개별 `Engine` (`engines/{ENGINE_ID}`)에 연결된 정책을 따라가지만, `NotebookLM Enterprise`는 개별 `App` 하위 리소스가 아니라 **`Project` + `Location` (`global` 또는 `us`) 수준의 독립적인 `customerProvidedConfig.notebooklmConfig`** 설정을 참조합니다. 현재 `NotebookLM` 쪽의 `Layer 1 (SDP Content Policy)`과 `Layer 2 (Model Armor Filter)`가 모두 `UNBOUND (NULL)` 상태이기 때문에, `GE Chat`에서는 막히던 민감정보가 `NotebookLM`에서는 그대로 통과했던 것입니다."

---

## 3. `Step 3`: `SDP Content Policy` & `Model Armor` 양쪽 `Control Plane` 바인딩 (4분)

### 실행 명령어
```bash
make apply-policy
```

### 화면 확인 및 발표 포인트
- 스크립트가 자동으로 다음 4가지를 수행하는 과정을 보여줍니다:
  1. `Cloud DLP InspectTemplate` 및 `DeidentifyTemplate` 생성 (`CREDIT_CARD_NUMBER`, `KOREA_RRN`, `PHONE_NUMBER`)
  2. `Cloud DLP ContentPolicy` 생성 (`FALLBACK_ACTION_INPUT_TOO_LARGE = BLOCK` 설정으로 대용량 파일 우회 차단 + `BigQuery` `logToBigQuery` 활성화)
  3. `Model Armor Template` 생성 (`SDP Filter` 및 `Prompt Injection & Jailbreak Filter` 활성화)
  4. `Discovery Engine v1alpha` `projects.patch` `API`를 호출하여 `Project` 수준 `NotebookLM` (`customerProvidedConfig.notebooklmConfig`)과 `GE App` (`default_assistant`) 양쪽에 정책 바인딩 완료
- 이어서 다시 한 번 `make inspect`를 실행하여 양쪽 `Control Plane` 모두 초록색 **`BOUND`** 상태로 전환된 것을 확인합니다.

---

## 4. `Step 4`: `GCS Data Store` 사전 비식별화(`Upstream DLP Masking`) 파이프라인 실행 (4분)

### 실행 명령어
```bash
make mask-gcs
```

### 화면 확인 및 발표 포인트
- 터미널에 좌우 나란히 출력되는 **`BEFORE: Raw GCS Content (Unmasked PII)` vs. `AFTER: Cloud DLP Masked Content`** 비교 패널을 보여줍니다.
- **설명 포인트**:
  > "`NotebookLM`에서 로컬 파일을 직접 `Upload`할 때는 방금 `Step 3`에서 연결한 `SDP Content Policy`가 즉시 파일을 스캔하여 차단(`BLOCK`)합니다. 하지만 이미 색인된 `GE GCS Data Store`에서 `'Add content to...'` 메뉴로 문서를 가져올 때는 내부 `Data Store` 간 복사로 동작하므로, 근본적인 보안을 위해 `GCS Data Store`에는 **사전 마스킹(`Masked Bucket`)된 문서만 색인**되도록 `Upstream Cloud DLP De-identification Pipeline`을 구성합니다. 보시는 것처럼 카드번호와 주민등록번호가 `[CREDIT_CARD_NUMBER]`, `[KOREA_RRN]`으로 안전하게 치환된 후 `Data Store`에 동기화됩니다."

---

## 5. `Step 5`: 실시간 차단/마스킹 검증 및 `BigQuery` · `Cloud Logging` 감사 증적 확인 (5분)

### 5.1 `UI` 시연 (`NotebookLM Enterprise` & `GE Assistant Chat`)
1. **직접 파일 `Upload` 차단 검증 (`NotebookLM`)**:
   - `NotebookLM Enterprise`에서 새 `Notebook`을 열고 로컬 파일 `sample_data/generated/vip_customer_claim_raw.pdf` (민감정보 포함)를 `Upload`합니다.
   - `SDP Content Policy`에 의해 업로드가 거부(`BLOCK`)되는 것을 확인합니다.
   - 반면 민감정보가 없는 `sample_data/generated/store_operation_policy_clean.pdf`를 `Upload`하면 정상적으로 허용(`ALLOW`)됩니다.
2. **`GCS` `"Add content to..."` 마스킹 검증**:
   - `NotebookLM`에서 `GCS Data Store` 문서를 추가했을 때 원본 카드번호 대신 `[CREDIT_CARD_NUMBER]`로 마스킹된 안전한 본문만 조회되는 것을 확인합니다.

### 5.2 터미널 런타임 검증 및 통합 감사 로그 조회
```bash
make verify-logs
```
- **확인 포인트**:
  1. **`Model Armor Live Sanitization Result`**: 유효 카드번호와 주민번호가 포함된 `User Prompt`를 전송했을 때 `Filter Match State = MATCH_FOUND`와 함께 민감정보가 실시간 마스킹된 결과를 확인합니다.
  2. **`Cloud DLP ContentPolicy Health`**: `ContentPolicy.errors` 배열이 비어 있는지(`0 export errors`) 확인하여 `BigQuery` 로깅 권한(`roles/bigquery.dataEditor`)에 문제가 없음을 증명합니다.
  3. **`Latest BigQuery SDP ContentPolicyActionLog Records`**: `BigQuery` 테이블(`sdp_audit_logs.content_policy_action_logs`)에 기록된 `returned_verdict` (`BLOCK` / `ALLOW`), `matching_info_types` (`CREDIT_CARD_NUMBER`, `KOREA_RRN`), `document_id`, `correlation_id` 감사 증적을 확인합니다.
