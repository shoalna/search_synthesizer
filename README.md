# Search Agents

---

複数 Search Agent が並行して多角的な Web 検索を行い、取得した Evidence を統合して総合報告を生成する Multi-Agent Search System。

Search Agent は同じ結論を出すために複製するのではなく、それぞれ異なる `SearchAssignment` を担当する。必要に応じて反証探索 (`challenge_search`) も行うが、反対意見の存在や賛否の均等配置を前提にはしない。

本システムでは OpenAI の managed agent / built-in Web Search の利用を前提とする。


## Goal

---

* Search Agent が与えられた SearchAssignment に対して、有効かつ十分な Web 検索を実施できる。

* Search Agent が取得した情報について、SourceDocument と atomic Claim を保持し、最終出力まで provenance を追跡できる。

* Synthesizer は Search Agent が retrieve した Evidence のみを根拠として、全面的かつ偏らない総合分析を生成できる。

* cross-agent の数値的 conflict を検出し、必要な場合のみ追加検索を行う。

* 検索の成功、情報未発見、budget exhaustion、timeout、provider failure を明確に区別する。

* 検索品質・cost・latency・tool usage を記録し、後から harness の性能評価と tuning ができる。

  


## Design Principles

---

1. **Formatter が WHAT を決める**
   * 何を調べるかは `SearchAssignment[]` として Formatter が生成する。
2. **SearchPolicy / CoverageSpec が HOW / WHERE を決める**
   * channel、language、timeframe、geography、challenge search 等の Search Agent 個別及び横断ポリシーを管理する。
3. **Managed Agent の内部 query を architecture の主要単位にしない**
   * provider が返せる場合は telemetry として記録するが、Orchestrator の主要制御単位は `SearchAssignment / Round / AgentTurn` とする。
4. **Raw Claim は immutable**
   * normalization、conflict 判定、analysis によって元の Claim を書き換えない。
5. **Duplicate と Independent を混同しない**
   * duplicate でないことは independent origin の証明ではない。
6. **Hard limit 到達を COMPLETE とみなさない**
   * budget / timeout 等による停止は `PARTIAL` として扱う。
7. **Conflict は強制的に勝者を決めない**
   * 判断不能なら `UNRESOLVED` を正常な結果として許可する。
8. **Final Claim まで provenance を保持する**
   * ReportClaim → Claim → SourceDocument → URL / locator を追跡可能にする。



## Example

---

### User

```text
キオクシア
```



### Formatter

Formatter は単なる Prompt 文字列ではなく、構造化された `SearchAssignment[]` をユーザキーワードから生成する。

キーワードによるレンダーリングの内容もしくは固定内容を生成する。

例：

```yaml
search_assignments:
  - assignment_id: historical_etf_impact
    required: true
    objective: >
      ETF分配金発生時のキオクシア株価への過去影響を調査する。
      影響時期、影響期間、値動きの大きさを確認する。
      ETF分配金の規模と株価への影響度の関係を調査し、過去の規模と比較しキオクシアへの影響度を確認する。
      同一セクター企業に対するETF分配金発生時の影響を比較する。

  - assignment_id: iran_effect
    required: true
    objective: >
      現在のイラン情勢変化を確認する。過去も同じ変化があるとき、株市場とキオクシアへの影響を確認する。

  - assignment_id: america_effect
    required: true
    objective: >
      昨日のアメリカ株の状況を調査する。アメリカ同セクターの会社の株価変化はどのような影響があるか調査する。
```

SearchAssignment の数により起動する Search Agent の数が決まる。

Search Agent は単に `<keyword> 関連ニュース` を検索するのではなく、割り当てられた objective を判断するための Evidence を検索する。



## Architecture

---

```mermaid
flowchart TD
    User[User Input]
    Formatter[Formatter]
    Assignments[SearchAssignment Array]
    Policy[SearchPolicy / CoverageSpec]
    Orchestrator[Orchestrator]

    subgraph SearchAgents[Managed Search Agents]
        AgentTurn[Agent Turn]
        WebSearch[OpenAI built-in web_search]
    end

    EvidenceStore[Global Evidence Store]
    Dedupe[Global Deduplicator / Provenance Resolver]
    Normalize[Numeric Claim Normalizer]
    Conflict[Conflict Detector]
    Followup[Neutral Follow-up Search]
    Synthesizer[Synthesizer]
    Validator[Citation / Entailment Validator]
    Renderer[Markdown Renderer]
    Output[(report.md)]

    User --> Formatter
    Formatter --> Assignments
    Assignments --> Orchestrator
    Policy --> Orchestrator

    Orchestrator --> AgentTurn
    AgentTurn --> WebSearch
    WebSearch --> AgentTurn
    AgentTurn --> EvidenceStore

    EvidenceStore --> Dedupe
    Dedupe --> Normalize
    Normalize --> Conflict
    Conflict -. unresolved material conflict .-> Orchestrator
    Orchestrator -. verification assignment .-> Followup
    Followup --> EvidenceStore

    Conflict --> Synthesizer
    EvidenceStore --> Synthesizer
    Synthesizer --> Validator
    Validator -. retry / omit / gap .-> Synthesizer
    Validator --> Renderer
    Renderer --> Output
```


## Component Responsibility

---

| Component | Responsibility | Implementation |
| --- | --- | --- |
| Formatter | User Input から SearchAssignment[] を生成 | Template + deterministic code |
| Orchestrator | assignment、round、budget、retry、state 遷移を制御 | deterministic code |
| Search Agent | assignment ごとの Web research | OpenAI / Claude managed agent |
| Global Evidence Store | AgentTurn / SourceDocument / Claim を保存 | code / database |
| Deduplicator | global duplicate 判定、declared provenance 管理 | code + optional semantic similarity |
| Numeric Normalizer | conflict 比較用の derived representation を作成 | LLM + deterministic normalization |
| Conflict Detector | comparable な numeric Claim 間の conflict 検出 | LLM + deterministic checks |
| Synthesizer | Evidence の統合・分析 | LLM / toolなし |
| Citation Validator | ReportClaim の evidence presence と entailment を検査 | LLM/NLI + deterministic checks |
| Renderer | validated JSON を Markdown 化 | deterministic code |



## Managed Agent Conception

---

Manged Agent を使用する。App 側で制御できない内容を明確にする。

```text
Task
  ↓
SearchAssignment[]
  ↓
Round[]
  ↓
Managed Agent Turn
  ↓
provider tool activity / telemetry
  ↓
URL[]
  ↓
SourceDocument[]
  ↓
Atomic Claim[]
```

### Query

`query` は Web Search provider が検索エンジンに渡す検索文字列を指す。

ただし managed agent を使う場合、1 AgentTurn 内で複数検索が行われる可能性があり、query が常に application 側から完全に観測・制御できるとは限らない。

そのため query は architecture の主要制御単位にせず、provider から取得可能な場合のみ `observed_queries` として telemetry に保存する。

### URL

検索によって発見された Web page の location。

```text
1 query -> N URL
1 URL -> 0 or 1 SourceDocument per retrieved version
1 SourceDocument -> N atomic Claims
```

同じ URL が異なる query / AgentTurn から発見されることは許容する。保存時に Global Evidence Store で deduplicate する。



## Formatter / SearchAssignment

---

Formatter は User Input を Template に埋め込み、Search Agent が担当する検索内容を `SearchAssignment[]` として生成する。

```json
{
  "assignment_id": "historical_etf_impact",
  "required": true,
  "objective": "ETF分配金発生時のキオクシア株価への過去影響を調査する",
  "status": "pending",
  "termination_reason": null
}
```

### Rules

* SearchAssignment が検索内容の dimension を表現する。

* `required = true` の assignment が `PARTIAL / FAILED` の場合、Task 全体も原則 `PARTIAL` とする。

* objective は Search Agent が範囲を過度に拡大しないよう十分具体化する。

  


## SearchPolicy / CoverageSpec

---

SearchPolicy は全 SearchAssignment に対する HOW / WHERE の横断ルール及び個別 Search Agent  channel ルール。

```yaml
search_policy:
  channels:
  		- assignment_id: historical_etf_impact
        preferred:
          - official
          - independent_news
        optional:
          - social
          - reddit

  challenge_search:
    required: true

  timeframe:
    from: 2026-09-01
    to: current

  geography:
    - global

  languages:
    preferred:
      - ja
      - en
    allow_other_languages: true
```

### Rules

* `challenge_search.required = true` は反証探索を行うことを意味する。
* 反証 Evidence が存在することを要求しない。
* preferred language 外の source が重要なら取得してよい。
* challenge search は SearchAssignment の反対結論を強制するものではない。



## Managed Search Agent

---

Search Agent は OpenAI managed agent を利用する。

主な capability は built-in Web Search のみに限定する。

```text
SearchAssignment
      ↓
Managed Agent Turn
      ↓
OpenAI built-in web_search
      ↓
Structured SearchAgentResult
```

managed harness 内部の検索計画、query generation、page retrieval 等は provider に任せる。

application 側では以下を管理する。

* SearchAssignment
* Round
* AgentTurn state
* SourceDocument / Claim
* duplicate detection
* budget / timeout
* conflict handling
* synthesis / validation


## Round / AgentTurn

---

* 1 SearchAssignment = N Round
* 1 Round = 原則 1 Managed Agent Turn
* 1 AgentTurn = N provider tool activity
* 1 AgentTurn = N SourceDocument

```json
{
  "agent_turn_id": "turn_123",
  "assignment_id": "historical_etf_impact",
  "round": 1,
  "status": "success",
  "source_document_ids": [
    "src_1",
    "src_2"
  ],
  "provider_usage": {
    "web_search_calls": 7,
    "observed_queries": []
  },
  "started_at": "...",
  "finished_at": "...",
  "error_type": null
}
```

### AgentTurn Status

```text
success
no_material_evidence
cancelled
provider_error
timeout
rate_limited
```

`no_material_evidence` は「事実が存在しない」という意味ではなく、設定した search policy / budget の範囲で material evidence を取得できなかったことを意味する。

provider usage は取得可能な範囲で記録する。取得不能な telemetry を Orchestrator の必須制御条件にしない。



## SourceDocument / Claim

---

Evidence の保存単位は `SourceDocument`。1 SourceDocument の内部に N atomic Claim を持つ。

```json
{
  "source_document_id": "src_123",
  "source": {
    "url": "...",
    "canonical_url": "...",
    "title": "...",
    "publisher": "...",
    "author": "...",
    "published_at": "...",
    "updated_at": "...",
    "retrieved_at": "...",
    "language": "en",
    "exact_content_hash": "...",
    "normalized_content_hash": "..."
  },
  "duplicate": {
    "duplicate_cluster_id": null,
    "duplicate_type": "none"
  },
  "declared_provenance": [],
  "claims": [
    {
      "claim_id": "cl_001",
      "text": "Company X launched Product Y in June 2026",
      "language": "en",
      "material_to_assignment": true,
      "locator": {
        "section": "...",
        "excerpt": "..."
      }
    }
  ]
}
```

### Claim Rules

* Claim は source の意味を変えず、可能な限り atomic に保存する。
* 原文の language と数値単位を保持する。
* Agent の推論を Claim に混ぜない。
* SourceDocument 内で複数 Claim を許可する。
* 同一 Claim が複数 SourceDocument に存在してよい。
* raw Claim は immutable。
* `no result` や execution error を empty Claim として保存しない。AgentTurn status に保存する。
* duplicate は Global Evidence Store側の Deduplicator が判断し付与。



## Duplicate / Provenance

---

真の information origin / independence は Web 上の観測だけでは証明できない場合が多い。

そのため `independent_origin` を強い事実として扱わず、以下だけを管理する。

```text
duplicate
near_duplicate
non_duplicate_observed
declared_provenance
unknown_provenance
```



### Duplicate 判定

優先順位：

1. canonical URL 一致
2. normalized content hash 完全一致
3. exact content hash 完全一致
4. near duplicate 判定（optional。semantic similarity 等）

`non_duplicate_observed` は「現在の判定方法で duplicate を検出していない」という意味であり、情報源が独立していることを保証しない。

### Declared Provenance

記事内に `according to ...` 等の明示的な出典が存在する場合のみ provenance link を記録してよい。

```json
{
  "source_document_id": "src_20",
  "declared_provenance": [
    {
      "type": "cites",
      "target_url": "..."
    }
  ]
}
```

### Global Dedupe

Duplicate 判定は Agent / Round 単位ではなく Task 全体の Global Evidence Store で実施する。

同じ SourceDocument を Agent A / Agent B が取得しても保存は1件とし、discovery metadata のみ複数保持してよい。


## Search End Condition

---

検索終了理由と Task / Assignment status を分離する。

### Status

```text
COMPLETE
PARTIAL
FAILED
```

### Termination Reason

```text
SATURATED
NO_MATERIAL_EVIDENCE
BUDGET_EXHAUSTED
TIMEOUT
PROVIDER_ERROR
RATE_LIMITED
CANCELLED
```

### Semantics

* `SATURATED` → COMPLETE にできる。
* `NO_MATERIAL_EVIDENCE` → 検索自体が正常に完了した場合は COMPLETE としてよい。ただし「対象事実が存在しない」とは断定しない。
* `BUDGET_EXHAUSTED / TIMEOUT` → PARTIAL。
* `PROVIDER_ERROR / RATE_LIMITED` → retry 後も回復しなければ PARTIAL または FAILED。
* Hard limit に達しただけで COMPLETE にしない。



## Search Saturation

---

Saturation は source 数だけでは判定しない。

少なくとも以下の両方を満たす場合を saturation candidate とする。

```text
no new non-duplicate observed sources
AND
no new material claims
```

推奨初期値：

```yaml
saturation:
  min_rounds_before_evaluation: 2
  consecutive_saturated_rounds: 1
```

この値は benchmark 結果により調整する。

`material claim` は SearchAssignment objective を直接支持・反証・説明し、現在の回答を実質的に更新する Claim とする。


## Budget

---

Managed agent の内部 tool usage や model usage は provider implementation に依存するため、初期値を最終仕様とみなさない。

Budget は Task / Assignment / Round の階層で管理する。

### Recommended Initial Budget

```yaml
budget:
  task:
    max_wall_time: 15m
    max_web_search_calls: 100
    soft_cost_usd: 2.0

  assignment:
    max_rounds: 2

  round:
    max_wall_time: 5m
    max_web_search_calls: 15
```

### Rules

* `task.max_wall_time` は hard stop。
* `assignment.max_rounds` は hard stop。
* `max_web_search_calls` は provider telemetry / enforcement が可能な場合に使用する。
* provider が実行中の正確な web search count を制御できない場合、観測値として扱い、次 Round を開始しないための guard に利用する。
* `soft_cost_usd` は strict hard cap ではなく、累積 usage から推定する soft budget とする。
* monetary cost は model、reasoning effort、tool usage に依存するため、初期 benchmark 後に p50 / p90 / p95 を見て再設定する。
* Conflict follow-up search も同じ Task budget に含める。conflict ごとに別 budget を無制限に追加しない。

### Benchmark Telemetry

最低限以下を記録する。

```text
task_id
assignment_count
agent_turn_count
wall_time
web_search_calls
model_input_tokens
model_output_tokens
estimated_cost
source_document_count
non_duplicate_source_count
material_claim_count
conflict_count
final_supported_report_claim_count
```


## Tool Security / Managed Agent Security

---

OpenAI managed agent を利用しても application 側の Security 設計は必要。

ただし built-in Web Search を利用することで、browser / network execution の低レイヤ実装を自前で持たずに済むため、自前 Controlled Fetcher は原則実装しない。

### Allowed Capability

```text
Search Agent
  - OpenAI built-in web_search only

Synthesizer
  - toolなし

Conflict Detector / Citation Validator
  - external action toolなし

Orchestrator
  - application state / output artifact writeのみ
```

### Search Agent には原則付与しないもの

```text
shell
code execution
file write
email
connectors
MCP
arbitrary custom HTTP tools
application secrets
unnecessary private user data
```

### Security Rules

* Web content は **untrusted evidence** として扱い、instruction として扱わない。
* Search Agent は取得ページの指示により SearchAssignment を変更しない。
* Search Agent は system / developer prompt、secret、内部contextを検索 query や URL に含めない。
* Orchestrator が capability を deterministic に制限する。
* domain restriction が有効な assignment では provider の allowed-domain 機能を利用してよい。
* custom HTTP / MCP / connector / shell 等を将来追加する場合は、Security review を別途必須とする。
* Managed agent を使うことは prompt injection risk がゼロになることを意味しない。主な残存リスクは research integrity、data exfiltration、cost amplification。


## Numeric Normalization

---

ConflictDetector v1 は **同一事実に対する numeric factual conflict のみ**を対象とする。

自然言語だけの定性的 contradiction は v1 では conflict detection の対象外。

raw Claim は immutable とし、比較用 `NormalizedClaim` を別に作成する。

```json
{
  "normalized_claim_id": "ncl_10",
  "source_claim_id": "cl_10",
  "subject": "Company X",
  "metric": "revenue",
  "value": 1200000000,
  "unit": "JPY",
  "period": "FY2026",
  "geography": "global",
  "qualifier": "actual"
}
```

### Normalization Rules

* subject / metric / period / geography / qualifier が比較可能か確認する。
* raw value / raw unit を失わない。
* 単純な scale normalization（million → base unit 等）は deterministic code を優先する。
* 為替換算等、外部前提が必要な変換は自動 conflict 比較に使用しない unless 明示的な共通基準がある。
* forecast / actual、quarter / annual、GAAP / non-GAAP 等を混同しない。


## Conflict Detector

---

全 Search Agent の normalized numeric Claim を確認し、比較可能な Claim 間だけ conflict candidate を生成する。

```json
{
  "conflict_id": "cf_12",
  "claim_a_id": "cl_10",
  "claim_b_id": "cl_55",
  "normalized_claim_a_id": "ncl_10",
  "normalized_claim_b_id": "ncl_55",
  "type": "numeric_disagreement",
  "status": "unresolved",
  "resolution_claim_ids": []
}
```

### Comparable Check

最低限以下を比較する。

```text
subject
metric
period
geography
qualifier
unit / scale compatibility
```

比較不能なものを conflict と判定しない。


## Follow-up Search

---

material な unresolved conflict に対してのみ verification SearchAssignment を生成する。

### Neutral Verification

Follow-up Search Agent にどちらかの Claim が正しいという前提を与えない。

```text
Claim A と Claim B は同一 subject / metric / period について矛盾している。
どちらも正しいと仮定せず、両者を検証できる最も直接的な source を探索する。
```

### Conflict Grouping

同一 `subject + metric + period + geography` に属する conflict は可能な限り group 化し、pair ごとに無制限に Agent を起動しない。

### Resolution Principles

単純な source count / majority vote では決めない。

以下を evidence として使用する。

1. claim type に対して最も直接的な authoritative source
2. subject / metric / period / definition の一致
3. explicit provenance
4. non-duplicate observed corroborating sources
5. source の publication / update timing

`official` を全 Claim に対する絶対優先ルールにはしない。

例：

* company revenue → audited / regulatory filing を優先
* product specification → official product documentation を優先
* market price → market data source を優先
* social reaction → community / social source が直接 Evidence

### Resolution Status

```text
resolved_a
resolved_b
compatible_after_normalization
superseded
unresolved
```

証拠が不足している場合は `unresolved` を正常な結果として Synthesizer に渡す。


## Synthesizer

---

Synthesizer は Evidence Store、Conflict status、SearchAssignment status のみを根拠に総合分析を生成する。

Web Search 等の外部 tool は持たない。

### ReportClaim

```json
{
  "report_claim_id": "rc_12",
  "type": "direct_fact",
  "text": "Company X's revenue increased while margin declined.",
  "evidence_claim_ids": [
    "cl_21",
    "cl_44"
  ],
  "conflict_ids": [],
  "status": "supported"
}
```

### ReportClaim Type

```text
direct_fact
derived_analysis
uncertain
unresolved_conflict
```

### Rules

* `direct_fact` は supporting Evidence Claim を必須とする。
* `derived_analysis` は推論自体と、その全 premise Claim を明示する。
* `unresolved_conflict` は conflict の両側 Evidence を保持する。
* Evidence がない factual claim を最終報告に出さない。
* Search Agent の source summary ではなく Claim / provenance を primary input とする。


## Citation / Entailment Validator

---

Renderer 前に ReportClaim を検査する。

### Validation 1: Citation Presence

```text
ReportClaim -> evidence_claim_ids が存在するか
```

### Validation 2: Entailment

```text
参照 Evidence Claim が ReportClaim の factual content を実際に support しているか
```

### Validation Policy

* factual ReportClaim は原則 100% supported を要求する。
* unsupported factual claim は割合で許容しない。
* `derived_analysis` は全 premise が Evidence により support されていることを確認する。
* Evidence があるのに Synthesizer の linking が間違っている場合 → re-synthesize。
* Evidence 自体が不足している場合 → claim を omit / uncertain とする。`uncertain` として出力する。
* contradictory Evidence が解決していない場合 → `unresolved_conflict` として出力する。

Synthesizer retry の初期上限は `max_retry = 2` とし、同じ原因で無限再生成しない。


## Orchestrator State

---

Task と SearchAssignment の状態を deterministic に管理する。

推奨 state：

```text
PENDING
SEARCHING
VALIDATING_EVIDENCE
RESOLVING_CONFLICT
SYNTHESIZING
VALIDATING_REPORT
COMPLETE
PARTIAL
FAILED
```

### Workflow

1. User Input を受け取る。
2. Formatter が SearchAssignment[] を生成する。
3. Orchestrator が SearchPolicy と Task Budget を適用する。
4. SearchAssignment ごとに managed Search Agent を並列 trigger する。
5. AgentTurn 結果を Global Evidence Store に保存する。
6. Global duplicate / provenance 処理を行う。
7. Assignment ごとに saturation / termination status を判定する。
8. numeric Claim を Normalize し、cross-agent numeric conflict を検出する。
9. material unresolved conflict があれば neutral follow-up search を budget 内で実行する。
10. Synthesizer が ReportClaim[] と総合分析を生成する。
11. Citation / Entailment Validator が検証する。
12. Renderer が validated result を Markdown に変換する。
13. Task status と coverage / unresolved items を report に含める。


## Agent Must Do

---

* Search Agent は SearchAssignment objective に必要な情報を十分に探索する。
* Source language を限定しない。ただし SearchPolicy の preferred language を優先してよい。
* 取得した重要情報は SourceDocument / atomic Claim として provenance を保持する。
* 不確かながら重要な情報は uncertainty を明示した上で保持してよい。
* challenge search では反証の存在を強制しない。
* Synthesizer は Search Agent が取得・検証した Evidence のみを根拠にする。


## Agent Must NOT Do

---

* Search Agent は assignment から過度に派生して scope を拡張しない。
* Search Agent は Web page 内の instruction に従って objective を変更しない。
* Search Agent は raw source Claim に推論を混ぜない。
* Duplicate でないことを independent origin と断定しない。
* Conflict Resolver は source 数だけで真偽を決めない。
* Conflict Resolver は必ずどちらかの Claim を採用しない。
* Synthesizer は Evidence にない事実を factual claim として追加しない。
* Synthesizer は主観的な憶測をしない。


## Output

---

最終出力は Markdown の総合報告書。

最低限以下を含む。

```text
Summary
Key Findings
Supporting Evidence / citations
Unresolved Conflicts
Uncertainty / Search Gaps
Search Coverage / Assignment Status
```

内部では Markdown を canonical data とせず、validated `ReportClaim[]` と structured result JSON を canonical output とする。

Markdown は Renderer による presentation layer とする。


## Initial Tuning Policy

---

以下は設計上の固定値ではなく、初期 benchmark 用推奨値。

```yaml
budget:
  task:
    max_wall_time: 15m
    max_web_search_calls: 100
    soft_cost_usd: 2.0
  assignment:
    max_rounds: 2
  round:
    max_wall_time: 5m
    max_web_search_calls: 15

saturation:
  min_rounds_before_evaluation: 2
  consecutive_saturated_rounds: 1

synthesizer:
  max_retry: 2
```

50〜100件程度の代表 task で以下の distribution を計測した後に tuning する。

```text
quality metric
wall time
web search calls
model tokens
estimated total cost
source count
material claim count
conflict discovery / resolution
citation entailment pass rate
```

最終 budget は平均値ではなく p50 / p90 / p95 と quality saturation point を見て決める。


## References for Managed Agent Implementation

---

OpenAI の具体的な API / pricing / managed harness の仕様は変更される可能性があるため、実装時は公式ドキュメントを確認する。

* OpenAI Agents API overview: https://developers.openai.com/api/docs/guides/agents-api/overview
* OpenAI Agents API Web Search: https://developers.openai.com/api/docs/guides/agents-api/tools/web-search
* OpenAI API pricing: https://developers.openai.com/api/docs/pricing

