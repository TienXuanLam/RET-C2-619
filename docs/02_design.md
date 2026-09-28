# Template Design Specification

## Position in AgentCore Architecture

- **Agent Class**: `RetailVendorRebateTradePromoReconciliationAgent`
- **L1 Base**: `AgentBaseGraph`
- **Pattern**: Cat 2 — flat backbone (outer `AgentBaseGraph`, no inner subgraph); DocGenerationAgent
- **Three-Layer Separation**:
  - State: flat TypedDict composition (no Pydantic — msgpack incompatible)
  - Node: L1 inheritance (Template Method: `execute(self, state: dict) -> dict` override only)
  - Graph: composition (`register_nodes()` for node substitution)

## Architecture Overview

`AgentBaseGraph` exposes exactly three domain slots — `pre_process`, `main`,
`post_process`. Unlike some Cat 2 templates that need to reconcile a
multi-node architect spec against this 3-slot limit, RET-C2-619's source
proposal (`EngTemplate_RET-C2-619.md` §4, §10-3) already scopes the domain
logic as **3 real nodes**, with `MainNode` running 4 sequential internal
passes (A–D) inside a single `execute()` call — "MainNode has 4 internal
passes but remains a single node — no multi-node routing complexity" (source
proposal §10-3). No step-helper-class layer or `GraphNode`/inner-subgraph
composition is needed; the 4 passes are implemented as plain functions in
`src/services/` called sequentially from `MainNode.execute()`.

```
AgentBaseGraph (src/graph/graph.py):
  InitializeNode      [framework default]
  PreProcessNode      [VERIFIED_EXTERNAL — real FunctionNode]
    - S-1 schema validation (claim_lines fields, numeric amounts, ISO date)
    - Claim line type normalization (canonical set)
    - Statutory deadline computation + urgency flag
  MainNode            [VERIFIED_EXTERNAL — real FunctionNode]
    Pass A — agreement_term_extract_service  (LLM)  — semantic clause matching
    Pass B — accrual_validate_service        (deterministic) — variance + decision
    Pass C — timeline_check_service          (deterministic) — 下請法 Art.4 check
    Pass D — dispute_brief_service           (LLM)  — per-line rationale
  PostProcessNode     [VERIFIED_EXTERNAL — real FunctionNode]
    - S-2 output sanitization (strip internal margin/back-margin data)
    - Markdown report rendering + line_decisions[] JSON assembly
    - S-4 audit log (vendor_id hash, period, line count, decision counts)
  FinalizeNode        [framework default]
```

### Node Configuration

| Node | Responsibility | Input State | Output State | Inherits/Overrides |
|------|---------------|-------------|--------------|-------------------|
| initialize | schema_version, session_id, trust_level | — | — | `InitializeNode` (default) |
| pre_process | S-1 schema validation; claim line normalization; statutory deadline computation; urgency flag | `user_input` (JSON payload as string) | `normalized_claim`, `payment_deadline`, `urgency_flag`, `vendor_id`, `agreement_summary` | `FunctionNode` |
| main | Pass A agreement term extraction (LLM) + semantic claim-to-clause mapping; Pass B deterministic accrual validation; Pass C 下請法 Art.4 timeline check; Pass D LLM dispute brief generation | `normalized_claim`, `agreement_summary`, `payment_deadline` | `line_decisions`, `compliance_flags`, `term_extracts`, `variance_table` | `FunctionNode` |
| post_process | S-2 output sanitization; Markdown report rendering; `line_decisions` JSON assembly; S-4 audit log | `line_decisions`, `compliance_flags`, `variance_table`, `vendor_id` | `result`, `formatted_output` | `FunctionNode` |
| finalize | response_metadata, total_time_ms | — | — | `FinalizeNode` (default) |

### Data Flow

```
START
  → InitializeNode
  → PreProcessNode (VERIFIED_EXTERNAL, real S-1/S-2 gate)
       S-1 schema validation: claim_lines fields present, amounts numeric
         non-negative, claim_receipt_date parseable ISO date,
         agreement_summary non-empty and under token cap (8k tokens)
       Normalize claim line types -> canonical set (volume_rebate /
         coop_contribution / listing_fee / logistics_contribution / other)
       Compute payment_deadline = claim_receipt_date + payment_due_days
       Flag urgency if payment_deadline < today + 14 days
  → MainNode (VERIFIED_EXTERNAL)
       Pass A: LLM extracts per-type formula/threshold/period/cap/basis from
         agreement_summary; semantic-matches each claim line to its clause;
         each extracted parameter carries extraction_confidence
         (high/medium/low)
       Pass B: deterministic — apply extracted formula to actual_performance;
         compute expected_amount; variance = claimed_amount - expected_amount;
         classify: |variance| <= tolerance -> Approve; variance > tolerance
         -> Dispute; clause not found OR extraction_confidence=low ->
         Needs-Info
       Pass C: deterministic — payment_deadline <= claim_receipt_date + 60
         days (下請法 Art.4 statutory max); flag violating lines; generate
         compliance_flags[] with statutory citation, informational=true
       Pass D: LLM drafts 2-3 sentence rationale for each Dispute/Needs-Info
         line, citing variance amount + agreement clause; recommended next
         action per line
  → PostProcessNode (VERIFIED_EXTERNAL, real S-3 gate)
       S-2/S-3: strip internal cost/margin data inferred from
         agreement_summary; redact internal buyer strategy notes
       Render Markdown reconciliation report (header, variance table,
         compliance flags, dispute briefs, summary, next actions)
       Assemble line_decisions[] JSON
       S-4 audit log: vendor_id HASH (not raw), claim period, line count,
         decision counts, timestamp, invocation_id
       → result (JSON-str), formatted_output (str)
  → FinalizeNode
END
```

> **Scope boundary** (source proposal §4): multi-vendor batch aggregation,
> direct ERP/AP system write-back, historical trend analysis, PDF OCR
> (text-layer or pre-extracted JSON required), and contract lifecycle
> management are explicitly out of scope. Each invocation processes a single
> vendor's claim batch for one period, statelessly across calls.

> **Advisory-only guarantee** (source proposal §11 Risk #3): `compliance_flags`
> and the report's 下請法 section are informational only —
> `{"informational": true}` on every compliance flag. The report header and
> `docs/07_operation_guide.md` must carry the legal disclaimer text from
> source proposal §12 dependency #5. Final statutory compliance determination
> remains with the buyer/AP team and legal counsel; this agent never issues a
> binding ruling.

## State Definition

File: `src/schemas/state.py` — extends `AgentState` (flat TypedDict, ADR-005).

| Field | Type | Producer (step) | Consumer | ADR-005 note |
|---|---|---|---|---|
| `vendor_id` | `Optional[str]` | PreProcessNode | PostProcessNode (audit hash) | business entity identifier, not personal data |
| `agreement_summary` | `Optional[str]` | PreProcessNode (passthrough, capped) | MainNode Pass A | free-text; token-capped at 8k in PreProcessNode |
| `normalized_claim` | `Optional[str]` | PreProcessNode | MainNode Pass A/B | **JSON-str** — list of `{line_id, type (canonical), claimed_amount, period, basis}` |
| `actual_performance` | `Optional[str]` | PreProcessNode (passthrough) | MainNode Pass B | **JSON-str** — `{net_sales, sell_out_units, ...}` |
| `claim_receipt_date` | `Optional[str]` | PreProcessNode (passthrough) | MainNode Pass C | ISO date string — caller-provided; needed alongside `payment_deadline` for the 60-day statutory check |
| `payment_deadline` | `Optional[str]` | PreProcessNode | MainNode Pass C, PostProcessNode | ISO date string — `claim_receipt_date + payment_due_days` |
| `urgency_flag` | `Optional[bool]` | PreProcessNode | PostProcessNode (report header) | true when `payment_deadline < today + 14 days` |
| `term_extracts` | `Optional[str]` | MainNode Pass A | MainNode Pass B (same node, same execute — intermediate, not required to leave the node, but stored for traceability) | **JSON-str** — per-type `{formula, threshold, period, cap, basis, extraction_confidence}` |
| `variance_table` | `Optional[str]` | MainNode Pass B | PostProcessNode | **JSON-str** — list of `{line_id, type, claimed_amount, expected_amount, variance}` |
| `line_decisions` | `Optional[str]` | MainNode Pass B (decision) + Pass D (rationale merged in) | PostProcessNode output | **JSON-str** — list of `{line_id, decision, variance_amount, rationale, recommended_action}` |
| `compliance_flags` | `Optional[str]` | MainNode Pass C | PostProcessNode output | **JSON-str** — list of `{type: "下請法Article4", detail, informational: true}` |
| `result` | `Optional[str]` | PostProcessNode | FinalizeNode / caller | **JSON-str** — full structured response (`line_decisions`, `compliance_flags`, `summary`, `audit_ref`) |
| `formatted_output` | `Optional[str]` | PostProcessNode | caller | Markdown reconciliation report |

> **State Constraints (mandatory):**
> - Flat TypedDict only — no Pydantic, dataclass, or arbitrary objects (msgpack incompatible)
> - No credentials/JWT/API keys in state (checkpoint DB leakage risk)
> - `InvocationContext` accessed via `InvocationContext.from_state(state)` inside
>   `execute()` only — never stored in state, never constructed directly in a node
> - Dict/list fields (`normalized_claim`, `actual_performance`, `term_extracts`,
>   `variance_table`, `line_decisions`, `compliance_flags`): `Optional[str]` +
>   `json.dumps` (producer) / `json.loads` (consumer) [ADR-005]
> - `vendor_id` is a business entity identifier (not APPI personal data per
>   source proposal §10-5); still hashed (not stored raw) in the audit log to
>   avoid exposing vendor business relationships in logs.
> - `agreement_summary` may contain confidential back-margin/pricing terms
>   (source proposal Risk #4) — never persisted beyond the invocation; audit
>   log records a hash of `agreement_summary`, never its content.

## Security Design

| Gate | Location | Level | Implementation |
|---|---|---|---|
| S-1 | PreProcessNode (real gate) | VERIFIED_EXTERNAL | Framework S-1 trust gate on `__call__()`; domain-level check inside `execute()`: `claim_lines` schema (required fields present), amount fields numeric/non-negative, `claim_receipt_date` parseable ISO date, `agreement_summary` non-empty and ≤ 8k-token cap, `claim_lines` count ≤ 30 (source proposal Risk #5) |
| S-2 | PreProcessNode | VERIFIED_EXTERNAL | `_extra_security_gate_input()` — no additional PII scan needed beyond the framework default (vendor financial data only, no APPI personal data per source proposal §10-5); does a raw-length sanity check on `user_input` before JSON parsing (sets `_raw_input_suspiciously_short` for `execute()` to see). The field-level `agreement_summary` length warning (≥ 200 chars, source proposal Risk #2) runs inside `execute()` after JSON parsing, since `agreement_summary` is not yet extractable at the hook stage |
| S-3 | PostProcessNode (real gate) | VERIFIED_EXTERNAL | `_extra_security_gate_output()` — pattern-matches the rendered report and `line_decisions` for common back-margin/internal-pricing indicators (margin%, 原価, 仕切率) inferred from `agreement_summary`; redacts before output (source proposal Risk #4) |
| S-4 | All domain nodes | — | `emit_trace_event()` in every `execute()`: `input_validated`/`deadline_computed` (PreProcessNode), `terms_extracted`/`accrual_validated`/`timeline_checked`/`dispute_brief_generated` (MainNode), `report_assembled` (PostProcessNode) — payload includes `vendor_id` hash, claim period, decision counts; never raw `agreement_summary` content |

> **S-2/S-3 hook rule (ADR-017):** All three real slot nodes are `FunctionNode`
> subclasses. Framework `@final` gates run automatically. Extend via
> `_extra_security_gate_input()` / `_extra_security_gate_output()` only.
> **MUST NOT override `_security_gate_input()` or `_security_gate_output()`
> directly** — raises `TypeError` at class definition.

> **S-4 emit rule:** Do NOT emit `node_start` / `node_complete` / `node_error`
> — `BaseNode.__call__()` emits these automatically. Custom events only.

### Risk mitigations — design decisions (source proposal §11, Risks #1–#5)

1. **Risk #1 (High) — LLM misextracts agreement formula parameters.** Pass A
   prompt requires structured JSON output including a per-parameter
   `extraction_confidence` field (high/medium/low) — explicit
   confidence-self-assessment instruction in the prompt (prompt-engineering
   pattern, not a model feature). Pass B applies a strict schema gate
   (`accrual_compliance_service._terms_are_trustworthy()`) before any
   parameter set is used: `extraction_confidence` must be exactly `"high"`
   (`"medium"` and `"low"` both route to **Needs-Info** — a merely-plausible
   extraction is not sufficient for an Approve/Dispute decision that carries
   financial and legal weight), `basis_field` must be one of the allowlisted
   `actual_performance` keys (`net_sales`, `sell_out_units`), and
   `rate`/`threshold`/`cap` must all be non-negative numeric values. Any
   extraction failing this gate — malformed, incomplete, non-"high"
   confidence, or an unrecognized `basis_field` — always resolves to
   **Needs-Info**, never Dispute or a silently-defaulted Approve. Accrual
   math itself (Pass B) is pure deterministic arithmetic on validated,
   LLM-extracted parameters — the math is never LLM-generated, keeping the
   authoritative decision path hallucination-free.
2. **Risk #2 (Medium) — incomplete/non-standard agreement_summary.** PreProcessNode
   emits a warning (not a hard block) when `agreement_summary` length is
   suspiciously short relative to `claim_lines` count (< 200 chars). Any
   claim line whose clause cannot be extracted always resolves to
   **Needs-Info** — never a silent failure.
3. **Risk #3 (Medium) — 下請法 flags read as authoritative legal determination.**
   Every `compliance_flags[]` entry carries `informational: true`. Report
   header includes the fixed disclaimer text (source proposal §12
   dependency #5, JP + EN); `docs/07_operation_guide.md` documents the
   flag -> buyer confirms with legal/AP manager -> AP entry workflow.
4. **Risk #4 (Medium) — agreement_summary contains confidential back-margin
   data.** S-3 `_extra_security_gate_output()` pattern-matches common
   back-margin indicators (margin%, 原価, 仕切率, internal code patterns) in
   the rendered report and dispute rationale before output. Audit log stores
   only an `agreement_summary` hash, never content.
5. **Risk #5 (Low) — claim/agreement size exceeds context window.**
   PreProcessNode enforces `claim_lines` count ≤ 30 (configurable) and
   `agreement_summary` ≤ 8k tokens; oversized input returns
   `AgentStatus.ERROR` with guidance to split into batches (documented in
   `docs/07_operation_guide.md`).

## Framework Utilization

### Shared Components Used
- [x] InvocationContext (correlation_id, session_id, trust level) — via `InvocationContext.from_state(state)` inside `execute()`; no secrets required by this agent's domain logic (LLM client is injected via `self.config["llm"]` at graph construction, not fetched per-node)
- [x] ConnectionPolicy (retry/timeout strategy) — for the 2 LLM calls (Pass A, Pass D) in MainNode
- [x] SecurityViolationError — raised by framework S-1 trust gate on insufficient `caller_trust_level`
- [x] S-2: `_extra_security_gate_input()` — `agreement_summary` length warning in PreProcessNode
- [x] S-3: `_extra_security_gate_output()` — back-margin pattern redaction in PostProcessNode
- [x] S-4: `emit_trace_event()` — at least one domain-specific event in each `execute()`

> **S-2/S-3 gate behaviour by node type (ADR-017):**
> - `FunctionNode` subclass → framework `@final` gate always runs automatically;
>   extend via `_extra_security_gate_input()` / `_extra_security_gate_output()` only
> - `GraphNode` / `RemoteAgentNode` → deliberate no-op (upstream or remote node's gate already applied)
> - Custom `BaseNode` subclass → must implement `_security_gate_input()` and
>   `_security_gate_output()` directly (`@abstractmethod` — omission raises `TypeError` at instantiation)

### Composition Pattern

- **Pattern**: Standalone (no GraphNode/RemoteAgentNode) — 3 real `FunctionNode`s
  only; MainNode's 4 passes are plain Python/LLM calls inside one `execute()`,
  not separate nodes
- **L1 Base**: `AgentBaseGraph`
- **Error propagation strategy**: propagate — node failures surface to the
  framework backbone; a claim line that cannot be resolved never raises, it
  resolves to `Needs-Info` (source proposal §10-1, §11 Risk #1/#2)

## Import Isolation Confirmation

- [x] Template does NOT import `agenticstar-platform` SDK (Level 0)
- [x] Import targets: `framework/` and `shared/` only
- [x] No `agents/base/` imports (L1 direct inheritance — no L2)

## Class Name Consistency

| Artifact | Value |
|---|---|
| `src/graph/graph.py` | `class RetailVendorRebateTradePromoReconciliationAgent(AgentBaseGraph)` |
| `config/agent.yaml` | `class: "RetailVendorRebateTradePromoReconciliationAgent"` |
| `src/api/server.py` | `from src.graph.graph import RetailVendorRebateTradePromoReconciliationAgent` |

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|---|---|---|---|---|
| L1 base type | AgentBaseGraph | AutonomousBaseGraph | AgentBaseGraph | Cat 2 fixed pipeline, single pass, no autonomous loop (source proposal §10-1) |
| 4-pass realization | 4 separate LangGraph nodes | 4 sequential passes inside one MainNode.execute() | Sequential passes inside MainNode | Source proposal §10-3 explicitly scopes this as "no multi-node routing complexity"; a 4th/5th slot does not exist on `AgentBaseGraph` and is not needed here since the passes have no independent routing/retry requirements |
| Composition pattern | Standalone (flat backbone) | GraphNode + inner BaseGraph | Standalone | Pipeline is linear with no branching; nested graph adds complexity without benefit |
| Accrual math authority | LLM computes expected_amount | Deterministic Python arithmetic on LLM-extracted formula params | Deterministic arithmetic | Source proposal §7/§11 Risk #1 — math must be authoritative and hallucination-free; LLM scope limited to semantic matching + prose |
| Low-confidence extraction handling | Classify as Dispute | Classify as Needs-Info | Needs-Info | A wrongly-classified Dispute has AP/vendor-relationship consequences; Needs-Info always routes to human review instead |
| 下請法 compliance flag semantics | Authoritative ruling | Informational flag + legal disclaimer | Informational flag | Source proposal §11 Risk #3 — statutory determination remains with buyer/legal; agent output must never be read as a binding ruling |
| Claim/agreement size limits | Unbounded | `claim_lines` ≤ 30, `agreement_summary` ≤ 8k tokens | Bounded, configurable | Source proposal §11 Risk #5 — protects against context-window overflow; batching guidance documented for callers |
