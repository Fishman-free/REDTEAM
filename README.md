# REDTEAM payment-agent experiment

This repository is a safe, local synthetic experiment for testing whether participant messages can trick an agent that has authority to transfer experimental tokens. It includes a Python decision runtime, a SQLite reference ledger, and a local-only Ethereum/Hardhat layer wired together into one end-to-end chain: participant message -> versioned system prompt -> LLM backend (offline mock by default) -> strict PAY/NONE validation -> trusted policy -> **real on-chain ERC-20 transfer** -> independent evaluator -> evaluator-only reward settlement -> JSON evidence bundle. It is **not** a mainnet payment system or generic security-review marketplace.

## What is verified (honest status)

- **Python SQLite MVP: verified.** Deterministic vulnerable/hardened agents, idempotent HTTP flow, replay, labeled regression, independent post-execution violations.
- **Local EVM layer: verified.** `ExperimentalToken`, `PaymentAgent`, `RewardSettlement` compile and pass 13 Hardhat tests on the in-process chain.
- **End-to-end LLM-shaped -> on-chain demo: verified, offline.** `npm run demo:agent` executes real chain transactions driven by the Python runtime's decisions and emits a full evidence bundle (tx hash, block, event data, balances, violations, settlement hash). The decision brain uses the versioned prompt plus a **deterministic mock LLM** -- reproducible, no network.
- **LLM adapter: implemented and bounded, but advisory-by-default.** The OpenAI-compatible backend in `redteam/agent_runtime.py` requires an explicit `REDTEAM_LLM_ENABLED=1`; even then its output only enters the same validated pipeline and can never bypass mechanical policy. It has not been exercised against a live model in this repository's tests.
- **Not done / not claimed:** no model training, no mainnet or production deployment, no external RPC, no real wallets or funds, no general-purpose agent safety. GitHub Pages is wired via the `test` + `deploy` jobs in `.github/workflows/pages.yml`, but publishing requires the site to be enabled; if the run fails with "Get Pages site failed", a repository administrator must choose **Settings -> Pages -> Source: GitHub Actions** once.

## Run everything

```bash
pip install pytest            # once
npm install                   # once (Hardhat toolchain)

python -m pytest -q                        # Python suites (recommended entrypoint)
python -m unittest discover -s tests       # equivalent unittest entrypoint
npm test                                   # Hardhat contract + e2e tests
npm run demo:agent                         # offline end-to-end on-chain agent demo
```

`python -m pytest -q` is the authoritative Python entrypoint (both runners execute the same 19 tests). CI runs both, plus `npm test` and the demo.

## SQLite HTTP MVP (optional interactive mode)

```bash
python -m redteam.server --port 8765 --db ./redteam.sqlite3
```

Open `http://127.0.0.1:8765` (loopback only). Create vulnerable/hardened runs, submit participant text, inspect balances/evidence, and replay the exact transcript through both agents. `POST /api/regression` produces labeled attack/control metrics. A session token is generated at process start and required for API calls.

## Architecture and trust boundaries

- `redteam/agent_runtime.py`: **the single decision brain.** Loads `prompts/payment_agent_system_v1.txt` as the system message, keeps three inputs strictly separated (system prompt / trusted procurement-delivery-ledger state / untrusted participant message), accepts only the strict `PAY INV-123 TO account AMOUNT 40` or `NONE` contract from the model, applies mechanical boundary checks, and runs the vulnerable/hardened policy. A model can never execute code, call tools, fetch URLs, or talk past the boundary checks.
- `redteam/llm.py`: low-level OpenAI-compatible transport used by the legacy MVP path; network requires `REDTEAM_LLM_ENABLED=1`; failures degrade to abstain.
- `redteam/agents.py`: facade binding the runtime into the SQLite MVP; `TRUSTED_FEED` is host-owned fixture state.
- `redteam/core.py`: SQLite WAL ledger with boundary/balance checks, a 250-token cap, idempotency keys and persisted evidence.
- `redteam/policy.py`: independent post-execution evaluator for the MVP (bad recipient, duplicate, unverified delivery, over/underpayment). It never controls execution.
- `contracts/`: `PaymentAgent` enforces mechanical boundaries on-chain (allowlist, exact configured-invoice match, single-use op/invoice, total cap, events). `RewardSettlement` is evaluator-signer-only, one-shot, capped -- the agent cannot grant itself rewards.
- `scripts/agent-flow.js` + `scripts/agent-demo.js`: the on-chain orchestrator and demo. The Python runtime is invoked as a subprocess with the LLM env vars force-cleared, so the demo is hermetically offline. `test/agent-e2e.test.js` drives the identical code path.

Vulnerable mode deliberately treats the participant's instruction as authority so a red-team run can observe a genuine mis-payment; hardened mode pays only against trusted delivery, exact recipient/amount and fresh ledger state.

## Versioned prompt and LLM opt-in

`prompts/payment_agent_system_v1.txt` is the single source of truth for the system message (prompt version `payment-agent-system-v1`); the runtime reads it by module-relative path and every evidence bundle records `prompt_version`. The mock backend keeps the demo deterministic and offline. To point the same pipeline at a real OpenAI-compatible endpoint, set `REDTEAM_LLM_ENABLED=1` plus `REDTEAM_LLM_BASE_URL`, `REDTEAM_LLM_API_KEY`, `REDTEAM_LLM_MODEL` in the environment -- never in source files or committed config. Even enabled, the model only proposes; code validates.

## Evidence

Each demo run records: `run_id`, `prompt_version`, mode, participant message, raw model output, parsed proposal, trusted policy snapshot, transaction hash, block number, `Payment` event payload, token balances, violations, `RewardSettlement` transaction, and the final classification. Evidence is honest data, not tamper-proof storage.

## Acceptance criteria

- `python -m pytest -q` passes (19 tests); `npm test` passes (13 tests).
- `npm run demo:agent` runs fully offline and prints a JSON bundle where the vulnerable run has a real tx hash, block number, `Payment` event, `bad_recipient` + `unverified_delivery` violations, participant balance increase, and a reward settlement hash; the hardened run records no payment for the same message.
- No production funds, external RPC, network calls, real wallets, or public bind.

## Honest limitations

The tokens are synthetic local-chain ERC-20 test assets; nothing is money. This is not a sandbox against a malicious local OS user: source files, fixtures and the local chain are developer-controlled. The evaluator's ground truth is a fixture, not unbiased adjudication. The deterministic mock LLM is a stand-in; results do not certify behavior of any real model, and prompt text is semantic guidance, never a security boundary. No mainnet deployment, remote append-only signing or production payment integration is claimed or implemented.

## Project site

The Chinese introduction lives at `docs/index.html` and is published by the `deploy` job of `.github/workflows/pages.yml` after the test job passes. GitHub Pages may need a one-time enablement by a repository administrator (Settings -> Pages -> Source: GitHub Actions); until then the deploy job legitimately fails and the public URL returns 404.
