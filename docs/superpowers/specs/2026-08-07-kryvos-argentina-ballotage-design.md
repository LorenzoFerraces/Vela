# Kryvos + Argentina Ballotage — Design Spec

**Date:** 2026-08-07  
**Status:** Approved (conversation review)  
**Course:** ECI 2026 — SNARKs Final Project  
**Paper:** #11 — Kryvos (Huber et al., ACM CCS 2022)  
**Team:** Solo  

## Problem

Argentina’s presidential elections use a **primera vuelta** with ballotage (Art. 96). The public must learn whether a formula was elected outright or which two formulas proceed to segunda vuelta — but publishing the **full per-formula tally** is unnecessary and causes privacy and political downsides (weak mandates, embarrassed losers, gerrymandering) that Kryvos explicitly addresses.

Kryvos provides **publicly tally-hiding verifiable e-voting**: talliers learn the aggregated tally; the public verifies a SNARK and sees only the election result — not all vote counts.

## Solution

Implement a **minimal Kryvos slice** for single-choice plurality voting, then extend the tally result function `fres` with **Argentina’s first-round rules**:

1. **Elected in primera vuelta** if:
   - strictly **> 45%** of valid votes, **or**
   - **≥ 40%** and a lead of **> 10 percentage points** over second place.
2. **Otherwise (ballotage):** publish the **two formulas with the most votes** as the runoff pairing (identities only, not counts).

Baseline comparison: paper’s **Most Votes** tally SNARK on the same ballot circuit.

## Architecture

```
Voter                Mock Bulletin Board              Public verifier
  |                          |                              |
  |-- ballot + ballot ZK --->|                              |
  |                          |-- aggregate commitments ---->|
  |                          |                              |
Tallier                      |                              |
  |-- tally + tally ZK ----->|                              |
  |   (public res only)      |<----- verify SNARKs ---------|
```

### Components

| Component | Responsibility |
|-----------|----------------|
| `circuits/ballot_single_vote.circom` | Prove vote is one-hot, sum = 1 |
| `circuits/tally_most_votes.circom` | Baseline: winner = argmax(tally) |
| `circuits/tally_argentina_ballotage.circom` | Extension: Argentina rules + runoff pair |
| `circuits/lib/` | Shared gadgets: argmax, second_argmax, comparisons |
| `scripts/setup.mjs` | Trusted setup (POT + zkey) per circuit |
| `scripts/prove_ballot.mjs` | Generate ballot witness + proof |
| `scripts/prove_tally.mjs` | Generate tally witness + proof (parameterized by circuit) |
| `scripts/verify.mjs` | Verify proof against public signals |
| `scripts/benchmark.mjs` | Measure prove/verify time, proof size |
| `test/` | Completeness + soundness (Node + snarkjs) |
| `.github/workflows/ci.yml` | Run tests on push |
| `README.md` | Course report (≤1500 words, rubric sections 1–6) |

### Simplifications (in scope)

- **Mock bulletin board:** JSON files (`data/ballots.json`, `data/election.json`) — no network, no encryption, no threshold talliers.
- **Commitments:** For the course slice, the tally vector is the SNARK witness; public signals include the claimed result. Pedersen vector commitments can be added as a stretch goal; the **result-function extension** is the graded novelty.
- **Candidate count:** `n_choices` ∈ {5, 10, 15} — small enough for laptop proving.
- **Tie-breaking:** Deterministic — on equal vote counts, **lower index wins** rank order.

### Out of scope

- IRV, Condorcet, Borda, multi-vote
- Second-round (ballotage) election execution
- Distributed CRS ceremony, tallier MPC, ballot encryption
- Slot-size tradeoff study (deferred; can add if time permits)
- Production deployment

## Result function (`fres_argentina`)

**Private witness:** tally vector `T[0..n-1]`, each entry a non-negative integer.

**Public outputs:**

| Signal | Meaning when `elected_first_round = 1` | Meaning when `elected_first_round = 0` |
|--------|----------------------------------------|----------------------------------------|
| `elected_first_round` | `1` | `0` |
| `winner` | index of elected formula | `0` (sentinel) |
| `runoff_a` | `0` (sentinel) | index of most votes |
| `runoff_b` | `0` (sentinel) | index of second-most votes |

**Logic (integer arithmetic, no floats):**

```
total       = sum(T)
first_idx   = argmax(T)           // tie: lowest index
second_idx  = argmax_second(T)    // tie: lowest index among non-first
t_first     = T[first_idx]
t_second    = T[second_idx]

cond_45     = t_first * 100 > 45 * total
cond_40_10  = (t_first * 100 >= 40 * total) AND ((t_first - t_second) * 100 > 10 * total)
elected     = cond_45 OR cond_40_10
```

## SNARK mapping (README rubric)

### 1. Application

- **Prover (voter):** ballot validity
- **Prover (tallier):** correct `fres` on aggregated tally
- **Verifier (public):** accepts proof, learns only `res` — not full `T`
- **Trust:** Groth16 trusted setup per circuit; talliers trusted to see `T` (publicly tally-hiding, not fully tally-hiding)

### 2. Proof system

- **SNARK:** Groth16 via **Circom 2 + snarkjs**
- **Properties:** trusted setup, ~constant proof size, fast verification
- **Framework choice:** Circom/snarkjs for solo reproducibility (paper uses libsnark C++)

### 3–4. Extension + feasibility

| Item | Status |
|------|--------|
| Most Votes baseline tally | Implemented |
| Argentina ballotage `fres` | Implemented |
| Pedersen commitments in-circuit | Feasible, out of scope |
| Full Kryvos protocol (encryption, talliers) | Feasible, out of scope |
| Transparent-setup SNARK swap | Open research |

### 5–6. Tests + performance

- **Completeness:** valid tally → proof verifies
- **Soundness:** wrong winner, wrong runoff pair, or flipped `elected` flag → reject
- **Benchmarks:** prove time, verify time, proof size, constraint count — Argentina vs Most Votes vs naive full-tally publish (no ZK)

## Repository

Deliverable is a **standalone public GitHub repo** (not the Vela monorepo). This spec and plan live in Vela `docs/superpowers/` as planning artifacts; implementation follows the plan in a new repo (suggested name: `kryvos-argentina-ballotage`).

## Success criteria

- [ ] Form submitted (paper #11, solo, extension described)
- [ ] Ballot circuit: valid one-hot passes, invalid rejected
- [ ] Most Votes tally: baseline works
- [ ] Argentina tally: all rule cases in test table pass
- [ ] Soundness tests fail on tampered public signals
- [ ] Benchmark script produces reproducible numbers + hardware note
- [ ] README ≤1500 words, all 6 rubric sections
- [ ] CI green on completeness + soundness
