# ADR-0073: Requirement Judge와 Capability Routing V2 책임 분리

Status: Accepted

Related ADRs: [ADR-0038](ADR-0038-workflow-aware-adaptive-routing.md), [ADR-0059](ADR-0059-judge-bootstrap-incremental-routing.md), [ADR-0064](ADR-0064-provider-execution-capability-boundary.md), [ADR-0066](ADR-0066-nested-llm-canonical-node-location.md), [ADR-0067](ADR-0067-production-https-and-operation-bound-outbound.md), [ADR-0069](ADR-0069-provider-usage-durable-ledger.md), [ADR-0071](ADR-0071-rag-query-embedding-provider-capability.md), [ADR-0072](ADR-0072-outbound-proxy-only-network-enforcement.md)

> 이 문서의 채택은 V2 production activation 승인이 아니다.
> 아래 활성화 게이트와 MBA-372 통합 검증을 통과하기 전까지 V2는 기본 비활성으로 유지한다.
> ADR-0059의 versioned V1 row와 실행 이력은 호환·rollback을 위해 보존한다.

## 배경

[ADR-0059](ADR-0059-judge-bootstrap-incremental-routing.md)는 초기 운영 요청마다 Judge가
현재 후보 모델 중 하나를 선택하고, 충분한 label이 쌓이면 로컬 분류기가 그 선택을 재현하는
`judge_bootstrap_incremental_v1`을 결정했다. MBA-340은 Judge가 모델 ID 대신 요청에 필요한
능력을 판정하고 서버가 현재 모델 capability와 운영 evidence를 비교하는 V2를 별도 전략으로
제안했다.

현재 구현은 Requirement Judge와 서버 selector를 도입했지만 V2 의미를 V1 strategy ID 아래에서
실행한다. 누락된 `task_type`은 `generate`로 간주되고, learner 전환 기준은 ADR-0059와 다르며,
cache·learner·trace가 현재 routing contract에 완전히 결합되지 않았다. 따라서 현재 코드는 목표
방향의 일부를 구현했지만 V1도 V2도 완결된 상태가 아니다.

2026-07-20부터 2026-07-22까지의 실험은 현재 selector가 일부 고정 baseline보다 비싸거나 느리고
품질도 낮을 수 있으며 local takeover와 locked holdout 비교가 완결되지 않았음을 보여준다. 일부
실험에는 source SHA, dirty state, dataset hash, catalog·pricing·selector·Judge·learner version이
없으므로 production 활성화 근거로 사용할 수 없다.

| 검토 근거 | 직접 관찰 | 허용되는 결론 |
| --- | --- | --- |
| [Contract isolation 80](../../reports/model-routing/runs/judge-first/2026-07-20__contract-isolation-80__judge-gpt-5.4-mini/report.md) | Auto는 mid fixed보다 총비용·평균 LLM node 시간이 높고 품질 통과율이 낮았다 | 현재 selector에 경제성·품질 admission이 필요하다 |
| [Learner blind 40](../../reports/model-routing/runs/judge-first/2026-07-21__learner-v2-blind-50__auto-high-mid/report.md) | Auto가 mid fixed보다 비싸고 느리며 품질 통과율도 낮았다 | 현재 learner/selector 결합을 production 우위로 볼 수 없다 |
| [Learning 100](../../reports/model-routing/runs/judge-first/2026-07-22__routing-learning-100__benchmark-20/learning/report.md) | Judge가 100/100 호출됐고 fixed baseline·독립 품질 평가는 포함되지 않았다 | Learner 효과나 100-label 기준의 타당성을 입증하지 못한다 |
| [Auto vs high 25](../../reports/model-routing/runs/judge-first/2026-07-22__auto-vs-high-30__generative-safe-fallback-v4/benchmark/report.md) | Auto는 high fixed보다 저렴했지만 더 느리고 품질 통과율이 낮았다 | 비용만으로 activation을 승인할 수 없다 |

이 결과는 selector·learner 개선 필요성의 진단 근거다. Manifest와 locked holdout 조건을 충족하지
않으므로 V2 폐기, learner threshold 변경 또는 production activation의 승인 근거로 사용하지 않는다.

이 결정은 V2 방향을 폐기하거나 Judge 직접 선택으로 되돌리지 않는다. V2를 독립된 versioned
전략으로 정의하고, 구현·실험·승인 경계가 모두 준비될 때까지 기본 비활성으로 유지한다.
ADR-0073의 계약 권위는 ADR-0059의 신규 runtime 정책을 대체하되, V1 row와 실행 이력은
역사·호환 데이터로 보존한다.

## 결정

### 1. Requirement Judge는 요구 능력만 판정한다

V2의 Requirement Judge는 현재 rubric version에 따른 bounded 결과만 반환한다.

- `task_complexity`: 0부터 3
- `decision_impact`: 0부터 3
- `evidence_synthesis`: 0부터 3
- `confidence`: 0부터 1
- allowlist 기반 `ambiguity_flags`
- allowlist 기반 `reason_codes`

`judge_contract_version`과 `rubric_version`은 모델 응답 필드가 아니다. Routing application은 provider
호출 전에 두 값을 server-owned immutable invocation envelope에 고정하고, 파싱한 bounded result와
함께 provenance로 결합한다. 모델이 두 version을 echo하거나 다른 version을 주장하면 unknown field
contract failure로 처리하며 그 값을 신뢰하지 않는다. Model response body는 위 bounded field만
허용한다.

모델 ID, 후보 목록, 가격, credential, provider private state와 policy ID는 Judge 입력·출력에서
제외한다. Output schema, tool use, context window와 외부 부수효과처럼 서버가 결정적으로 계산할 수
있는 값은 structural fact와 hard gate로 처리한다.

Judge 요청은 실행 중에만 존재하는 bounded projection이다. 인증 실행의 execution subject 또는
ADR-0018 Anonymous Public Audience는 Knowledge/source 데이터 접근 범위에만 사용하고 credential
principal로 재해석하지 않는다. 호출 전에 ADR-0064의
deployment policy에서 server-derived한 credential principal, exact Judge model policy, provider lifecycle과
조직의 data egress 정책을 검증하고 승인된 provider에만 전달한다. Public·schedule·system actor를
credential principal로 승격하거나 owner credential을 fallback하지 않는다. Raw RAG chunk/document,
credential, 다른 tenant 정보와 private candidate state는 전달하지 않으며 request/response 원문은
trace, audit, cache, label과 실험 report에 영속하지 않는다. Judge provider 호출도 ADR-0064의
server-issued capability와 capability-bound budget admission을 통과해야 한다. Judge, primary와 fallback
attempt는 같은 Billing Principal에 귀속하되 purpose와 attempt identity를 분리하고 ADR-0069 원장에
실제 사용량을 각각 종결한다.

RAG query embedding은 ADR-0071의 별도 `purpose=query_embedding`, exact embedding-model policy와
capability를 사용한다. V2의 Judge/main-generation/candidate credential policy로 query embedding을
승인하거나 query embedding policy를 작업 모델 권한으로 재사용하지 않는다. 권한 있는 retrieval이
완료된 뒤의 bounded safe facts만 Requirement Judge에 전달하며 query embedding policy/capability 실패를
V2 stored default/fallback으로 우회하지 않는다.

이 결정은 ADR-0064의 credential authority를 대체하지 않는다. ADR-0064의 현재 node별 단일 active
exact-model policy는 다중 모델 후보의 사용 권한이 아니다. Capability-required V2를 effective strategy로
사용하려면 별도 Accepted ADR과 구현이 Judge model 및 각 primary/fallback 후보를 model-bound policy로
명시하고, 같은 server-derived credential principal·organization·deployment version에서 current relation과
credential `use`를 검증해야 한다. 이 정책이 없으면 V2 Judge와 selector를 실행하지 않고 versioned
non-V2 policy 또는 stored safe path로 전환하며, 그 경로도 없으면 provider I/O 전 typed failure로 닫는다.

축을 추가·삭제하거나 점수 의미를 바꾸는 것은 rubric version 변경이다. 이 변경은 learner,
cache와 평가 contract를 회전시킨다. 첫 Judge가 계약에 맞는 응답으로 성공했지만 confidence가
versioned policy 기준보다 낮은 경우에만 동일한 bounded schema의 secondary Judge를 최대 한 번 호출할
수 있다. Secondary Judge도 모델을 선택하지 않으며 호출 조건, 병합 규칙, 비용과 지연 budget을
policy에 포함한다. 첫 Judge가 `provider_started` 뒤 `outcome_unknown`으로 종결되면 같은 routing
decision에서 Judge를 자동 재시도하거나 secondary Judge로 대체하지 않는다. 별도로 versioning된
current-valid non-V2 stored safe path가 있으면 독립 work-model attempt의 current
capability·budget·egress admission과 durable intent를 거친 뒤 사용할 수 있고, 그렇지 않으면 provider
호출 전에 typed failure로 닫는다.

### 2. 서버가 현재 상태를 기준으로 최종 모델을 선택한다

서버는 다음 순서를 지킨다.

1. 현재 실행의 데이터 접근 범위와 organization scope를 확정하고, ADR-0064에서 server-derived한
   credential principal 및 각 exact-model policy의 current relation·credential lifecycle·provider
   availability와 current global workflow model execution eligibility를 검증해 사용할 수 없는 후보를
   제외한다. 날짜 고정 ID나 정책상 실행 제외 모델을 저장 graph/policy가 참조해도 이 gate를 우회하지
   못한다.
2. context window, structured output, tool use, output/effect contract와 안전 하한을 hard gate로
   적용한다.
3. 동적 라우팅의 기대 이익이 routing overhead와 risk margin을 넘는지 판정한다.
4. current contract와 일치하는 local classifier 또는 Requirement Judge에서 요구 능력을 얻는다.
5. 요구 능력과 minimum quality evidence를 충족하지 못한 후보를 제외한다.
6. 남은 후보를 예상 전체 비용, 예상 지연과 품질 제약으로 비교한다.
7. 동률은 versioned canonical model order로 해소한다.

인증 interactive 실행의 데이터 접근 범위는 current `execution_subject`다. Subject가 없는 public,
webhook, schedule, API와 system 실행은 ADR-0018의 Anonymous Public Audience로 낮추며 active public
Collection/KB와 source-managed public exposure approval을 통과한 근거만 사용할 수 있다. Owner,
deployment creator, audit actor, `user_id` 또는 credential principal을 synthetic execution subject로
만들지 않는다. 향후 service account를 쓰려면 별도 Accepted ADR과 immutable deployment binding이
먼저 필요하며, 그 전에는 private Knowledge 접근을 승인하지 않는다. Requirement Judge에는 이 데이터
범위와 ADR-0071 query-embedding 경계를 통과한 bounded safe facts만 전달한다. 허용 근거가 없으면
Knowledge의 safe no-result 또는 node의 versioned RAG failure policy를 적용하고, 거부된 resource의
ID·이름·정확한 수를 Judge, trace와 audit에 노출하지 않는다.

Cache, preview, Client 또는 prompt가 전달한 모델 ID와 task hint는 authorization capability가
아니다. 각 primary·fallback provider 호출 직전에도 authorization, credential lifecycle과
provider availability를 다시 검증하고 별도 capability-bound budget admission을 수행한다. Judge
예산을 승인했다는 사실은 primary/fallback 예산 승인이 아니며, budget unavailable·exceeded 또는
가격 불명 상태에서는 해당 provider I/O를 시작하지 않는다.

### 3. task intent 누락은 `unspecified`다

Canonical 내부 값은 다음 enum을 사용한다.

```text
unspecified | classify | extract | transform | generate
```

- 유효한 기존 `task_type`은 canonical `task_intent`로 정규화한다.
- 필드가 없는 legacy graph는 `unspecified`다.
- 누락값을 `generate`로 채우거나 prompt keyword만으로 영속하지 않는다.
- Legacy Cost Optimizer 값은 `classify -> classify`, `extract -> extract`,
  `summarize -> transform`, `generate -> generate`로 정규화한다. `reason`은 추론 난이도이지 작업
  intent가 아니므로 `unspecified`로 두고 Judge 요구 축과 server structural fact가 처리한다.
- `model_routing_context.node_task`처럼 자유 문자열인 legacy hint는 exact allowlist 값일 때만 사용하고
  그 밖의 값은 `unspecified`다. 도메인명·노드명·prompt keyword로 intent를 추측하지 않는다.
- task intent는 routing hint이며 authorization 또는 안전 capability가 아니다.
- explicit `generate` 또는 server가 확인한 human-facing 자유형 출력에만 generative floor를
  적용한다.
- output schema, 외부 부수효과와 high-risk structural fact는 task intent보다 우선한다.

### 4. V2는 독립 strategy로 versioning한다

- `judge_bootstrap_incremental_v1`의 의미를 V2로 바꾸지 않는다.
- V1 policy, cache와 learner를 V2로 자동 재해석하지 않는다.
- V2 strategy ID는 `capability_routing_v2`다.
- V2는 별도 feature flag와 명시적 immutable policy version으로 기본 비활성 도입한다.
- strategy, activation profile, selector, learner와 cache contract가 모두 current일 때만 실행한다.
- unknown 또는 stale version은 V2 Requirement Judge 호출 전에 별도로 versioning된 current-valid
  non-V2 policy, stored safe path 또는 typed failure로 닫는다.
- 명시적으로 versioned된 `judge_bootstrap_incremental_v1`은 ADR-0059의 legacy Selection Judge가
  current authorization으로 거른 후보 중 모델을 직접 선택하는 V1 의미를 유지한다. V2 Requirement
  Judge와 wire schema, cache, learner 및 source enum을 공유하지 않는다.
- 현재 DB row는 `active_policy.strategy_id` 외 immutable `strategy_contract_version`이 없어 어떤 코드
  의미로 발행됐는지 증명할 수 없다. 이 row를 생성 시각이나 현재 코드로 V1/V2에 자동 분류하지
  않는다. `legacy_ambiguous`로 취급해 dynamic Judge/local/cache routing을 끄고 current gate를 통과한
  stored safe model만 사용한다. Safe model도 없으면 provider 호출 전 typed failure로 닫는다.
- Legacy ambiguous row를 versioned V1 또는 V2로 자동 migration하지 않는다. Workflow deploy 권한자가
  current graph와 candidate scope를 다시 검증해 재배포/reissue해야 한다. Historical trace와 usage는
  기존 strategy 문자열을 그대로 보존한다.
- V2 activation profile은 별도로 검증·발행한 non-V2 rollback policy version을 명시해야 한다.
  Profile 부재·stale 상황에서 임의의 V1 row를 찾거나 V2 artifact를 V1로 재해석해 fallback하지
  않는다. Rollback target은 재검증·발행한 명시적 V1 또는 별도 non-V2 stored policy만 허용한다.

### 5. 권한·구조·품질 gate는 최적화보다 우선한다

Authorization, credential, provider capability, context/output/effect contract와 minimum quality는
가중치로 상쇄할 수 없는 hard gate다. 비용과 지연은 이 gate를 통과한 후보끼리만 비교한다.
Client가 낮은 task intent를 보내거나 prompt 문구를 조작해도 human-facing, 금전·권한·보안·법무
또는 외부 부수효과 하한을 낮출 수 없다.

### 6. 동적 라우팅에는 경제성 admission을 적용한다

동적 라우팅 예상 이익이 routing overhead와 risk margin을 넘지 못하면 Judge를 호출하지 않고
검증된 stored baseline을 사용한다.

```text
expected_total_cost =
  routing_cost
  + expected_input_tokens * input_price
  + expected_output_tokens * output_price
  + expected_retry_and_fallback_cost
```

Pre-Judge admission은 서버가 이미 아는 input/output 길이 추정, current safe baseline, catalog
가격과 bounded evidence만 사용한다. Judge 결과가 있어야 계산 가능한 값을 admission 근거로
사용하지 않는다. Stored baseline도 current hard gate를 통과하지 못하면 proven safe candidate를
사용하거나 provider 호출 전에 typed failure로 닫는다.

Current pricing version에 가격이 없거나 단위를 비교할 수 없는 후보는 최저 비용 후보로 간주하지
않는다. 별도 품질·운영 정책이 그 사용을 명시적으로 허용하지 않으면 경제성 최적화 대상에서 제외하고
current-valid stored safe path를 유지한다.

실제 비용에는 Judge, 실패, retry, fallback과 outcome-unknown attempt를 포함한다. 품질 비교용
evaluator 비용은 제품 routing cost와 분리하되 실험 비용으로 기록한다. 모든 비용은 routing이
새 Billing Principal을 합성하지 않고 실행 capability가 확정한 principal과 pricing revision에
귀속한다.

### 7. 모델 profile은 provenance를 가진 versioned evidence다

모델 선택 profile은 다음 증거를 구분한다.

- provider가 선언한 capability와 limit
- 수동 bootstrap prior
- 고정 benchmark 결과
- 운영 success/schema/downstream/fallback/latency evidence

각 evidence는 source, version, observed_at, confidence와 적용 scope를 가진다. 출처를 알 수 없거나
freshness 기준을 넘은 evidence는 강한 자동 선택 근거로 쓰지 않는다. Provider 공개 capability와
가격은 전역 catalog로 사용할 수 있지만 tenant 실행에서 파생한 operational evidence는 승인된 익명
집계 contract가 없으면 다음 identity가 모두 같을 때만 재사용한다.

```text
organization_id
workflow_id
canonical_node_location
task_semantic_fingerprint_contract_version
task_semantic_fingerprint
requirement_evidence_cohort_contract_version
requirement_evidence_cohort_id
model_id
evidence_contract_version
```

Prompt/instruction, variable mapping, output/schema, Knowledge/RAG configuration 또는 downstream
structural contract가 바뀌어 fingerprint가 회전하면 같은 node의 이전 operational evidence도 current
minimum-quality 근거가 아니다. 이전 row를 새 identity로 덮어쓰거나 fingerprint를 current state로
재계산해 되살리지 않는다. Fingerprint 원본 구성 요소와 runtime 입력은 model profile, API, trace와
audit에 저장하지 않는다. 같은 task fingerprint라도 다른 `model_id`의 성적이나 다른
`evidence_contract_version`으로 산출한 성적을 합치지 않는다.

`requirement_evidence_cohort_id`는 server가 해당 실행 snapshot의 canonical `task_intent`, bounded
`task_complexity`·`decision_impact`·`evidence_synthesis`와 output/effect/context risk class를
versioned canonical form으로 결합해 만든 opaque identity다. Requirement source가 없거나 cohort를
확정할 수 없는 표본은 current minimum-quality의 positive evidence로 사용하지 않는다. 별도 Accepted
monotonic transfer policy가 없는 한 다른 cohort의 성공 표본을 현재 cohort의 품질 근거로 합치지 않는다.
Raw requirement 값과 입력은 event, API, trace와 audit에 노출하지 않는다.

Aggregate 재사용 identity와 개별 표본 append identity는 구분한다. 각 model attempt는 ADR-0069의
immutable `provider_usage_operation_id`에 결합한 `record_operational_model_evidence` command로
evidence contract version당 최대 한 표본만 제공한다. Trusted logical actor
`platform routing operational evidence system`은 terminal provider operation과 canonical
workflow/node outcome을 읽어 organization/workflow/deployment, canonical node location,
invocation/Loop iteration, model/purpose와 task fingerprint를 server-side로 파생한다. Client, task
payload나 임의 finalizer가 run/node/model attempt identity를 주장할 수 없고, ADR-0069 operation이 없는
legacy 호출은 V2 operational evidence로 승격하지 않는다. Evidence contract가 명시적으로 허용한
work-model purpose와 production `deployed` 또는 사전 등록 limited-canary execution만 표본이 된다.
Requirement Judge, query embedding, summary, 일반 `test`, `policy_preview`와 격리 `benchmark` operation은
tenant operational model evidence에서 제외한다. `outcome_unknown`은 unknown으로만 보존하며 success,
schema/downstream pass 또는 proven-quality 표본으로 승격하지 않는다.

Canonical append identity는 `(organization_id, provider_usage_operation_id,
evidence_contract_version)`이며 canonical safe metric bundle digest를 함께 저장한다. 같은
identity·digest의 순차/동시 재전달은 기존 event/receipt를 반환하고 aggregate sample count를 다시
증가시키지 않는다. 같은 identity의 다른 digest는
`model_routing.operational_evidence_conflict`와 event/receipt/aggregate zero-write로 닫는다. Event,
idempotency receipt와 aggregate delta는 같은 짧은 DB transaction에서 unique constraint와 aggregate
row lock/CAS로 commit하며 provider/network I/O를 수행하지 않는다. ADR-0069 correction 또는 late
reconciliation은 새 sample identity를 만들지 않는다. 별도 evidence correction contract가 구현되기
전에는 기존 표본을 다시 집계하거나 sample count를 늘리지 않는다. Raw prompt/output, provider payload와
credential은 event, digest, receipt와 aggregate에 저장하지 않는다.

### 8. 미검증 후보와 저빈도 workflow를 제한한다

운영 품질 근거가 없는 모델은 low-risk, reversible, internal 요청에서만 versioned canary budget으로
탐색한다. Human-facing, 외부 부수효과, 보안·법무·금전·권한 또는 되돌리기 어려운 요청에는 proven
safe baseline만 사용한다. Guardrail을 넘으면 exploration을 즉시 중단한다.

표본을 장기간 모으기 어려운 workflow는 검증된 fixed stored baseline, 경제성 admission을 통과한
요청의 Judge routing 또는 tenant 경계를 지키는 승인 prior를 사용한다. 조직 간 global learner는
tenant isolation, privacy와 retention을 다루는 별도 ADR 없이는 도입하지 않는다.

### 9. learner candidate와 production activation을 분리한다

새 근거가 승인되기 전 learner candidate 최소 자격은 ADR-0059의 기준을 유지한다.

- 계약에 맞는 Judge label 50건 이상
- 최근 학습 전 예측 20건 이상
- 요구 수준 완전 일치율 80% 이상
- 축별 평균 오차 0.5 이하
- 계약 통과율 95% 이상

계약 실패 label은 평가 분모와 계약 통과율에는 포함하지만 classifier weight와 accepted training
count에는 포함하지 않는다. 이 gate는 local requirement source를 사용할 자격만 부여한다. V2
production activation에는 별도의 locked holdout, 전체 비용, p95 지연, 품질, high-risk 과소판정,
fallback, canary와 rollback 검증이 필요하다. 사전 등록한 cohort별 모델 선택 분포 guardrail,
운영 schema/downstream 성공률 95% 이상과 fallback 5% 이하도 learner 자체의 요구 판정 능력이 아니라
selector와 runtime의 production activation gate에서 검증한다. 단일 모델 수렴 자체를 실패로 보거나
임의의 다양성을 강제하지 않고, 다양한 적격 요구 cohort에서도 profile이 허용한 분포를 벗어나거나
선택 근거로 설명할 수 없는 수렴만 차단한다.

Candidate gate 통과와 immutable learner version 발행은 active V2 policy 또는 activation profile을
자동 변경하지 않는다. Production 실행이 local classifier를 쓰려면 activation profile이 exact
learner version과 requirement contract digest를 승인해야 한다. 새 learner version은 기존 version의
in-place replacement가 아니며 새 profile revision, locked holdout, limited canary와 독립 production
승격을 다시 거친다.

### 10. learner와 cache는 각 소비 의미에 맞는 contract에 종속된다

Requirement contract digest는 최소 다음 version과 contract를 포함한다.

- Judge rubric version
- feature schema와 encoder version
- task intent normalization contract version과 canonical normalized `task_intent`
- learner label/evaluation contract version
- canonical deployment snapshot의 immutable task semantic fingerprint와 fingerprint contract version

Task semantic fingerprint는 canonical node location의 canonical normalized `task_intent`와 normalization
contract version, 고정 prompt/instruction, variable mapping, output/schema, Knowledge/RAG configuration과
downstream structural contract를 server-side canonical form으로 결합한다. Runtime 원문 값, credential
ID/material, mutable catalog/profile/pricing은 포함하지 않는다. 동일 의미의 재배포는 같은 fingerprint를
재사용할 수 있지만 canonical intent 또는 위 작업 의미가 바뀌면 새 learner lineage를 만들며,
fingerprint 원본 구성 요소를 API·trace·audit에 노출하지 않는다.

Selection contract digest는 다음 값을 포함한다.

- strategy와 selector version
- requirement contract digest
- authorization을 제외한 server hard-gate policy와 output/effect/context structural contract version
- model catalog/profile와 pricing version
- activation profile ID/revision과 exact requirement source manifest digest

Top-level routing contract version은 requirement와 selection contract를 함께 가리키는 실행 provenance다.
Learner는 requirement contract가 같으면 catalog·profile·pricing만 바뀌어도 재사용할 수 있지만,
accepted decision cache는 selection contract까지 같아야 한다. Requirement contract가 바뀌면 learner와
cache를 모두 회전한다. Selection contract만 바뀌면 기존 accepted cache entry는 모두 mandatory miss로
처리하고 current contract의 server selector를 다시 실행하되 learner는 불필요하게 재학습하지 않는다.
Stale cache가 가리킨 모델을 current gate로 재검증하는 것만으로 cache hit로 되살리지 않는다.
같은 requirement contract여도 activation profile 또는 exact requirement source가 learner A에서 B,
`approved_learner`에서 `judge_only` 등으로 바뀌면 selection contract와 cache namespace가 회전한다.
이전 profile/source가 만든 requirement 판정과 model recommendation을 새 activation 근거로 재사용하지
않으며, requirement contract 자체가 같으면 learner lineage까지 불필요하게 폐기하지 않는다.

Cache는 추천일 뿐 authorization이나 안전 승인 결과가 아니며, cache hit 후에도 current candidate,
authorization, credential/provider lifecycle과 hard gate를 다시 검증한다. Digest 없는 legacy cache는
miss로 처리한다. HMAC algorithm과 key epoch는 cache namespace identity에 포함한다. Key rotation은
이전 cache를 miss로 만들며 learner 또는 selection 의미를 바꾸지는 않는다. 같은 key/contract의 동시
fill은 immutable compare-and-set 또는 unique identity로 한 결과에 수렴하고 다른 contract artifact를
덮어쓰지 않는다. Cache namespace는 organization, deployment/version, canonical node location,
selection contract, activation profile/source binding과 key epoch를 포함하고 HMAC key material은 cache,
trace와 audit에 저장하지 않는다.
같은 입력이어도 다른 organization·deployment·node cache를 재사용하지 않는다.

### 11. durable node identity와 invocation identity를 분리한다

Policy와 learner의 durable node identity는 ADR-0066의 canonical `(container_path, node_id)`를
사용한다. Label과 attempt의 exactly-once identity에는 run, node invocation과 Loop iteration
identity를 추가한다. Terminal `node_id`만으로 다른 container나 반복 실행을 합치지 않는다. 같은
terminal event의 retry/background finalizer 중복은 하나의 label outcome과 count로 수렴하고,
동시 learner 발행은 expected active generation을 비교해 stale candidate의 승격을 거부한다.

### 12. 요구 판정·선택·재사용 출처를 분리한다

Canonical observability는 먼저 strategy 해석을 기록한다.

```text
requested_strategy_id
effective_strategy_id
strategy_resolution_reason:
  requested_active | economic_admission_skipped | feature_disabled |
  emergency_disabled | profile_missing | profile_stale | profile_disabled |
  profile_expired | profile_superseded | strategy_out_of_scope |
  activation_requirement_source_unavailable | credential_policy_unavailable |
  worker_incompatible | rollback_policy_selected |
  strategy_contract_unresolved | rollback_target_invalid | benchmark_isolated |
  no_safe_path
```

`strategy_resolution_reason`은 bounded allowlist이며 credential, 후보 ID와 private scope detail을 포함하지
않는다. `profile_superseded`는 신규 실행의 predecessor 해소에만 사용하며 정상 cutover 전에
predecessor snapshot을 고정한 in-flight run의 중단 reason으로 합성하지 않는다. Typed failure 전에
실행 가능한 policy가 없으면 `effective_strategy_id=null`이다. 다음 V2 source
필드는 `effective_strategy_id=capability_routing_v2`인 decision에만 존재한다.

```text
requirement_source:
  runtime_judge | local_classifier | not_required | unavailable

model_selection_source:
  server_capability_selector | stored_default | stored_fallback

routing_reuse_source:
  none | accepted_decision_cache

requirement_evaluation_scope:
  current_execution | accepted_decision_cache | none
```

`not_required`는 effective V2 안에서 economic admission으로 요구 판정을 의도적으로 생략한 상태다.
V2 off, profile·requirement source·scope·credential policy·Worker 부적격은 requested/effective
strategy와 resolution reason으로
기록하고 V2 requirement source를 합성하지 않는다. `unavailable`은 effective V2가 요구 판정을 얻으려
했지만 호출·파싱·contract validation에 실패한 상태다. Secondary Judge를 사용해도 requirement source는
`runtime_judge`이며 bounded attempt count와 adjudication 여부로 구분한다.

`requirement_source`는 현재 execution에서 Judge가 실제 호출됐다는 telemetry가 아니라 effective
requirement의 origin을 뜻한다. Accepted decision cache가 requirement와 selection recommendation을 함께
재사용하면 cache row가 보존한 `runtime_judge` 또는 `local_classifier` origin을 유지하고,
`requirement_evaluation_scope=accepted_decision_cache`, `routing_reuse_source=accepted_decision_cache`,
Judge attempt count `0`을 함께 기록한다. UI와 trace consumer는 이 조합을 `이전 판정 재사용`으로
표시하며 이번 execution에서 Judge를 호출했다고 표시하지 않는다. 경제성 생략과 failed source는 각각
`not_required`/`unavailable` 및 `requirement_evaluation_scope=none`으로 기록한다.

기존 `decision_source`와 preview의 `matched_rule | default_model | fallback_model`은 호환 기간의
deprecated projection으로만 유지한다. 이를 V2 canonical source로 재해석하지 않는다. Raw prompt,
RAG 원문, credential, private candidate exclusion detail과 unredacted provider payload는 trace,
audit와 cache에 저장하지 않는다.

### 13. 실패와 fallback은 current gate를 다시 통과한다

Selector가 모델을 정한 뒤 `provider_started` 전에 lifecycle/authorization 변화로 그 후보만 무효가
되면, 같은 pinned selection contract와 원래 승인 후보 집합의 남은 후보를 대상으로 selector를 최대
한 번 다시 실행할 수 있다. 이는 provider 실패 fallback이 아니며 `server_capability_selector` source와
reselection reason을 기록한다. 새 후보를 추가하거나 profile/scope를 넓히지 않는다.

Requirement source/selector를 사용할 수 없거나 1회 reselection에도 후보가 없으면 다음 순서를 사용한다.

1. current data scope와 server-derived credential principal의 model-bound policy를 통과하고 hard gate를
   만족한 stored default
2. 같은 current 검증을 통과한 stored fallback
3. 둘 다 없으면 외부 호출 전 `model_routing.no_usable_model` 계열 typed error

이미 primary provider I/O가 definitive failure로 종결된 뒤에는 stored default로 되돌아가지 않고
current gate를 통과한 configured stored fallback만 평가한다.

Fallback은 권한, credential lifecycle, output/effect contract와 high-risk 하한을 우회하지 않는다.
ADR-0069의 definitive before-send/rejection/failure로 확인된 경우에만 fallback eligibility를 평가한다.
Outcome-unknown provider attempt는 성공 또는 실패로 추측하지 않고 같은 run에서 자동 retry나
fallback provider를 호출하지 않는다. Test Sidebar와 Cost Optimizer
compare 실행은 routing을 평가할 수 있지만 운영 learner label, weight, 성적과 refresh counter를
변경하지 않는다.

### 14. 실험 증거는 재현 가능하고 데이터 최소화돼야 한다

Activation 후보 실험 manifest는 다음 값을 가진다.

- source Git SHA와 dirty flag
- dataset ID/version/hash와 tuning/holdout 구분
- model catalog, pricing, selector, Judge rubric과 learner version
- environment class와 비교에 필요한 bounded 환경 정보
- `valid | invalid | incomplete` run status와 제외 사유
- 데이터 분류, redaction 상태, raw artifact 위치·checksum·retention reference

동일한 locked holdout과 evaluator로 V2, current strategy와 fixed baseline을 비교한다. Invalid,
incomplete 또는 tuning dataset 결과는 activation 계산에서 제외한다. Git에는 redacted aggregate
report와 manifest만 저장하며 raw 입력·출력은 승인된 접근 통제·retention 저장소만 사용한다.

### 15. Activation profile이 없거나 stale하면 V2를 실행하지 않는다

Production activation은 사전 등록된 versioned `routing_activation_profile`을 요구한다. Profile은
최소 다음 값을 가진다.

- immutable requirement source manifest:
  `requirement_source_mode=judge_only | approved_learner`. `judge_only`이면 exact Judge
  policy/rubric/contract version, `approved_learner`이면 exact immutable learner version과 requirement
  contract digest를 고정한다. `approved_learner`는 `learner_judge_fallback=disabled` 또는
  `exact_judge_policy`를 명시하며, 후자일 때만 exact Judge policy/rubric/contract를 추가로 고정한다.
- 비교 baseline과 locked holdout dataset/evaluator version
- cohort별 최소 표본 수, 실패·미평가 분모 처리와 confidence/non-inferiority 계산 방법
- 최소 비용 개선 또는 최대 허용 비용 증가
- 품질·schema·downstream non-inferiority margin
- 최대 p95 latency 증가
- 최대 fallback·provider failure 비율
- high-risk 과소판정과 미검증 후보 사용 한도
- canary 규모·기간·중단 조건
- 작성자·승인자, 승인 시각, 유효 기간과 exact current-valid non-V2 rollback policy version
- environment와 organization/workflow/deployment scope 또는 stable canary 규칙
- strategy/selector/catalog/pricing contract digest
- 최소 호환 Worker build 또는 runtime capability revision과 rollout readiness. Revision은 Client나 producer가
  task payload로 주장한 값이 아니라 실제 delivery를 소비한 process의 code-owned build/runtime identity다.

Locked holdout과 limited-canary evidence는 exact requirement source manifest에 결합하며 manifest에서
실제로 활성화한 source branch만 검증한다. `approved_learner`가 Judge fallback을 `disabled`로 고정하면
learner branch 근거만으로 승격할 수 있다. Fallback을 `exact_judge_policy`로 활성화한 경우에만 해당 exact
Judge branch의 holdout/canary 근거가 없으면 production으로 승격하지 않는다.

Limited-canary evidence는 append-only event와 window별 monotonic `canary_evidence_revision`으로 집계한다.
일반 evidence append transaction은 source identity를 먼저 dedupe하고 current open-window aggregate를
잠근 뒤 event append와 revision 갱신을 함께 commit한다. Sealed snapshot row는 cutoff 이전
late-arrival reconciliation 또는 blocking breach가 snapshot invalidation을 기록할 때만 갱신한다.
논리 service actor `platform routing evidence system`만 authoritative source adapter가 만든
`record_canary_evidence` command를 제출할 수 있다. Canonical dedupe identity는 canary window와 독립된
environment/family/profile ID·revision/safety generation, source kind와 immutable source event ID로
구성하고 이 identity에 unique constraint를 둔다. Server가 배정한 `assigned_window_id`, metric contract
version, bounded event kind와 redacted payload digest는 identity 밖의 immutable comparison field로 저장한다.
같은 source identity와 네 comparison field가 모두 같은 재전달만 기존 event/receipt를 반환한다. 같은
source identity가 다른 window로 재분류되거나 comparison field 하나라도 다르면
`model_routing.canary_evidence_conflict`와 event/revision/block/audit zero-write로 닫는다. 따라서 지연
재전달이나 payload/contract/kind 변경으로 같은 authoritative source event를 두 표본에 append할 수 없다.
이 actor는 profile lifecycle이나 scope를 활성화할 수 없고 blocking evidence에 대해 source identity가
결합된 exact generation의 deny-only safety block만 set할 수 있다.

Production 승격 snapshot은 논리 service actor `platform routing evidence system`의 idempotent
`seal_canary_evidence_window` command로만 만든다. Canonical request는 environment/family/profile
ID·revision/generation, window ID, immutable cutoff, expected open-window aggregate revision과 authoritative
source별 expected watermark를 포함한다. Transaction은 current-window pointer, aggregate와 source watermark
row를 고정 순서로 잠그고 cutoff, aggregate revision과 모든 watermark를 다시 검증한다. 성공 시 window를
sealed로 전이하고 immutable evidence snapshot ID/revision/hash, 다음 open-window pointer, actor/request-bound
receipt와 canonical audit를 한 transaction에 commit한다. Audit 또는 receipt 기록 실패는 window/snapshot/
pointer를 모두 rollback한다. 같은 actor/request 재전달은 기존 snapshot을 반환하고 같은 command ID의
다른 request는 `model_routing.canary_snapshot_seal_conflict`와 zero-write다.

Append가 먼저 commit하면 seal command는 증가한 revision을 읽거나 stale expected revision으로 실패해
재제출되어야 하고, 성공한 snapshot은 그 event를 포함한다. Seal이 먼저 commit하면 cutoff 이후
non-blocking event는 다음 open canary window에 append하며 현재 sealed snapshot revision/hash나
invalidation revision을 변경하지 않는다. Source event time이 cutoff 이전인 late arrival은 일반 append로
현재 snapshot에 합치지 않고 reconciliation이 snapshot을 invalid 상태로 전이하며 invalidation revision을
증가시킨다. Cutoff와 무관한 새 blocking breach는 immutable event, exact profile-bound generation의
deny-only safety block/epoch, snapshot invalidation과 redacted security audit를 한 transaction에 기록한다.
Promotion command는 expected profile/family/domain-claim revision과 exact snapshot identity,
`expected_snapshot_invalidation_revision`을 canonical request에 결합한다. Coordinator는 exact snapshot과
generation safety row를 잠그고 snapshot이 sealed/current이며 invalidation revision이 일치하고 blocking
breach가 없는지 다시 검증한다. 따라서 promotion은 cutoff 이후 non-blocking 트래픽과 경합했다는 이유만으로
stale되지 않고, cutoff 이전 late arrival 또는 blocking breach가 먼저 commit된 경우에만
`model_routing.canary_evidence_stale`과 zero-write로 닫힌다. 권한 있는 operator command는 이후 profile
lifecycle을 `disabled` 또는 승인 rollback으로 종결한다.

Profile이 없거나 current contract와 다르거나 profile-bound requirement source를 현재 실행에서
사용할 수 없으면 V2 Requirement Judge나 다른 learner로 조용히 대체하지 않는다. Workflow에
별도로 versioning된 current-valid non-V2 policy 또는 stored safe path가 있으면 이를 사용하고, 그런
경로도 없을 때만 provider 호출 전에 typed failure로 닫는다. Legacy artifact를 V2 rollback으로
자동 승격하지 않는다. Profile의 수치 기준과 통계 방법은 locked holdout 결과를 보기 전에 사전
등록한다. 최소 표본이나 confidence 조건이 충족되지 않은 결과를 성공으로 보거나 실패·미평가 표본을
분모에서 제거하지 않는다.

Activation profile lifecycle은 다음 상태를 사용한다.

| 상태 | V2 실행 범위 | 진입 조건 |
| --- | --- | --- |
| `proposed` | 실행 불가 | threshold, canary, rollback과 contract를 immutable revision으로 사전 등록 |
| `limited_canary` | 사전 등록한 stable canary scope만 | valid manifest와 locked holdout, current credential policy, 호환 Worker readiness, rollback target을 검증하고 작성자와 다른 actor가 canary 시작을 승인 |
| `production_active` | family의 immutable production activation domain | `limited_canary`의 사전 등록 최소 표본·기간과 품질·비용·지연·fallback·high-risk guardrail을 통과하고 current revision에 독립 승인을 다시 받음 |
| `disabled` | 신규 V2 실행 불가 | guardrail breach 뒤 권한 있는 emergency disable/rollback command |
| `expired` | 신규 V2 실행 불가 | 유효 기간 종료 |
| `superseded` | 신규 V2 실행 불가 | 같은 family successor의 production promotion이 atomic cutover를 완료 |

활성화 진행 경로는 `proposed -> limited_canary -> production_active`다. `proposed`, `limited_canary`와
`production_active`는 유효 기간 종료 시 `expired`, 권한 있는 operator의 disable/rollback command 시
`disabled`로 전이할 수 있다. `superseded`는 같은 family successor의 성공한 production promotion이
predecessor를 원자적으로 교체할 때만 사용한다. `disabled`, `expired`, `superseded`는 terminal 상태이며
활성 상태로 되돌리지 않고 변경된 계약을 새 immutable `proposed` revision으로 등록한다.

각 profile은 `rollout_family_id`와 family의 immutable production activation domain을 가진다. Family에는
`production_active` predecessor 최대 하나와 `limited_canary` successor 최대 하나만 있을 수 있다.
Successor canary가 stable assignment에 일치하면 successor를 선택한다. Predecessor가 있으면 나머지는
predecessor production revision을 선택하고, 없으면 아래 최초 rollout 계약을 적용한다. 서로 다른 family의
active production/canary domain은 overlap할 수 없다.

Rollout family와 최초 assignment contract는 권한 있는 `platform routing operator`의 idempotent
`rollout_family_create` command로만 만든다. Request는 command ID, actor, environment, canonical immutable
activation domain, assignment algorithm/unit contract version과 server-allowed bucket count를 포함하지만 raw
seed를 포함하지 않는다. `RoutingActivationCoordinator`는 environment activation guard를 잠그고 actor 권한,
current global kill state, canonical domain 유효성 및 기존 family와의 overlap을 다시 검증한다. Server는
CSPRNG로 최소 128-bit non-secret opaque seed를 발급하고 immutable family/domain row, assignment contract,
domain registry revision, actor/request-bound receipt와 canonical audit를 한 transaction에 commit한다. Audit/
receipt 실패는 모든 write를 rollback한다. 같은 actor/request 재전달만 기존 family/contract를 반환하고 같은
command ID의 다른 request는 `model_routing.rollout_family_command_conflict`, 같은 domain 또는 overlapping
domain의 concurrent creator loser는 `model_routing.activation_domain_conflict`와 zero-write로 닫는다. 서로
겹치지 않는 family create command는 같은 environment guard에서 순차 overlap 검증한 뒤 각각 commit할 수
있다. Profile propose는 존재하는 immutable family와 assignment contract reference만 받을 수 있다.

Stable canary assignment는 profile에 사전 등록한 immutable
`canary_assignment_contract_version`, non-secret opaque `canary_assignment_seed`,
`canary_bucket_count`와 target bucket range로만 계산한다. Server는 contract가 정의한 canonical encoding으로
environment, `rollout_family_id`, activation domain digest, organization, workflow와 immutable deployment
ID를 결합해 assignment unit을 만든다. Bucket은
`uint64_be(SHA256(canonical_assignment_bytes)[0:8]) mod canary_bucket_count`로 계산하며 canonical bytes에
contract version과 seed도 포함한다. V1의 `canary_bucket_count`는 10,000이고 target ranges는
`[0, 10000)` 안의 non-empty, 정렬·비중첩 구간이며 합계가 10,000보다 작아야 한다. Unknown contract,
잘못된 seed/count/range는 profile propose를 zero-write로 거부한다. Profile
ID/revision, safety generation, Worker/process identity, 실행·재시도 횟수, 시간과 runtime random 값은
bucket 입력이 아니다. Client와 task payload는 assignment unit, seed 또는 bucket을 주장할 수 없다.
Seed는 rollout family assignment contract 생성 시 server가 CSPRNG로 발급한 최소 128-bit 값이며 profile
작성 request는 raw seed를 제출하지 않고 immutable contract reference만 고정한다. 같은 family의 새
profile은 기존 contract reference를 재사용할 수 있다. Reseed/algorithm/unit/count 변경은 server-issued
새 assignment contract와 새 `proposed` profile, 독립 canary-start 승인을 요구한다.
같은 assignment contract와 deployment는 Worker, retry와 process restart가 달라도 같은 bucket을 사용한다.
새 profile이 기존 assignment contract와 seed를 그대로 고정하면 profile revision만으로 rebucketing하지
않는다. Bucket algorithm/seed/unit contract 변경은 새 `proposed` profile과 독립 canary-start 승인을
요구하고, target range 변경은 bucket 값을 바꾸지 않은 채 새 profile에 사전 등록한 eligibility만 바꾼다.
원 assignment unit과 seed는 API, trace와 audit에 노출하지 않고 safe contract version과 range digest만
투영한다.

최초 rollout family에는 production predecessor가 없을 수 있다. 이 경우 limited-canary target만
successor V2를 사용하고 non-target 요청은 profile에 고정된 exact current-valid non-V2 rollback policy를
사용한다. 최초 production promotion은 successor만 `production_active`로 전이하고 존재하지 않는
predecessor row나 `superseded` audit를 만들지 않는다. 이후 successor가 생긴 promotion부터만 기존
production predecessor를 같은 transaction에서 `superseded`로 전이한다.

`proposed -> production_active` 직접 전이는 금지한다. Canary 시작은 아직 존재하지 않는 canary 결과를
요구하지 않고 exact manifest의 locked `activation_holdout`과 실행 준비 상태를 요구한다. Production 승격은 실제 limited-canary
근거를 요구한다. 성공한 승격은 predecessor가 있으면 successor를 `production_active`, predecessor를
`superseded`로 같은 transaction에서 전이한다. 최초 rollout처럼 predecessor가 없으면 successor 전이와
domain claim만 commit한다. 이미 시작한 run은 기존 snapshot을 유지하고 새 run만 successor를 선택한다.
`superseded`는 정상 cutover 상태이므로 새 run의 strategy resolution에서만 predecessor 선택을 막는다.
이미 시작해 predecessor profile/revision을 고정한 run은 global kill, generation block, explicit
disable/rollback, rollback policy·credential·model revoke, provider 비활성화 또는 organization scope
상실 같은 별도 current safety override가 없는 한 이후 node attempt도 기존 snapshot으로 완료한다.
Profile 기준 또는 contract digest 변경은 같은 family의 새 `proposed` revision으로 시작한다. Production
scope 변경은 revision update가 아니라 별도 activation-domain migration이며, 그 migration 계약이 Accepted되기
전에는 overlap profile 생성/start를 zero-write로 거부한다. `limited_canary`와 `production_active` 상태만
effective V2의 current profile이 될 수 있다.

이 profile gate는 production `deployed`와 일반 Test Sidebar `test`가 실제 V2 모델을 선택하는 경로에
적용한다. `policy_preview`는 server-known structural gate와 사용 가능한 기존 local/cache 정보만
평가하고 Judge/provider를 호출하지 않는다. 요구 판정이 없으면 최종 모델을 꾸며내지 않고
`preview_status=requirement_pending` safe 상태를 반환한다. 명시적 `benchmark` harness는 proposed profile과 격리된
예산으로 V2 Judge/provider를 실행할 수 있지만 production policy, learner, cache, activation과 외부
부수효과를 변경하지 않으며 완전한 manifest를 남긴다. `execution_mode=benchmark`에서는
`effective_strategy_id=capability_routing_v2`와 `strategy_resolution_reason=benchmark_isolated`를
진단 provenance로 기록할 수 있지만, 이는 `proposed` profile을 production-effective로 승격하지 않는다.
Benchmark decision은 profile activation, accepted decision cache, learner, workflow policy와 production trace에
재사용할 수 없다.

Billable benchmark는 일반 workflow 실행 command가 아니다. 논리 actor `platform routing benchmark
operator`가 명시적 environment/organization과 target workflow/deployment scope를 요청하고, server는
platform benchmark 권한과 target resource의 current `execute` 권한을 모두 검증한다. 같은 Billing
Principal 아래 Judge와 각 후보 attempt의 credential, egress, budget admission과 durable intent를
provider I/O 전에 각각 기록한다. Benchmark command ID는 actor, target/profile, budget, manifest와
canonical request hash에 결합하며 같은 actor/request 재전달만 기존 receipt/run을 반환한다. 다른
actor/request 재사용은 `model_routing.benchmark_command_conflict`와
run/receipt/success audit/provider I/O zero-write로 닫는다. Commit 전 권한 회수도 같은 write/I/O를
zero-write한다. Run intent commit 뒤에는 각 Judge/candidate attempt 직전에 platform benchmark
권한과 target resource `execute` 권한도 다시 검증한다. 이 시점의 권한 회수는 새 attempt/provider I/O 없이
run을 terminal denied로 종결하고 redacted outcome audit를 남긴다. Duplicate delivery는 기존 receipt/run만
반환하며 추가 provider attempt를 만들지 않는다. 현재 platform benchmark actor/API가 없으므로 일반 product
API에서 billable benchmark를 열지 않고, 구현 전에는 독립 승인된 workload identity와 versioned release
artifact만 허용한다.

### 16. Strategy governance를 네 권한 계층으로 분리한다

| 계층 | 책임 주체 | 허용되는 결정 | 금지되는 결정 |
| --- | --- | --- | --- |
| 전략 등록 | 개발자·아키텍트의 검토된 코드 릴리스 | immutable strategy ID/contract version, hard gate와 fallback 등록·폐기 | 배포만으로 production V2 자동 활성화 |
| 플랫폼 활성화 | 논리 actor `platform routing operator` | activation profile 승인, environment/scope/canary/rollback 설정, global kill enable과 독립 승인된 recovery | 전략 코드 변경, tenant 원문 열람, stale profile 강제 활성화, 단독 actor의 global kill 해제 |
| 격리 benchmark | 논리 actor `platform routing benchmark operator` + target resource `execute` 권한 | proposed profile의 사전 승인 scope·budget·manifest로 진단 run 시작 | 일반 workflow 사용자의 platform profile 실행, production artifact 변경 |
| workflow 선택 | workflow `deploy` 권한자 | 플랫폼이 허용한 strategy version과 immutable rollout family/domain 선택 또는 더 안전한 경로로 opt-out | 허용 scope 확대, threshold 변경, 미승인 version·family/domain 선택 |

현재 RBAC에는 platform-scoped routing/benchmark operator, trusted evidence workload identity와 전용 관리
API가 없다. 이 경계가 구현되기 전 production activation과 billable benchmark는 각각 독립 검토를 거친
versioned release/deployment artifact와 workload identity로만 승인하며 일반 organization manager UI/API에서
변경하거나 실행하지 않는다.

Limited canary 시작과 production 승격은 서로 다른 상태 전이다. 각 command는 current expected revision과
작성자와 다른 독립 승인자를 검증한다. Canary 시작은 `proposed -> limited_canary`만 수행하고 production
scope를 열지 않는다. Coordinator는 성공한 canary start transaction에서 새 immutable profile-bound
safety generation을 할당하고 stable canary assignment에만 capability를 발급한다. Command는 expected
domain generation을 canonical request에 포함하며 guard lock 아래 current generation과 일치할 때만
다음 monotonic generation을 한 번 할당한다. Production 승격은
`limited_canary -> production_active`만 수행하며 그 generation의 사전 등록 canary evidence가 모두
통과해야 한다.

Activation evidence source kind는 `activation_holdout`과 `activation_canary_runtime`으로 제한한다. 등록된
holdout evaluator의 immutable `activation_holdout` artifact는 locked holdout branch만 충족하며 canary
sample, watermark 또는 safety block으로 집계하지 않는다. `record_canary_evidence`는 trusted evidence
workload identity인 canary runtime monitor의 `activation_canary_runtime` event만 activation
aggregate·snapshot·safety block에 반영한다.
`execution_mode=benchmark`의 격리 product benchmark는 별도 `product_benchmark` source kind와 diagnostic
namespace만 사용하며 `record_canary_evidence` 또는 다른 activation evidence write를 제출할 수 없다.
그 시도는 `model_routing.canary_evidence_source_ineligible`과 event/receipt/aggregate/snapshot/block/audit
zero-write로 닫는다. Learner, optimizer와 scheduler도 candidate를 제안하거나 lifecycle command를
제출할 뿐 activation evidence producer 권한을 얻지 않는다. Profile state 변경과 guardrail 위반 뒤
disable/rollback은 권한 있는 `platform routing operator`의 idempotent emergency command만 수행한다.
긴급 경로로 활성화하거나 scope를 넓힐 수 없다.

Profile 유효 기간은 DB current time으로 판정한다. `valid_until`을 지난 profile은 expiry scheduler가
늦더라도 resolver가 즉시 V2 부적격으로 처리한다. Scheduler는 profile row를 직접 변경하지 않고 논리
service actor `platform routing lifecycle system`으로 deterministic `activation_profile_expire` command를
제출한다. Command identity는 profile/family/environment, expected profile revision과 immutable
`valid_until`, state가 claim을 가질 때는 expected claim role/generation에 결합한다. Coordinator는 DB
clock, current non-terminal state와 domain claim을 재검증해 `expired` 전이, receipt와 redacted audit를
한 transaction에 commit한다. Domain claim 해제와
scoped safety generation/epoch 무효화는 만료 profile이 현재 `limited_canary` successor 또는
`production_active` predecessor claim과 exact generation을 실제 소유할 때만 그 소유분에 한해 수행한다.
Claim이 없는 `proposed` profile 만료는 state/receipt/audit만 변경하며 같은 family의 production
predecessor claim, generation과 capability를 변경하지 않는다. Claim mutation predicate는 owner profile
ID/revision, claim role과 generation을 모두 비교해 다른 profile의 claim을 해제할 수 없다. 중복 delivery는
기존 receipt를 반환한다.

모든 activation/profile command receipt는 command ID만이 아니라 actor principal과 canonical request
hash를 저장한다. Canonical request는 command kind, environment/family/profile, target state,
activation domain/scope digest, bounded reason과 rollback policy version을 기본으로 포함한다. Family create는
assignment algorithm/unit contract와 bucket count, domain command는 expected profile/family/domain-claim
revision, canary start는 expected domain generation, expiry는 optional expected claim role/generation,
promotion은 sealed evidence snapshot ID/hash와 `expected_snapshot_invalidation_revision`을 추가한다. Global
kill command만 expected environment guard state/revision/epoch를 포함한다. Raw tenant data와 assignment seed는
포함하지 않는다.
같은 command ID·actor·hash 재시도만 기존 receipt를 반환한다. Actor 또는 canonical request가 다르면
`model_routing.activation_command_conflict`와 profile/domain/receipt/success audit zero-write로 닫는다.

성공 mutation의 profile state/revision, command idempotency receipt와 canonical audit는 같은 DB transaction에서
commit한다. Audit recorder 또는 durable command receipt 기록이 실패하면 상태와 revision을 모두
rollback하고 성공 응답을 반환하지 않는다. 권한 거부 command는 profile state/revision과 command receipt를
만들지 않지만, 기존 security audit policy가 요구하면 safe actor/reason만 담은 transaction-bound
`permission.denied` audit을 남길 수 있다. 이 denial audit은 성공 mutation audit이나 receipt가 아니다.
비동기 notification outbox는 후속 전달에만 사용하며 canonical audit를 대체하지 않는다. Learner,
optimizer, benchmark와 scheduler는 candidate를 제안할 수 있지만 canary 시작, production activation 또는
emergency disable을 직접 쓰지 않는다.

Rollout family create, canary start, production promote, emergency disable/rollback, active claim
expiry/supersede와 activation-domain migration은 단일 `RoutingActivationCoordinator` application 경계를
통과한다. Coordinator는 외부 I/O 전에 짧은 DB transaction을 열고 canonical environment activation guard
row를 먼저 잠근 뒤 family/profile/domain-claim row를 고정 순서로 잠근다. Production promote는 이어서
exact sealed snapshot과 generation safety row를 잠근다. Guard row는 environment registry와 함께 사전
생성하며 missing row를 command가 임의 생성하지 않고 `model_routing.activation_guard_unavailable`로
fail-closed한다.

Environment guard row는 active domain overlap과 global kill을 직렬화하는 fence다. Global kill state를
변경하는 command만 guard state/revision/epoch CAS를 사용한다. Family/domain command는 guard lock 아래
current kill state와 전체 domain overlap을 다시 읽되, expected profile/family/domain-claim revision만 자신의
optimistic concurrency 조건으로 사용한다. 성공한 domain mutation은 별도 monotonic domain registry revision을
증가시킬 수 있지만 unrelated command의 expected guard revision을 stale하게 만들지 않는다. Production
promote는 exact snapshot, `expected_snapshot_invalidation_revision`과 blocking breach도 다시 판정하고 winner의
profile state, domain claim, command receipt와 canonical audit를 함께 commit한다.

같은 environment에서 겹치는 두 family command가 동시에 들어오면 한 command만 승리한다. Loser 또는
bounded lock timeout은 `model_routing.activation_domain_conflict`를 반환하고 profile state/revision,
domain claim, receipt와 success audit를 모두 zero-write로 유지한다. 서로 겹치지 않는 두 command는 동일
expected guard revision을 읽었더라도 environment lock 아래 순차 overlap 검증한 뒤 각각 자신의 domain-local
CAS로 정상 commit할 수 있다. Holdout/benchmark 계산, provider 호출, notification 전송과 다른 network I/O
중에는 activation lock을 유지하지 않는다. 이 coarse environment serialization은 드문 control-plane
mutation의 overlap 검증만 직렬화하며 runtime routing request를 직렬화하지 않는다.

Workflow strategy select/opt-out은 profile mutation과 별개의 durable workflow policy mutation이다. Command는
current workflow policy의 expected version과 idempotency key를 포함한다. Policy row가 없을 때만
`expected_version=null`을 허용하며 첫 생성도 CAS insert로 처리한다. Opt-out은 row 삭제가 아니라 명시적
`opt_out` 상태의 새 policy version으로 저장한다. V2 선택 policy는 exact activation profile ID/revision이
아니라 immutable `rollout_family_id`와 `activation_domain_digest`를 고정한다. Idempotency key는 workflow,
expected version, 요청한 strategy/version, V2이면 family/domain binding 또는 opt-out의 canonical request
hash에 결합한다. 같은 key·같은 request 재시도는 기존 receipt를 반환하고 같은 key의 다른 request는
conflict와 zero-write로 닫는다. 서버는 commit 직전에 workflow `deploy` 권한, active
organization/resource scope, family/domain binding과 선택한 strategy의 current 유효성을 다시 검증한다.
Workflow/deployment가 bound activation domain에 포함되지 않거나 다른 family/domain을 동적으로 해소해야
하는 policy는 저장하지 않는다.

Runtime resolver는 새 run을 시작할 때 policy의 exact family/domain 안에서만 current
`production_active` predecessor와 optional `limited_canary` successor를 읽고 canonical stable assignment로
profile을 선택한 뒤 exact profile ID/revision, safety generation과 workflow policy version을 execution
snapshot에 고정한다. Successor promotion 뒤에는 workflow policy mutation이나 재배포 없이 같은
family/domain에 결합된 새 run만 successor를 선택하고, 이미 시작한 run은 별도 safety override가 없는 한
pinned predecessor를 유지한다. 다른 family/domain으로 전환하려면 workflow `deploy` actor가 새 policy
CAS command를 제출해야 한다.
성공 시 workflow policy version, command receipt와 canonical audit를 같은 DB transaction에서 commit한다.
같은 expected version의 경합 loser와 stale command는 policy·receipt·success audit zero-write로 conflict를
반환하고, audit 또는 receipt 기록 실패도 전체 transaction을 rollback한다. 권한·scope 거부는 policy와
receipt를 만들지 않으며 기존 security audit policy가 요구하는 safe `permission.denied` audit만 허용한다.

### 17. 실행 policy는 고정하되 보안 lifecycle은 재검증한다

Effective V2 strategy는 다음 교집합으로 결정한다.

```text
전역 feature flag와 emergency kill switch가 허용
AND 지원되는 immutable strategy registry
AND current contract와 일치하고 상태가 `limited_canary` 또는 `production_active`인 유효 activation profile
AND profile에 고정된 exact Judge-only 또는 approved learner requirement source가 current
AND profile 상태가 허용하는 production scope 또는 stable canary에 포함된 deployment
AND workflow deploy 권한자가 선택한 policy
AND Judge와 각 work candidate/fallback을 승인하는 current V2 credential policy
AND 현재 Worker가 profile의 최소 runtime capability를 충족
AND profile에 고정된 exact non-V2 rollback policy version이 current-valid
AND global kill과 선택 profile-bound safety generation/block/epoch가 current
```

Runtime은 실행 시작 시 strategy contract, activation profile과 workflow policy version을 snapshot으로
고정한다. 일반 policy 변경과 정상 promotion의 `superseded` 전이는 새 실행부터 적용한다. Emergency
kill switch, generation-scoped safety block,
rollback policy/credential/model revoke, provider 비활성화와 organization scope 상실은 snapshot보다
우선하며 Judge, primary와 fallback provider 호출 직전에 재검증한다. Rollback policy가 current-valid하지
않으면 새 V2 attempt를 시작하지 않고 `rollback_target_invalid`로 닫는다. 아직 시작하지 않은 V2 판정은
승인된 stored safe path로 전환하고, 이미 발행한 provider attempt의 outcome은 추측하지 않는다.

Emergency lifecycle은 단일 전역 epoch로 모든 family를 함께 무효화하지 않는다. Environment 전체
kill switch는 `global_routing_kill_epoch`로 관리한다. Activation domain guard는 monotonic
`scoped_routing_safety_generation`을 할당하고, profile disable/rollback/expiry와 blocking safety
evidence는 `(environment, rollout_family, activation_domain, generation)`에 결합한
`scoped_routing_safety_epoch`와 deny-only safety block으로 관리한다. ProviderExecutionCapability는 발급 시점의 global epoch, exact profile-bound generation/epoch와 함께
organization authorization fence, credential policy/credential, model/provider lifecycle 및 rollback policy의
immutable current revision을 binding한다. Global epoch가 stale하면 모든 family가, 선택 generation의 epoch가
stale하거나 block이 set이면 그 generation만 provider I/O 없이 거부된다. Lifecycle revision 하나라도
stale하거나 current state가 deny면 해당 attempt를 거부한다. Production predecessor와 limited-canary
successor는 각자 generation을 가지므로 한쪽 block이 다른 쪽을 암묵적으로 해제하거나 무효화하지 않는다.
겹치지 않는 다른 family/domain capability도 자신의 global/generation/lifecycle revision이 current이면
유지된다.

`provider_started` 전이는 위 비교와 분리된 blind write가 아니다. Runtime은 짧은 DB transaction에서
동시 provider start를 허용하는 shared fence를 다음 순서로 획득한다.

```text
environment guard
-> organization authorization fence
-> credential policy and credential lifecycle
-> model and provider lifecycle
-> rollback policy
-> optional sealed snapshot
-> exact generation safety row
-> provider attempt
```

Runtime은 모든 capability-bound revision/state와 attempt expected state를 다시 검증해 `provider_started`를
원자 전이한다. Organization scope/permission, credential policy/credential, model/provider 또는 rollback
policy revoke/disable mutation은 자신이 변경하는 동일 authoritative fence row를 exclusive하게 획득하고
revision을 증가시킨다. 다수 row를 변경하는 mutation도 위 공통 순서를 따른다. Global kill은 environment
guard의 exclusive mutation fence, blocking breach는 environment shared fence 뒤 optional sealed snapshot과
exact generation safety row의 exclusive mutation fence를 사용한다. Scoped breach는 다른 generation start를
직렬화하지 않는다. Provider/network I/O는 provider-start transaction이 commit된 뒤에만 시작한다.

어떤 lifecycle revoke/kill/breach transaction이 먼저 commit하면 대기한 start는 stale revision/state를 보고
`provider_started`와 provider I/O zero-write로 닫는다. Provider-start transaction이 먼저 commit하면 그
attempt만 이미 시작 승인을 얻은 것으로 보며 이후 revoke는 다음 start부터 차단한다. Bounded fence timeout
또는 serialization retry 소진은 fail-closed하며 lock을 잡은 동안 network I/O를 수행하지 않는다. RBAC
판정이 여러 grant row에 의존하면 start와 revoke가 공유하는 monotonic organization authorization fence
revision을 사용해 grant set 변경을 원자적으로 관측한다.

Scoped block은 false에서 true로만 전이하는 안전 marker이며 activation이나 scope 확대에 사용할 수 없다.
Breach가 난 lifecycle generation의 block은 in-place로 해제하지 않는다. Remediation을 반영한 새 immutable
profile은 locked holdout과 독립 canary-start 승인을 통과한 시점에 Coordinator가 새 generation을
할당하고 `limited_canary` scope에만 capability를 발급한다. 이 canary 시작은 기존 blocked generation을
변경하거나 production scope를 열지 않는다. Blocked predecessor를 non-target fallback으로 사용하지 않고
profile에 고정된 current-valid non-V2 rollback policy를 사용한다. 새 generation에서 canary evidence를
충족하고 별도 독립 production 승격을 통과한 뒤에만 같은 generation을 production claim으로 전환한다.
기존 blocked generation이 `limited_canary` successor claim을 소유한다면 권한 있는 emergency
disable/rollback command가 그 claim을 먼저 terminal하게 닫아 successor slot을 비워야 한다. 이 종료는
기존 generation의 block을 해제하지 않으며, 새 canary start는 그 뒤 다음 generation만 할당한다.

Environment guard는 `global_routing_kill_enabled`, monotonic `global_routing_kill_epoch`와 guard
revision을 함께 소유한다. 권한 있는 `platform routing operator`만
`global_routing_kill_enable | global_routing_kill_disable` command를 제출할 수 있다. Enable은 즉시
fail-safe 차단할 수 있지만, disable은 kill을 건 actor와 다른 독립 승인자와 current remediation
approval revision을 요구한다. Canonical request는 command kind, environment, desired state, expected
guard revision/epoch, bounded reason과 disable의 recovery approval revision을 포함한다.
`RoutingActivationCoordinator`는 environment guard row를 잠그고 commit 직전에 actor 권한, expected
state/revision/epoch와 recovery approval을 다시 검증한다. 성공한 true/false 상태 전이는 모두 epoch와
guard revision을 한 번 증가시키고, enabled state·receipt·canonical audit와 같은 transaction에
commit한다. Kill이 enabled인 동안 새 V2 capability를 발급하지 않는다. Disable 뒤에도 기존 capability를
되살리지 않고, current profile·policy·scope·credential·rollback·Worker gate를 다시 통과한 새 capability만
새 global epoch에 binding한다.

같은 command ID·actor·canonical request 재전달은 기존 receipt를 반환하고 epoch를 다시 증가시키지
않는다. 같은 ID의 다른 actor/request는 `model_routing.global_kill_command_conflict`, stale expected
state/revision/epoch 또는 동시 enable/disable loser는 `model_routing.global_kill_state_conflict`와
zero-write로 닫는다. 권한이 commit 전에 회수되거나 disable의 독립 recovery 승인이 없으면
enabled state·epoch·revision·receipt·success audit를 모두 쓰지 않는다. Canonical audit 또는 receipt
기록 실패도 전체 mutation을 rollback한다.

Mixed-worker rollout에서 V2 contract를 지원하지 않는 Worker는 V2 policy를 V1 의미로 실행하지
않는다. Producer task payload나 Client가 전달한 capability revision은 호환성 근거가 아니며 실제 소비
process의 code-owned build/runtime identity를 검사한다. 해당 delivery는 current-valid non-V2 path로 명시적으로 전환하거나 provider I/O 전 typed
failure로 닫으며, 호환 Worker 비율이 profile readiness를 충족하기 전에는 canary scope를 확대하지
않는다.

Strategy 등록·폐기, activation profile 작성·승인·만료·비활성화, activation-domain migration, workflow 선택과
rollback은 old/new version, bounded scope, actor, reason과 결과를 기록한다. Audit에는 raw prompt,
RAG 원문, credential과 provider payload를 넣지 않는다.

## 계약 완결성 매트릭스

이 표는 Target 구현이 한 경계만 부분 적용하지 않도록 불변조건부터 테스트까지 연결한다. 각 구현
이슈는 자신이 소유한 행의 공식 계약, 실제 구현 위치와 실행 가능한 테스트를 함께 제시해야 한다.

| 경계와 불변조건 | 상태 전이 | Actor/command와 canonical request | Lock/transaction | Cache/evidence identity | Provider I/O 순서 | Rollback | Audit | 테스트·소유 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Effective V2는 모든 current gate의 교집합이다 | requested V2 -> effective V2/non-V2/null | Trusted runtime resolver, pinned strategy/profile/workflow policy | 실행 snapshot 뒤 lifecycle은 호출 직전 재검증 | Profile/source/rollback/Worker/global + profile-bound safety generation/epoch | Gate 실패 시 Judge 포함 I/O 0회 | Exact current-valid non-V2 policy만 사용 | requested/effective/reason safe projection | `M365-A07B`~`A07D`, `F11`, `F24`, `F25`; MBA-366·Activation |
| Accepted cache는 승인 source를 바꾸지 않는다 | miss -> immutable fill 또는 exact hit | Runtime cache query/fill, selection contract key | Unique/CAS fill, 다른 contract overwrite 금지 | Organization/deployment/node, selection contract, profile/source, HMAC epoch | Hit 후 current gate와 selector, 필요 attempt admission | Stale/mismatch는 mandatory miss | 원 requirement source + reuse source, raw input 비저장 | `M365-D02`~`D03`, `E07`; MBA-367 |
| Requirement Judge는 billable 독립 attempt다 | needed -> admitted -> started -> terminal/outcome-unknown | Server-owned Judge invocation, exact capability와 budget | Durable intent가 commit된 뒤 provider call | Judge contract/rubric, Billing Principal, attempt ID | Current scope/lifecycle와 capability·budget·egress admission 뒤 Judge 호출 | Outcome-unknown이면 같은 decision의 Judge retry/secondary 0회, stored safe path도 독립 work-model admission | ADR-0069 ledger + bounded source/reason | `M365-A01`, `A07`, `A12`, `B05A`, `B11A`; MBA-366·Ledger |
| Primary/fallback은 각각 current admission을 통과한다 | selected -> admitted -> started -> terminal | Server selector와 attempt별 capability | Attempt intent/start/outcome 원장 경계 | Pinned selection contract와 current scope/model/credential | Current scope/lifecycle와 capability·budget·egress 재검증 뒤 호출 | Outcome-unknown 재시도 금지, definitive failure만 configured fallback | Attempt별 usage와 redacted routing trace | `M365-A07`, `B04`~`B11`; MBA-366·Ledger |
| Provider start와 모든 lifecycle mutation은 한 순서를 가진다 | admitted -> provider_started 또는 blocked | Runtime start gate, organization/credential/model/provider/rollback revoke와 kill/breach command | Environment -> authorization -> credential -> model/provider -> rollback -> optional snapshot -> generation -> attempt 공통 fence. Mutation은 affected row exclusive + revision 증가 | Bound global/generation epoch와 organization/credential/model/provider/rollback revision | Start commit 뒤에만 I/O, 어떤 revoke/kill/breach winner 뒤 I/O 0회 | Timeout/serialization 소진은 fail-closed, started winner는 replay 금지 | Start와 lifecycle mutation의 canonical ledger/audit 분리 | `M365-F20`~`F20A`, `F24E`~`F24E1`; MBA-366·Activation·Ledger |
| Operational evidence는 모델·요구 cohort·산출 계약·실행 attempt를 넘지 않는다 | terminal provider operation -> immutable event/receipt -> scoped aggregate/read | Operational evidence system, `record_operational_model_evidence`, server-derived operation identity | Event/receipt/aggregate delta 원자 commit, unique + aggregate lock/CAS | Reuse scope + task fingerprint + requirement cohort + model/evidence contract, 허용 work-model operation당 1회 | Append/read 중 provider I/O 없음 | Duplicate는 기존 receipt, conflict/missing/ineligible operation은 zero-write | Safe metric digest만, unknown은 positive로 승격 금지 | `M365-C08`~`C08K`; Model Profile·Ledger |
| Billable benchmark는 일반 workflow 실행이 아니다 | authorized command -> isolated run -> terminal | Benchmark operator + target `execute`, actor/request-bound command | Receipt/run intent commit, duplicate delivery dedupe | Proposed profile, target scope, budget, manifest, run ID | 각 attempt 직전 두 권한 재검증과 admission 뒤 호출 | Production policy로 fallback/재사용 금지 | Redacted command/run audit와 ledger | `M365-F26`~`F26D`; MBA-340·Benchmark |
| Rollout family는 명시적 command로 한 번 생성한다 | absent -> immutable family + assignment contract | Platform operator의 actor/request-bound `rollout_family_create` | Environment guard overlap lock + family/domain unique + CSPRNG seed/receipt/audit 원자 commit | Immutable family/domain/assignment contract, raw seed 입력·출력 금지 | Family 생성 중 provider I/O 없음 | Same request는 기존 family, overlap/concurrent conflict는 zero-write | Safe family/domain/contract digest만 기록 | `M365-F18A4`~`F18A6`; Activation |
| Canary start는 production scope를 열지 않는다 | proposed -> limited_canary + 새 generation | 독립 platform operator, expected profile/family/domain-claim revision과 domain generation | Coordinator가 guard/profile/generation/canary claim/receipt/audit 원자 commit | Exact source manifest, holdout, rollback, Worker readiness, profile-bound generation | Commit 전 provider I/O 없음 | Non-target은 current predecessor, predecessor가 blocked/없으면 exact non-V2 rollback | State/generation/claim/receipt/audit exactly-once | `M365-F08B`~`F08C`, `F18E`~`F18G`, `F24D1`; Activation |
| Canary assignment는 process와 profile revision에 독립적이다 | deployment -> stable bucket -> successor/predecessor | Server resolver, `rollout_family_create`가 발급한 assignment contract | Immutable contract ref/range를 profile propose 때 고정, raw seed 입력 금지 | Environment/family/domain/organization/workflow/deployment + contract/seed, profile revision·runtime random 제외 | Assignment 중 provider I/O 없음 | 같은 contract는 retry/restart 동일 bucket, 변경은 새 profile 승인 | Unit/seed 비노출, safe contract/range digest만 투영 | `M365-F18`~`F18A6`; Activation |
| Canary evidence는 source event당 한 번만 집계한다 | authoritative canary runtime event -> immutable event/receipt -> open-window aggregate 또는 snapshot invalidation | Evidence system의 `record_canary_evidence` | `activation_canary_runtime` allowlist + window-independent source identity unique + aggregate/snapshot lock, event/receipt/revision 원자 commit | Assigned window/metric contract/event kind/payload digest는 identity 밖 comparison field | Exact duplicate는 receipt, 다른 window 재사용이나 mismatch는 conflict/zero-write | Ineligible holdout·benchmark source zero-write | Blocking canary runtime event만 exact generation block/audit 원자 기록 | `M365-F08D2`~`F08D4`, `F26E`; Activation·Benchmark |
| Canary snapshot은 명시적으로 봉인한다 | open window -> sealed snapshot + next window | Evidence system의 actor/request-bound `seal_canary_evidence_window` | Window pointer -> aggregate -> watermark lock, expected revision/watermark 재검증, snapshot/receipt/audit 원자 commit | Cutoff, aggregate revision, source watermarks와 immutable snapshot hash | Seal 중 provider I/O 없음 | Append winner는 재제출, seal winner 뒤 post-cutoff event는 next window | Same request exactly-once, conflict/audit failure zero-write | `M365-F08D0`~`F08D0B`; Activation·Benchmark |
| Production promote는 sealed evidence에 결합한다 | limited_canary generation -> production_active, predecessor가 있을 때만 superseded | 독립 operator, actor/request + expected profile/family/domain-claim/`expected_snapshot_invalidation_revision` | Guard -> profile/family/domain claim -> exact snapshot/safety lock, invalidation 재검증 | Generation-bound sealed snapshot ID/revision/hash, `snapshot_invalidation_revision`과 source watermark | Promotion transaction 중 provider I/O 없음 | 최초/blocked predecessor non-target은 승격 전까지 exact non-V2 rollback | Success cutover만 audit, stale evidence zero-write | `M365-F08D`, `F08D0`~`F08D3`, `F18B`~`F18B1`, `F18H`, `F24D2`; Activation·Benchmark |
| Expiry는 scheduler 지연에도 fail-closed다 | active/proposed -> expired | Lifecycle system의 deterministic expire command | DB clock/expected revision 아래 state/receipt/audit commit, exact owner claim/generation만 조건부 무효화 | Profile ID/revision/valid_until + owner claim role/generation | Resolver가 DB time 기준으로 먼저 V2 I/O 차단 | Exact current-valid non-V2 policy 또는 typed failure | System actor와 bounded reason만 기록 | `M365-F11C`, `F18I`~`F18I2`; Activation |
| Environment global kill은 전용 command로만 전이한다 | disabled <-> enabled, 매 성공 전이마다 global epoch 증가 | Platform operator enable, 독립 recovery 승인자가 disable; actor/request-bound command | Environment guard CAS lock, state/epoch/revision/receipt/audit 원자 commit | Environment + global epoch, 기존 capability 부활 금지 | Enabled 동안 발급 0회, stale capability는 provider_started 전 거부 | Disable 뒤 current gate를 통과한 새 capability만 발급 | State transition exactly-once, raw incident data 비저장 | `M365-F24B`~`F24B4`; Activation |
| Emergency와 late breach는 영향 generation만 차단한다 | active generation -> deny-only block, remediation -> 새 limited-canary generation | Evidence system의 source-bound append command, operator emergency command, 독립 canary-start command | Evidence/block/epoch/audit 또는 새 profile/generation/claim/receipt/audit를 각 원자 commit | Exact profile-bound lifecycle generation | Blocked generation은 provider_started 전 거부, 새 generation은 canary target만 허용 | Breached generation 해제 금지, blocked canary claim 종료 뒤 새 generation, canary evidence 뒤에만 production | Breach evidence와 lifecycle audit 분리 | `M365-F08D2`, `F10`, `F24`, `F24A`, `F24C`~`F24D3`; MBA-366·Activation |
| Workflow 선택은 activation mutation이 아니다 | absent/selected/opt_out -> 새 policy version | Workflow `deploy` actor, workflow request hash | Nullable-first CAS, commit-time 권한 재검증, receipt/audit 원자성 | Workflow policy version + strategy + immutable rollout family/domain binding, exact profile은 run snapshot에서 해소 | Policy write 자체 provider I/O 없음 | Opt-out은 명시적 non-V2 version | Same request exactly-once, promotion 뒤 policy write 없이 새 run만 successor | `M365-F19A`~`F19G`; Activation |

## MBA-340 계획·구현 Gap 분류

이 표의 분류는 다음 의미다.

- `계획과 다르게 구현`: MBA-340 또는 Accepted 계약과 다른 의미로 현재 코드에 도달했다.
- `계획됨·미완결`: 방향은 있었지만 실행 경계, version 또는 테스트가 완결되지 않았다.
- `계획 누락`: MBA-340에 production 안전을 위해 필요한 계약이 충분히 없었다.

| 영역 | 분류 | Current gap | 이 결정의 Target | 검증·소유 |
| --- | --- | --- | --- | --- |
| V1/V2 격리 | 계획과 다르게 구현 | V2 의미가 V1 strategy ID 아래 실행되고 기존 row에 contract version이 없다 | 명시적 ADR-0059 V1, 독립 V2, ambiguous row safe-path 전환 | `M365-D01`, `M365-D01A`, `M365-D01B`; Strategy Registry/Cutover 후속 |
| Judge 책임·축 | 계획됨·미완결 | 3축 요구 판정은 구현됐지만 strategy·rubric 계보가 섞였고 고정 `OUTPUT_CONTRACT`도 Current Judge 입력에 포함된다 | bounded 3축 Judge, 모델 선택 금지, output/schema는 server structural hard gate, rubric 회전 | Current `FR-011-P13`, Target `M365-A01`, `M365-A02`, `M365-A11`; MBA-366·368 |
| Secondary Judge | 계획 누락 | 호출·병합·비용 상한의 canonical contract가 없다 | 동일 schema, 최대 1회, budget과 adjudication 기록 | MBA-366 또는 별도 후속 |
| Task intent | 계획과 다르게 구현 | 누락값이 `generate`로 승격된다 | 누락=`unspecified`, server-derived 하한 우선 | `M365-A03`~`M365-A06`; MBA-366 |
| Server selector | 계획됨·미완결 | 수동 score와 단순 가격 비교 의존도가 높다 | hard gate 뒤 전체 비용·지연·품질과 deterministic tie-break | `M365-A08`, `M365-A09`, `M365-B01`~`M365-B03`; MBA-366·Ledger 후속 |
| 미검증 후보 | 계획과 다르게 구현 | 일반 운영 경로에서 선택될 수 있다 | low-risk bounded canary 외 proven safe baseline | `M365-C04`~`M365-C07`; MBA-366·Model Profile 후속 |
| Model evidence | 계획됨·미완결 | source/version/freshness, task semantic/model scope, eligible purpose/mode와 duplicate terminal finalizer 수렴이 불완전하다 | 재사용 scope가 같은 versioned profile과 eligible ADR-0069 operation-bound exactly-once sample append | `M365-C01`~`M365-C03`, `M365-C08`~`M365-C08I`; Model Profile·Ledger 후속 |
| Safe fallback | 계획됨·미완결 | pre-I/O reselection, 저장 기본·대체와 current gate가 분산돼 있다 | 원래 후보 내 1회 reselection과 definitive failure 뒤 configured fallback 재검증 | `M365-B01B`, `M365-B06`, `M365-B07`, `M365-B10`, `M365-B10A`; MBA-366 |
| Subject 없는 data scope | 계획 누락 | public·schedule·system actor와 데이터 접근 주체의 관계가 V2에 명시되지 않았다 | ADR-0018 anonymous public-only, synthetic owner/user/credential subject 금지 | `M365-A07A`~`M365-A07A4`; MBA-366·Knowledge 연동 |
| Credential principal·provider purpose policy | 계획 누락 | execution subject와 credential principal이 섞이고 ADR-0064의 단일 exact-model policy로 다중 후보 권한을 표현할 수 없으며 RAG query embedding도 별도 purpose가 필요하다 | server-derived principal, Judge·candidate별 model-bound policy, ADR-0071 query-embedding policy 분리, 미구현 시 V2 비활성 | `M365-A07`, `M365-A07A`, `M365-A07B`, `M365-A07C`; Provider Candidate Credential Policy 후속·MBA-351·320 |
| Requirement/selection contract | 계획됨·미완결 | learner와 cache의 소비 의미가 하나의 계보처럼 섞이고 고정 작업 의미 변경 뒤 learner 재사용 위험이 있다 | task semantic fingerprint가 포함된 requirement digest와 selection digest 분리, top-level provenance | `M365-D02`, `M365-D04`, `M365-D04B`, `M365-D04C`; MBA-367·368 |
| Accepted decision cache | 계획됨·미완결 | task/output/effect/strategy/profile·tenant/node binding이 부족하다 | selection contract, scoped namespace와 cache key epoch binding, current gate 재검증 | `M365-D02`, `M365-D02A`, `M365-D02B`, `M365-D03`, `M365-E07`; MBA-367 |
| Learner gate | 계획과 다르게 구현 | 구현은 100/50/75%, Accepted 계약은 50/20/80%이고 새 candidate가 active policy에 자동 연결될 수 있다 | 50/20/80은 candidate gate일 뿐이며 activation profile이 exact Judge-only 또는 approved learner version을 고정 | `M365-D04`~`M365-D06`, `M365-F08A`, `M365-F08E`~`M365-F08H`; MBA-368·Activation 후속 |
| Rejected label | 계획과 다르게 구현 | batch가 rejected label을 classifier에 반영한다 | 평가 분모에만 포함하고 training count/weight 제외 | `M365-D07`; MBA-368 |
| Nested identity | 계획됨·미완결 | terminal node ID 중심 경로가 남아 있다 | canonical location과 invocation/iteration identity 분리 | `M365-D09`, `M365-D10`; MBA-369 |
| 관측 source | 계획과 다르게 구현 | `decision_source`가 strategy 해석·요구 판정·선택·재사용을 혼합한다 | requested/effective strategy와 resolution reason 뒤 effective V2의 세 source enum 분리 | `M365-E01`~`M365-E11`; MBA-366·367 |
| 경제성 admission·전체 비용 | 계획 누락 | Judge/retry/fallback 비용보다 절감이 작은 호출도 가능하다 | pre-Judge admission과 모든 attempt 비용 | `M365-B01`~`M365-B05`; MBA-366·Ledger 후속 |
| Budget·usage 귀속 | 계획 누락 | Judge·primary·fallback의 budget admission과 Billing Principal 귀속이 selector 계약에 없다 | attempt별 capability/budget admission과 ADR-0069 종결 | `M365-B11`; MBA-366·ADR-0064/0069 연동 |
| 저빈도 workflow | 계획 누락 | local 전환 전 Judge 비용이 장기 지속될 수 있다 | fixed safe path와 경제성 기반 bounded routing | `M365-D08`; MBA-366·368 |
| Cache·learner 동시성 | 계획됨·미완결 | key rotation, concurrent fill·promotion·finalizer 수렴 계약이 불완전하다 | key epoch 회전, CAS/unique identity와 exactly-once count | `M365-D02A`, `M365-D04A`, `M365-D10A`; MBA-367·368·369 |
| 실험 재현성·raw artifact | 계획 누락 | SHA/dataset/contract version, validity와 retention이 불충분하다 | locked holdout, complete manifest, redacted Git report | `M365-E05`, `M365-F01`~`M365-F07`; Benchmark 후속 |
| Activation actor·profile | 계획 누락 | 일반 deploy 권한과 platform rollout 경계가 없고 서로 다른 family의 domain 경합이 직렬화되지 않는다 | exact requirement source가 있는 사전 등록 profile, 독립 승인, stable canary, environment coordinator와 actor 분리 | `M365-F08`~`M365-F18G`, `M365-F21`~`M365-F23`; Activation 후속 |
| 실행 snapshot·긴급 revoke | 계획 누락 | 실행 중 policy 변화와 lifecycle 우선순위가 불명확하다 | strategy/profile/policy pin, revoke/emergency 우선 | `M365-B10`, `M365-F19`, `M365-F20`, `M365-F24`; MBA-366·Activation 후속 |
| Preview·benchmark·mixed worker | 계획 누락 | Side-effect 없는 preview와 billable diagnostic, 구형 Worker의 V2 해석 경계가 불명확하다 | mode 분리, requirement pending, 실제 소비 Worker의 code-owned runtime capability readiness | `M365-A10`, `M365-F25`, `M365-F25A`, `M365-F26`; MBA-366·Benchmark·Activation 후속 |

## Current와 Target

### Current

- 실행 가능한 strategy ID는 `judge_bootstrap_incremental_v1` 하나다.
- Requirement Judge는 세 축 요구 능력만 반환하고 서버가 후보를 선택하므로 ADR-0059의 Judge 직접
  선택 설명과 다르다.
- 누락 task intent는 `generate`로 처리된다.
- learner gate 구현값은 `100 labels / recent 50 / exact 75%`로 ADR-0059와 다르다.
- accepted decision cache는 current output/effect/strategy contract를 완전히 binding하지 않는다.
- Client의 현재 Judge 상세는 구형 candidate-selection 문구와 후보 수 projection을 표시한다.
- routing activation profile, platform operator와 V2 execution snapshot은 구현되지 않았다.
- V1 row에 immutable legacy contract digest가 없으므로 V2 rollback 적격성을 증명할 수 없다.

### Target

- `capability_routing_v2`를 V1과 분리하고 기본 비활성으로 등록한다.
- Requirement Judge와 learner는 requirement contract를, server selector와 cache는 selection contract를
  공유하며 top-level routing contract가 실행 provenance를 결합한다.
- 아래 활성화 게이트를 모두 통과하기 전 production V2 activation은 허용하지 않는다.

## 활성화 게이트

1. 이 결정과 PRD, architecture, requirements, API, component와 test cases가 같은 책임을 설명한다.
2. V2 strategy가 V1 policy/cache/learner와 격리되고 기본 비활성이다.
3. 기존 V1 row는 legacy contract로 식별되고, 재검증·재발행하지 않은 row를 V2 rollback target으로
   사용하지 않는다.
4. MBA-366의 task intent, hard gate, selector, fallback과 source 테스트가 통과한다.
5. MBA-367의 cache contract digest와 current revalidation 테스트가 통과한다.
6. MBA-368의 learner rotation, threshold와 rejected label 테스트가 통과한다.
7. MBA-369의 canonical node location과 invocation identity 테스트가 통과한다.
8. Model profile provenance/freshness와 attempt/cost ledger가 구현돼 versioned evidence를 제공한다.
9. Strategy registry, idempotent rollout family/assignment contract 생성, activation profile 승인·scope,
   stable canary, 명시적 evidence snapshot seal, execution snapshot과 audit가 구현된다.
10. Locked holdout에서 사전 등록 profile의 품질, 전체 비용, p95 지연, high-risk 과소판정과 fallback
   기준을 사전 등록한 표본·confidence 조건과 함께 만족한다.
11. Diagnostic mode 뒤 limited canary와 V2-off rollback을 검증한다.
12. Manifest가 완전하고 run status가 `valid`이며 tuning/holdout 누수가 없다.
13. Activation·selection·rollback audit idempotency와 secret·PII redaction을 검증한다.
14. Judge·primary·fallback의 capability-bound budget admission, cache/learner 동시 수렴과
    mixed-worker compatibility gate를 검증한다.
15. Activation profile이 exact Judge-only 또는 approved learner version을 고정하고 candidate learner
    발행·교체가 profile을 자동 변경하지 않음을 검증한다.
16. Tenant operational evidence가 organization·workflow·canonical node location, task semantic
    fingerprint와 contract version, model ID와 evidence contract version이 같은 실행에만 재사용됨을
    검증하고, 동일 ADR-0069 provider usage operation의 순차·동시 terminal finalizer 재전달이 표본 하나와
    receipt 하나로 수렴함을 검증한다.
17. 서로 다른 rollout family의 overlapping activation command는 environment coordinator가 직렬화해
    winner 하나만 domain claim/state/receipt/audit를 commit하고, non-overlap command는 같은 guard revision을
    읽었더라도 domain-local CAS로 둘 다 순차 성공함을 검증한다.
18. Subject 없는 public·webhook·schedule·API·system 실행이 ADR-0018 anonymous public-only로 제한되고
    owner·actor·credential principal을 private data subject로 합성하지 않음을 검증한다.
19. ADR-0064를 확장하는 Accepted credential policy가 Judge와 각 primary/fallback exact model을
    server-derived credential principal에 binding하고 public·schedule·system actor 승격을 금지한다.
20. RAG 사용 scope는 ADR-0071 query-embedding policy/capability와 MBA-320 activation을 통과하며,
    V2 Judge/main-generation policy가 query embedding 권한을 대신하지 않는다.
21. Canary evidence의 unique source identity가 canary window·payload digest·metric contract·event kind를
    포함하지 않고, 같은 source event의 다른 window 재사용이나 comparison field 변경이 conflict와 aggregate
    zero-write로 닫힘을 검증한다.
22. Blocking breach 뒤 remediation profile의 canary-start가 기존 generation을 해제하지 않고 새
    limited-canary generation을 열며, proposed/canary/production expiry가 자신이 소유한 claim과 generation
    밖에 영향을 주지 않음을 검증한다.
23. `rollout_family_create`가 CSPRNG assignment contract, receipt와 audit를 원자 생성하고 replay/overlap
    경합을 zero-write로 닫으며 non-overlap family는 각각 생성할 수 있음을 검증한다.
24. `seal_canary_evidence_window`가 expected aggregate/watermark 아래 immutable snapshot과 next-window pointer를
    exactly-once로 만들고 append와의 경합 winner에 따라 포함 또는 next-window 분리가 결정됨을 검증한다.
25. Organization authorization, credential policy/credential, model/provider와 rollback policy revoke가
    provider-start와 같은 lifecycle fence를 사용해 revoke winner 뒤 `provider_started`와 provider I/O가
    0회임을 검증한다.

하나라도 충족하지 못하면 V2를 기본 활성화하지 않는다. Learner candidate가 50/20/80 기준을
통과했다는 사실만으로 production activation을 승인하지 않는다.

## 구현 소유권

- MBA-340: 별도 V2 strategy, 실험 harness와 fixed baseline 비교
- MBA-366: task intent, server hard gate/selector, safe fallback과 canonical source
- MBA-367: accepted decision cache contract digest와 current state 재검증
- MBA-368: learner contract rotation, threshold와 rejected label 경계
- MBA-369: canonical nested location과 invocation label identity
- MBA-372: 하위 변경 통합, 활성화 적격성 검증과 최종 `dev` 병합
- MBA-351: RAG query-embedding purpose/policy/capability 경계
- MBA-320: query-embedding target runtime과 mixed-version rollout 활성화
- 후속 이슈: Provider Candidate Credential Policy, model profile evidence registry, routing attempt/cost
  ledger, benchmark governance, V1 compatibility contract tagging/cutover와 strategy activation governance

## 결과

### 장점

- LLM의 요구 분석과 서버의 권한·capability·비용 판정을 분리한다.
- V1/V2 의미와 cache·learner 계보가 섞이지 않는다.
- 최적화 비용이 절감액보다 커지는 요청과 미검증 high-risk 모델 사용을 차단한다.
- 코드 릴리스, 플랫폼 승인과 tenant workflow 선택이 서로의 권한을 대체하지 않는다.
- 실행 의미를 version으로 보존하면서 revoke와 emergency disable은 즉시 적용한다.

### 비용과 복잡성

- Strategy registry, profile evidence, manifest, activation profile과 운영 승인 경계가 필요하다.
- 기존 V1 policy, cache와 learner를 V2로 자동 재사용할 수 없다.
- Source/version 필드, attempt ledger와 rollout 테스트가 늘어난다.
- Platform routing operator 구현 전에는 production 활성화를 release artifact로만 관리해야 한다.

## 검토한 대안

### Judge가 후보 중 모델 ID까지 직접 선택

Credential, provider availability, 가격과 private 운영 상태를 Judge에 노출하거나 응답을 다시
광범위하게 검증해야 하므로 채택하지 않는다.

### 기존 V1 strategy ID의 의미만 변경

기존 policy, cache, learner와 trace를 같은 계약으로 오인하게 하므로 채택하지 않는다.

### 모든 기준을 하나의 가중 score로 계산

가격이나 prior가 권한·기능·안전 hard gate를 상쇄할 수 있으므로 채택하지 않는다.

### 최근 실험값에 맞춰 learner 기준을 `100 / 50 / 75%`로 변경

Locked holdout 근거가 없고 기존 품질 기준을 조용히 낮추므로 채택하지 않는다.

### 개발자 배포 또는 learner gate 통과로 production을 자동 활성화

독립 승인, canary, tenant opt-out과 rollback 준비를 우회하므로 채택하지 않는다.

### 일반 organization manager가 전역 activation profile을 변경

Tenant 관리 권한이 플랫폼 전체 rollout 권한으로 상승하므로 채택하지 않는다.
