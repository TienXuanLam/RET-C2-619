# Test Specification

## Test Strategy
- Coverage target: 100% of domain branches in `src/services/` and `src/nodes/`
- Test types: Unit (per service module + per node) / Proof-of-Boundary (framework contract + accrual/compliance guarantees)

## Framework Compliance Tests (Mandatory)

| TC-ID | Test | Expected Result |
|-------|------|----------------|
| TC-01 | State contract: flat TypedDict, no Pydantic/dataclass | `State` fields are `Optional[str]`/`Optional[bool]` primitives only |
| TC-02 | `required_trust_level` enforced on all 3 real nodes | Declaration: `PreProcessNode`, `MainNode`, `PostProcessNode` all declare `TrustLevel.VERIFIED_EXTERNAL`. Enforcement: each node's `test_trust_gate_blocks_anonymous` calls the real `__call__()` gate entry point (not `execute()`) with `caller_trust_level=ANONYMOUS` and asserts `status=error`; `test_trust_gate_allows_verified_external` asserts the matching-trust case still succeeds |
| TC-03 | S-1 domain schema validation (PreProcessNode) | Invalid `claim_lines` (missing `line_id`, negative `claimed_amount`, unparseable `claim_receipt_date`, oversized batch) → `status=error` with a descriptive `error_log` entry, never a silent pass-through |
| TC-04 | S-2: `_extra_security_gate_input()` present (PreProcessNode) | Hook exists; does not raise; `FunctionNode.@final` gate is not overridden directly |
| TC-05 | S-3: `_extra_security_gate_output()` non-trivial (PostProcessNode) | Back-margin/internal-pricing redaction pattern executes on `formatted_output`; hook exists, `@final` gate not overridden directly |
| TC-06 | S-4: at least one domain `emit_trace_event()` per `execute()` | `PreProcessNode` emits `input_validated`; `MainNode` emits `terms_extracted`+`accrual_validated`+`timeline_checked`+`dispute_brief_generated`; `PostProcessNode` emits `report_assembled` |
| TC-07 | ⚠️ Accrual math authority and 下請法 timeline check — domain business logic | See "Accrual & Compliance Tests" below — these are the template's core correctness guarantee |

## Accrual & Compliance Tests (domain business logic — TC-07 detail)

| Case | Input | Expected Result |
|---|---|---|
| Approve — within tolerance | `claimed_amount` within ¥1,000 or 0.5% of formula-computed `expected_amount` | `decision="approve"`; fixed rationale, no LLM call |
| Dispute — over tolerance | `claimed_amount` exceeds `expected_amount` beyond tolerance | `decision="dispute"`; `variance` is the signed difference; Pass D drafts a rationale citing the variance |
| Needs-Info — clause not found | `term_extracts` has no entry for the claim line's type | `decision="needs_info"`; `expected_amount`/`variance` are `None`; rationale states manual review required |
| Needs-Info — extraction not fully trustworthy | `term_extracts` entry exists but `extraction_confidence` is not exactly `"high"` (`"medium"`, `"low"`, missing, or unrecognized), or `basis_field`/`rate`/`threshold`/`cap` are malformed/unallowlisted/non-numeric | `decision="needs_info"` — Pass B (`accrual_compliance_service._terms_are_trustworthy()`) must not treat anything short of a fully valid, high-confidence extraction as usable, even if a formula is present (source proposal §11 Risk #1) |
| 下請法 Art.4 — within statutory window | `payment_deadline <= claim_receipt_date + 60 days` | `compliance_flags=[]` |
| 下請法 Art.4 — statutory breach | `payment_deadline > claim_receipt_date + 60 days` | `compliance_flags` contains one entry, `type="下請法Article4"`, `informational=True` |
| Accrual math never LLM-generated | Any Approve/Dispute decision | `accrual_compliance_service.validate_accrual()` computes `expected_amount`/`variance` via pure arithmetic — no LLM call in this function, verified by not passing an `llm` argument to it |
| Claim line count exceeds cap | `claim_lines` count > 30 | `status=error`; guidance to split into batches in `error_log` |
| `payment_due_days` malformed | Non-integer, negative, or > 365 `payment_due_days` | `PreProcessNode` rejects with `status=error` and a descriptive `error_log` entry — never reaches `compute_deadline()`'s `int()` cast (previously an uncaught `ValueError` leaking a full stack trace into `error_log`) |
| Dispute brief factual grounding | Pass D LLM output does not cite the disputed line's ID and computed variance amount | Falls back to the deterministic rationale template — an ungrounded free-text brief is never sent to the vendor as-is |

## Proof-of-Boundary Tests (Mandatory)

| PB-ID | Boundary | Test | Expected Result |
|-------|----------|------|----------------|
| PB-01 | S-1 schema injection resistance | Claim payload with malformed `claimed_amount` (negative, non-numeric) or missing `line_id` attempting to bypass validation | `PreProcessNode` rejects with `status=error`; no line reaches MainNode |
| PB-02 | Accrual math is not LLM-influenced | `accrual_compliance_service.validate_accrual()` called directly with a `term_extracts` dict (no LLM object involved anywhere in the call chain) | Deterministic `expected_amount`/`variance`/`decision` — identical output on repeated calls with the same input |
| PB-03 | 下請法 flags are always informational | Full pipeline invocation producing a statutory-breach flag | Every entry in `compliance_flags` carries `informational=True`; report Markdown includes the JP+EN disclaimer text verbatim |
| PB-04 | Back-margin/internal-pricing redaction | `agreement_summary` containing a back-margin indicator (e.g. `margin: 12%`, `原価`) that could leak into a dispute rationale | Redacted (`[redacted — internal pricing data]`) in `line_decisions[].rationale` and the rendered `formatted_output` — verified independently at both PostProcessNode's inline sanitization and the `_extra_security_gate_output()` hook. `vendor_id` is never rendered in plaintext on any caller-facing surface — the Markdown report's `Vendor Ref` uses the same hashed value as the JSON response's `audit_ref`. **Known limitation** (tracked, not silently accepted): `sanitize_text()` is a fixed regex list and does not catch semantic paraphrases of the same back-margin fact — see `test_paraphrased_back_margin_disclosure_not_yet_caught`. |
| PB-05 (integration) | Full compiled-graph invocation | `tests/integration/test_graph.py` — valid claims via `agent.invoke()` end-to-end (report renders, no plaintext `vendor_id`, disclaimer present); malformed input (negative amount, non-numeric `payment_due_days`, oversized batch, anonymous caller) never reaches MainNode/PostProcessNode; a non-"high"-confidence LLM extraction resolves to Needs-Info end-to-end, not just at the `accrual_compliance_service` unit level | All pass; proves the node-level guarantees above actually hold through the real `__call__()`/`agent.invoke()` entry points, not just via `execute()` called in isolation |

## Test Execution Summary
- Execution date: local run, 2026-07-15 (see CI pipeline for the authoritative reviewed-SHA run)
- Total tests: 117 (115 unit/PB/integration + 2 PB-7 auto-skip)
- Pass: 115 / Fail: 0 / Skip: 2 (PB-7, non-HITL — `hitl.enabled` is absent/false in `config.yaml`)
- Coverage: not separately measured locally; the "100% of domain branches" target is enforced by CI's `run-tests` job, not re-attested by hand here
