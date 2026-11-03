# Architecture Deep Dive: `Gemini Enterprise` vs. `NotebookLM Enterprise` `SDP` & `Model Armor` Governance

본 문서는 `Gemini Enterprise (GE)`와 `NotebookLM Enterprise` 간 민감정보 보호(`Sensitive Data Protection`, `SDP`) 및 `Model Armor` 적용 아키텍처, `Multi-Region` 정합성 규칙, `Service Agent IAM Role` 명세, 그리고 4대 감사 로깅(`Audit Logging`) 채널의 기술적 세부사항을 다룹니다.

---

## 1. `Control Plane` 분리 구조 및 `API` 명세 비교

`Google Cloud Discovery Engine` 내에서 `Gemini Enterprise App` (`Engine`)과 `NotebookLM Enterprise`는 서로 다른 리소스 계층에서 보안 정책을 관리합니다.

| 구분 | `Gemini Enterprise App` (`Assistant Chat` & `Search`) | `NotebookLM Enterprise` (`Gemini Notebook`) |
| :--- | :--- | :--- |
| **관리 리소스 계층** | **개별 `Engine` (`App`) 및 `Data Connector` 수준** | **`Project` + `Location` (`Multi-Region`) 단일 설정 수준** |
| **`REST API` 리소스 경로** | `projects/{project}/locations/{loc}/collections/default_collection/engines/{engine_id}/assistants/default_assistant` | `projects/{project_number}/locations/{loc}` (`customerProvidedConfig.notebooklmConfig`) |
| **파일 `Upload` / `Connector` `SDP` 설정 필드** | `DataConnector` 설정 내 `contentPolicy` 또는 `Engine` 첨부파일 정책 | `customerProvidedConfig.notebooklmConfig.dataProtectionPolicy.sensitiveDataProtectionPolicy.sdpPolicy` |
| **`Prompt` / `Response` `Model Armor` 설정 필드** | `assistant.customerPolicy.modelArmorConfig.{promptTemplate, responseTemplate}` | `customerProvidedConfig.notebooklmConfig.modelArmorConfig.{promptTemplate, responseTemplate}` |
| **설정 캐시 주기 (`Cache TTL`)** | 실시간 반영 (라우팅 시점 즉시 평가) | 인메모리 `CustomerConfigurationCache` 적용 (**최대 10분 `TTL`**) |

---

## 2. 데이터 유입 경로(`Ingestion Path`)별 보안 동작 메커니즘

### 2.1 경로 1: `GE Assistant Chat`에서 `GCS Data Store` 문서 질의
1. 사용자가 `GE Assistant Chat`에서 질문(`Prompt`)을 입력하면 `Assistant`에 바인딩된 **`Model Armor` `Prompt Template`**이 입력값의 민감정보(`PII`) 및 `Prompt Injection` 여부를 검사합니다.
2. `GCS Data Store`에서 검색된 문서 스니펫(`Grounded Context`)을 바탕으로 생성된 답변(`Response`)은 사용자에게 반환되기 직전 **`Model Armor` `Response Template`**의 `SDP Filter`를 거치며, 탐지된 민감정보가 마스킹(`De-identify`)되거나 응답이 차단(`Block`)됩니다.

### 2.2 경로 2: `NotebookLM Enterprise`에서 로컬 파일 직접 `Upload`
1. 사용자가 `NotebookLM UI`에서 로컬 문서(`PDF`, `TXT` 등)를 직접 업로드하면, `NotebookLM` 서버는 `Project`의 `customerProvidedConfig.notebooklmConfig`에 연결된 **`Cloud DLP ContentPolicy`**를 확인합니다.
2. 파일 본문이 `DlpService.ApplyContentPolicy`로 전달되어 동기식 스캔을 수행하며, `CREDIT_CARD_NUMBER` 등 지정된 `InfoType`이 탐지되면 `BLOCK` 판정(`Verdict`)을 반환하고 `Notebook` 소스 추가를 즉시 거부합니다.
3. 만약 파일 크기가 단일 스캔 한도를 초과할 경우 `fallbackActionInputTooLarge` 설정을 따르므로, 보안 우회를 방지하기 위해 반드시 **`FALLBACK_ACTION_INPUT_TOO_LARGE_BLOCK`**으로 구성해야 합니다.

### 2.3 경로 3: `NotebookLM Enterprise`에서 `"Add content to..."`로 `GCS Data Store` 문서 가져오기
1. 사용자가 `GE` 검색 결과나 `NotebookLM` 내 `"Add content to..."` 기능을 통해 이미 색인된 `GCS Data Store` 문서를 `Notebook` 소스로 추가할 때는 외부 파일 업로드가 아닌 내부 `Data Store` 간 문서 복사로 처리됩니다.
2. 이 경로에서는 경로 2의 직접 업로드용 `SDP Content Policy` 훅이 호출되지 않으며, 가져온 문서가 `Notebook`의 `Grounded Source`로 등록된 이후에는 `Model Armor`가 `Grounded Source` 자체를 사후 편집하지 않습니다.
3. 따라서 **3계층 방어(`Layer 3: Upstream GCS Pre-Ingestion Cloud DLP De-identification`)**를 통해 `Raw GCS Bucket`의 문서를 사전에 비식별화하여 `Masked GCS Bucket`에 적재한 뒤, `GE Data Store`가 `Masked GCS Bucket`만 바라보도록 구성해야 합니다.

---

## 3. 필수 `Service Agent IAM Role` 명세

`SDP Content Policy`, `Model Armor`, 그리고 `BigQuery` 감사 로그 적재가 오류 없이 동작하려면 아래 두 `Google-managed Service Agent`에 권한이 부여되어 있어야 합니다 (`terraform/iam.tf` 참조).

| `Service Agent` 이메일 형식 | 필수 부여 `IAM Role` | 역할 및 필요 사유 |
| :--- | :--- | :--- |
| `service-{PROJECT_NUMBER}@gcp-sa-discoveryengine.iam.gserviceaccount.com` | `roles/discoveryengine.serviceAgent`<br/>`roles/dlp.user`<br/>`roles/storage.objectViewer` | `Discovery Engine` (`GE` 및 `NotebookLM`)이 파일 업로드 및 커넥터 수집 시 `Cloud DLP ContentPolicy`를 호출하고 `GCS` 문서를 읽기 위해 필요 |
| `service-{PROJECT_NUMBER}@dlp-api.iam.gserviceaccount.com` | `roles/bigquery.dataEditor` | `Cloud DLP`가 `ContentPolicy` 판정 결과(`ContentPolicyActionLog`)를 지정된 `BigQuery` 감사 테이블에 스트리밍 적재(`logToBigQuery`)하기 위해 필요 *(누락 시 `ContentPolicy.errors`에 `PERMISSION_DENIED` 발생)* |

---

## 4. 4대 보안 감사 로깅(`Audit Logging`) 채널 및 상관분석(`Correlation`)

1. **`BigQuery` `ContentPolicyActionLog` (`logToBigQuery`)**:
   - `Cloud DLP ContentPolicy`가 평가한 모든 문서/파일의 `timestamp`, `returned_verdict` (`ALLOW` / `BLOCK`), `matching_info_types`, `policy_rule`, `fallback_action`, `container_id`, `document_id`, `correlation_id`가 적재됩니다.
   - `GE Assistant` 첨부파일 스캔 시 `correlation_id`는 `AS|{engine_name}/assistants/default_assistant|{assist_token}` 형식으로 기록됩니다.
2. **`Cloud Logging` — `DataConnector` 로그 (`discoveryengine.googleapis.com/data_connectors`)**:
   - `resource.type="discoveryengine.googleapis.com/DataConnector"`에서 각 문서 URL별 `SDP verdict for {url}: ALLOW|BLOCK` 텍스트 페이로드를 확인할 수 있습니다.
3. **`Cloud Logging` — `GE User Activity Log` (`gemini_enterprise_user_activity`)**:
   - 사용자의 파일 업로드나 질의가 정책에 의해 차단된 경우 `CUSTOMER_POLICY_VIOLATION` (`violation_source="ATTACHMENT"`, `sdp_enforcement_result.violation="Sensitive data detected."`) 이벤트가 기록되며, `assistToken`을 통해 `BigQuery` `correlation_id`와 조인(`Join`)할 수 있습니다.
4. **`Cloud Logging` — `Model Armor Template` 로그 (`modelarmor.googleapis.com/Template`)**:
   - `templateMetadata.logSanitizeOperations = true` 활성화 시 모든 `SanitizeUserPrompt` 및 `SanitizeModelResponse` 호출에 대한 탐지/마스킹 결과가 기록됩니다.
