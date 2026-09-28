# RET-C2-619 — RetailVendorRebateTradePromoReconciliationAgent

> **Category**: Cat 2 (DocGenerationAgent — vendor rebate/trade-promo claim reconciliation)
> **Industry**: RET
> **Inherits**: AgentBaseGraph (Level 1 direct)
> **Status**: Draft

## Overview

`RetailVendorRebateTradePromoReconciliationAgent` (RET-C2-619) reconciles a
vendor's rebate/trade-promotion claim against the applicable agreement terms
and actual performance data. It is triggered when a retail category buyer or
accounts-payable team uploads a claim batch (structured JSON or PDF-extracted
data) together with a free-text agreement summary and actual performance
figures. The agent normalizes the claim, uses LLM-assisted semantic matching
to map each claim line to its agreement clause, runs deterministic accrual
formula validation against agreed terms, and executes a 下請法 (Subcontract
Act) Article 4 statutory timeline check (60-day payment window) to flag
compliance risk. It produces a structured Markdown reconciliation report with
per-line Approve/Dispute/Needs-Info decisions, dispute rationale, and 下請法
compliance flags. It exists because Japan retail category buyers currently
spend 3–8 hours per vendor per quarter on manual rebate reconciliation,
facing both accrual math errors and 下請法 enforcement exposure from missed
or late dispute notices — no existing template in the catalog combines
agreement-term extraction, deterministic accrual validation, and Japan
statutory payment-timeline compliance in one reconciliation step.

## Why This Template Exists

This template is **one production unit of the Agent 1000 line** — not a standalone
deliverable. The project goal is to make us *capable of producing* 1,000+ templates
per FY26 September capacity. That capability is what unlocks AGENTIC STAR as the
global de facto platform for enterprise agent development.

Of every design decision in this template, ask:

> "Does this make the next template faster, or only this one better?"

If your answer is the latter, reconsider — generalize at Level 2, or refactor the
pattern. A template that is technically beautiful but cannot be replicated quickly
across industries fails the mission. See the project charter for the three-layer
vision and full purpose context.

## Requirements

- Python 3.11+
- Optional: an `ANTHROPIC_API_KEY` secret to enable LLM-assisted agreement-term
  extraction and dispute-brief drafting

### Behaviour without the platform

Without `ANTHROPIC_API_KEY` configured, the standalone server still boots and
every invocation reaches `status=success` — Pass A/D degrade to a fully
deterministic fallback (unmatched claim types resolve to Needs-Info; dispute
briefs use a fixed rationale template citing the computed variance). The
deterministic accrual math (Pass B) and statutory timeline check (Pass C) are
authoritative and never depend on the LLM.

## Quick Start

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,anthropic]"
python -m pytest tests/ -v
```

## Project Structure

```
config/
  agent.yaml          # AgentRegistry manifest
  config.yaml         # runtime parameters
deploy/
  invoke_payload.json # sample /invoke payload
  local-stg.yml       # local STG-equivalent deploy config
src/
  api/server.py       # standalone HTTP entry point
  graph/graph.py       # AgentBaseGraph wiring
  nodes/               # pre_process / main / post_process
  schemas/state.py     # flat TypedDict state
  services/            # pure domain logic (normalization, extraction, accrual math, rendering)
tests/
  unit/                # per-node/per-service unit tests
  integration/          # full-pipeline tests
  proof_of_boundary/   # framework-contract boundary tests
docs/
  02_design.md         # design specification
  03_test_spec.md      # test specification
cli.py                 # Marketplace Pod entrypoint
```

## Customising

- `config/config.yaml`: `max_retry`, `memory_enabled`, `timeout_s`.
- `config/agent.yaml`'s `requires.secrets`/`requires.extras`: adjust if the
  LLM provider changes.

## License

MIT — see [LICENSE](LICENSE).

## Status of this repository

This is a template under active development within the Agent 1000 line. It is
provided as-is, with no warranty, and may change without notice.
