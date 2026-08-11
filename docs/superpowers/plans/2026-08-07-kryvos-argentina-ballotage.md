# Kryvos Argentina Ballotage — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone Groth16 (Circom/snarkjs) demo of Kryvos-style publicly tally-hiding e-voting with an Argentina primera vuelta result function and ballotage pairing.

**Architecture:** Three Circom circuits (ballot, baseline tally, extension tally) plus Node scripts for setup/prove/verify/benchmark. Mock JSON bulletin board. Vitest for completeness/soundness. GitHub Actions CI.

**Tech Stack:** Circom 2.1.9, snarkjs 0.7.5, Node 20, Vitest 3.2.4

**Design spec:** `docs/superpowers/specs/2026-08-07-kryvos-argentina-ballotage-design.md`

## Global Constraints

- Standalone repo (suggested: `kryvos-argentina-ballotage`), public on GitHub for course submission
- `n_choices` compile-time constant: start with `5`, parameterize later via `circom -l` / separate builds for 10 and 15
- Integer-only arithmetic in circuits (no floating point)
- Tie-breaking: **lower index wins** when vote counts are equal
- README final report ≤ 1500 words, sections 1–6 per course rubric
- Academic integrity: attribute Kryvos paper and any copied Circom patterns
- Do not commit `node_modules/`, `build/`, `*.zkey`, or `pot*_final.ptau` (add to `.gitignore`; document download/generation in README)

---

## File map

```
kryvos-argentina-ballotage/
├── .github/workflows/ci.yml
├── .gitignore
├── README.md
├── package.json
├── circuits/
│   ├── ballot_single_vote.circom
│   ├── tally_most_votes.circom
│   ├── tally_argentina_ballotage.circom
│   └── lib/
│       ├── comparators.circom
│       └── argmax.circom
├── scripts/
│   ├── setup.mjs
│   ├── prove_ballot.mjs
│   ├── prove_tally.mjs
│   ├── verify.mjs
│   └── benchmark.mjs
├── test/
│   ├── ballot.test.mjs
│   ├── tally_most_votes.test.mjs
│   ├── tally_argentina.test.mjs
│   └── helpers.mjs
└── data/
    └── fixtures/
        ├── elected_45.json
        ├── elected_40_10.json
        └── ballotage.json
```

---

### Task 1: Repository scaffold

**Files:**
- Create: `package.json`, `.gitignore`, `README.md` (skeleton), `test/helpers.mjs`

**Interfaces:**
- Produces: npm scripts `test`, `setup`, `benchmark`
- Produces: `runGroth16(circuitName, witness)` helper used by all tests

- [ ] **Step 1: Create repo and `package.json`**

```bash
mkdir kryvos-argentina-ballotage && cd kryvos-argentina-ballotage
git init
```

```json
{
  "name": "kryvos-argentina-ballotage",
  "version": "0.1.0",
  "private": false,
  "type": "module",
  "scripts": {
    "compile": "node scripts/compile.mjs",
    "setup": "node scripts/setup.mjs",
    "test": "vitest run",
    "benchmark": "node scripts/benchmark.mjs"
  },
  "devDependencies": {
    "circomlib": "2.0.5",
    "circomlibjs": "0.1.7",
    "snarkjs": "0.7.5",
    "vitest": "3.2.4"
  }
}
```

Install circom compiler separately (system dep): https://docs.circom.io/getting-started/installation/

- [ ] **Step 2: Create `.gitignore`**

```
node_modules/
build/
*.ptau
*.zkey
*.wtns
.DS_Store
```

- [ ] **Step 3: Create `test/helpers.mjs`**

```javascript
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { execSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import * as snarkjs from "snarkjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
export const ROOT = path.join(__dirname, "..");
export const BUILD = path.join(ROOT, "build");

export function compileCircuit(circuitPath, name) {
  mkdirSync(BUILD, { recursive: true });
  const outDir = path.join(BUILD, name);
  mkdirSync(outDir, { recursive: true });
  execSync(
    `circom ${circuitPath} --r1cs --wasm --sym -o ${outDir} -l ${path.join(ROOT, "node_modules")}`,
    { stdio: "inherit", cwd: ROOT },
  );
  return outDir;
}

export async function groth16FullProve(circuitName, witness) {
  const dir = path.join(BUILD, circuitName);
  const wasm = path.join(dir, `${circuitName}.wasm`);
  const zkey = path.join(dir, `${circuitName}_final.zkey`);
  const wtns = path.join(dir, "witness.wtns");
  const { wtns: wtnsPath } = await snarkjs.wtns.calculate(
    witness,
    wasm,
    wtns,
  );
  return snarkjs.groth16.prove(zkey, wtnsPath);
}

export async function groth16Verify(circuitName, publicSignals, proof) {
  const vkeyPath = path.join(BUILD, circuitName, `${circuitName}_vkey.json`);
  const vkey = JSON.parse(readFileSync(vkeyPath, "utf8"));
  return snarkjs.groth16.verify(vkey, publicSignals, proof);
}

export function writeWitnessJson(circuitName, witness) {
  const p = path.join(BUILD, circuitName, "input.json");
  writeFileSync(p, JSON.stringify(witness, null, 2));
  return p;
}
```

- [ ] **Step 4: Create `scripts/compile.mjs`** (lists all circuits; used by setup/test)

```javascript
import path from "node:path";
import { fileURLToPath } from "node:url";
import { compileCircuit, ROOT } from "../test/helpers.mjs";

const circuits = [
  "ballot_single_vote",
  "tally_most_votes",
  "tally_argentina_ballotage",
];

for (const name of circuits) {
  compileCircuit(path.join(ROOT, "circuits", `${name}.circom`), name);
}
```

- [ ] **Step 5: Commit**

```bash
git add package.json .gitignore test/helpers.mjs scripts/compile.mjs README.md
git commit -m "chore: scaffold kryvos-argentina-ballotage repo"
```

---

### Task 2: Shared Circom gadgets (argmax, comparators)

**Files:**
- Create: `circuits/lib/comparators.circom`, `circuits/lib/argmax.circom`

**Interfaces:**
- Produces: `template GreaterThan(n)` → `out` is 1 iff `in[0] > in[1]` for n-bit values
- Produces: `template ArgMax(n)` → `indexOut`, `valueOut` for array length `n`
- Produces: `template ArgMaxSecond(n)` → second-highest index/value (distinct from first; tie → lower index for first, next for second)

- [ ] **Step 1: `circuits/lib/comparators.circom`**

```circom
pragma circom 2.1.9;

include "circomlib/comparators.circom";

// Returns 1 iff a > b, else 0. Bit width n.
template GreaterThan(n) {
    signal input a;
    signal input b;
    signal output out;
    component gt = GreaterThanEq(n);
    gt.in[0] <== a;
    gt.in[1] <== b + 1;
    out <== gt.out;
}
```

- [ ] **Step 2: `circuits/lib/argmax.circom`**

```circom
pragma circom 2.1.9;

include "comparators.circom";

// Argmax over values[0..n-1]. Tie: lowest index wins.
template ArgMax(n) {
    signal input values[n];
    signal output indexOut;
    signal output valueOut;

    signal index[n];
    signal value[n];

    index[0] <== 0;
    value[0] <== values[0];

    for (var i = 1; i < n; i++) {
        component gt = GreaterThan(32);
        gt.a <== values[i];
        gt.b <== value[i-1];
        // if values[i] > value[i-1], take i; else keep previous
        index[i] <== gt.out * i + (1 - gt.out) * index[i-1];
        value[i] <== gt.out * values[i] + (1 - gt.out) * value[i-1];
    }

    indexOut <== index[n-1];
    valueOut <== value[n-1];
}

// Second-largest value/index. Assumes n >= 2.
template ArgMaxSecond(n) {
    signal input values[n];
    signal input firstIndex;
    signal output indexOut;
    signal output valueOut;

    signal masked[n];
    for (var i = 0; i < n; i++) {
        masked[i] <== (i == firstIndex) ? 0 : values[i];
    }

    component second = ArgMax(n);
    for (var j = 0; j < n; j++) {
        second.values[j] <== masked[j];
    }
    indexOut <== second.indexOut;
    valueOut <== second.valueOut;
}
```

- [ ] **Step 3: Compile-check gadgets via ballot stub**

Run: `npm run compile` after Task 3 — for now, commit gadgets alone.

```bash
git add circuits/lib/
git commit -m "feat: add argmax and comparator gadgets"
```

---

### Task 3: Ballot circuit (single-choice)

**Files:**
- Create: `circuits/ballot_single_vote.circom`
- Create: `test/ballot.test.mjs`

**Interfaces:**
- Private input: `vote[n]` (one-hot)
- Public output: none (or optional `voteHash` later)
- Constraints: each `vote[i] ∈ {0,1}`, `sum(vote) = 1`

- [ ] **Step 1: Write failing test `test/ballot.test.mjs`**

```javascript
import { describe, it, expect, beforeAll } from "vitest";
import path from "node:path";
import { ROOT, compileCircuit, groth16FullProve, groth16Verify, writeWitnessJson } from "./helpers.mjs";
import { execSync } from "node:child_process";
import * as snarkjs from "snarkjs";

const N = 5;
const CIRCUIT = "ballot_single_vote";

describe("ballot_single_vote", () => {
  beforeAll(() => {
    compileCircuit(path.join(ROOT, "circuits", `${CIRCUIT}.circom`), CIRCUIT);
    execSync(`node scripts/setup.mjs ${CIRCUIT}`, { stdio: "inherit", cwd: ROOT });
  });

  it("accepts a valid one-hot ballot", async () => {
    const vote = [0, 1, 0, 0, 0];
    writeWitnessJson(CIRCUIT, { vote });
    const { proof, publicSignals } = await groth16FullProve(CIRCUIT, { vote });
    const ok = await groth16Verify(CIRCUIT, publicSignals, proof);
    expect(ok).toBe(true);
  });

  it("rejects witness with two 1s (witness gen should fail)", () => {
    expect(() => writeWitnessJson(CIRCUIT, { vote: [1, 1, 0, 0, 0] })).not.toThrow();
    // Prover constraint unsatisfied — groth16FullProve throws or verify fails
  });
});
```

- [ ] **Step 2: Run test — expect FAIL (circuit missing)**

Run: `npm test -- test/ballot.test.mjs`  
Expected: compile or circuit not found error

- [ ] **Step 3: Implement `circuits/ballot_single_vote.circom`**

```circom
pragma circom 2.1.9;

include "circomlib/comparators.circom";

template BallotSingleVote(n) {
    signal input vote[n];

    signal sum;
    var acc = 0;
    for (var i = 0; i < n; i++) {
        component bin = IsZero();
        // vote[i] * (vote[i] - 1) === 0  => boolean
        signal tmp;
        tmp <== vote[i] * (vote[i] - 1);
        tmp === 0;
        acc += vote[i];
    }
    sum <== acc;
    sum === 1;
}

component main { public [] } = BallotSingleVote(5);
```

- [ ] **Step 4: Create `scripts/setup.mjs`** (powers of tau + zkey per circuit)

```javascript
import { execSync } from "node:child_process";
import { mkdirSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import * as snarkjs from "snarkjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const BUILD = path.join(ROOT, "build");
const PTAU = path.join(BUILD, "powersOfTau28_hez_final.ptau");

const circuitName = process.argv[2];
if (!circuitName) {
  console.error("Usage: node scripts/setup.mjs <circuitName>");
  process.exit(1);
}

mkdirSync(BUILD, { recursive: true });

if (!existsSync(PTAU)) {
  console.log("Download ptau (use snarkjs powersoftau prepare phase2 ... or curl from snarkjs repo)...");
  // Document: curl -L -o build/powersOfTau28_hez_final.ptau https://hermez.s3-eu-west-1.amazonaws.com/powersOfTau28_hez_final.ptau
}

const dir = path.join(BUILD, circuitName);
const r1cs = path.join(dir, `${circuitName}.r1cs`);
const zkey0 = path.join(dir, `${circuitName}_0000.zkey`);
const zkeyFinal = path.join(dir, `${circuitName}_final.zkey`);
const vkeyPath = path.join(dir, `${circuitName}_vkey.json`);

await snarkjs.zKey.newZKey(r1cs, PTAU, zkey0);
await snarkjs.zKey.exportVerificationKey(zkeyFinal, vkeyPath);
// Note: run contribute/beacon in README for production; local contrib OK for coursework
```

Adjust setup script for full zkey contribution flow per snarkjs docs.

- [ ] **Step 5: Run tests — valid ballot passes**

Run: `npm test -- test/ballot.test.mjs`  
Expected: PASS on valid one-hot

- [ ] **Step 6: Commit**

```bash
git add circuits/ballot_single_vote.circom test/ballot.test.mjs scripts/setup.mjs
git commit -m "feat: single-vote ballot circuit with tests"
```

---

### Task 4: Baseline tally — Most Votes

**Files:**
- Create: `circuits/tally_most_votes.circom`
- Create: `test/tally_most_votes.test.mjs`

**Interfaces:**
- Private input: `tally[n]`
- Public output: `winner` (field index)
- Proves `winner = argmax(tally)`

- [ ] **Step 1: Failing test**

```javascript
import { describe, it, expect, beforeAll } from "vitest";
import path from "node:path";
import { ROOT, compileCircuit, groth16FullProve, groth16Verify } from "./helpers.mjs";
import { execSync } from "node:child_process";

const CIRCUIT = "tally_most_votes";

describe("tally_most_votes", () => {
  beforeAll(() => {
    compileCircuit(path.join(ROOT, "circuits", `${CIRCUIT}.circom`), CIRCUIT);
    execSync(`node scripts/setup.mjs ${CIRCUIT}`, { stdio: "inherit", cwd: ROOT });
  });

  it("proves winner for plurality", async () => {
    const tally = [120, 340, 90, 50, 200];
  const winner = 1; // index of 340
    const { proof, publicSignals } = await groth16FullProve(CIRCUIT, { tally });
    expect(publicSignals[0]).toBe(String(winner));
    expect(await groth16Verify(CIRCUIT, publicSignals, proof)).toBe(true);
  });
});
```

- [ ] **Step 2: Implement `circuits/tally_most_votes.circom`**

```circom
pragma circom 2.1.9;

include "lib/argmax.circom";

template TallyMostVotes(n) {
    signal input tally[n];
    signal output winner;

    component am = ArgMax(n);
    for (var i = 0; i < n; i++) {
        am.values[i] <== tally[i];
    }
    winner <== am.indexOut;
}

component main { public [winner] } = TallyMostVotes(5);
```

Fix `main` syntax: public signals declared correctly for circom 2 — use:

```circom
component main { public [winner] } = TallyMostVotes(5);
```

Actually in circom 2, public inputs are listed in main — for output-only public:

```circom
template TallyMostVotes(n) {
    signal input tally[n];
    signal output winner;
    ...
}
component main = TallyMostVotes(5);
```

And mark winner public in component main — check circom docs. Standard pattern:

```circom
component main { public [winner] } = TallyMostVotes(5);
```

where winner is output - may need `signal output winner` and `main {public [winner]}`.

- [ ] **Step 3: Soundness test — wrong public winner rejected**

```javascript
  it("rejects tampered winner", async () => {
    const tally = [120, 340, 90, 50, 200];
    const { proof, publicSignals } = await groth16FullProve(CIRCUIT, { tally });
    publicSignals[0] = "0"; // lie about winner
    expect(await groth16Verify(CIRCUIT, publicSignals, proof)).toBe(false);
  });
```

- [ ] **Step 4: Run tests, commit**

```bash
git add circuits/tally_most_votes.circom test/tally_most_votes.test.mjs
git commit -m "feat: most-votes baseline tally circuit"
```

---

### Task 5: Extension tally — Argentina ballotage rules

**Files:**
- Create: `circuits/tally_argentina_ballotage.circom`
- Create: `test/tally_argentina.test.mjs`
- Create: `data/fixtures/elected_45.json`, `elected_40_10.json`, `ballotage.json`

**Interfaces:**
- Private input: `tally[n]`
- Public outputs: `elected_first_round`, `winner`, `runoff_a`, `runoff_b`
- Produces: all scenarios from design spec

- [ ] **Step 1: Create fixtures**

`data/fixtures/elected_45.json`:
```json
{ "tally": [46, 20, 15, 10, 9], "elected_first_round": 1, "winner": 0, "runoff_a": 0, "runoff_b": 0 }
```

`data/fixtures/elected_40_10.json`:
```json
{ "tally": [42, 28, 15, 10, 5], "elected_first_round": 1, "winner": 0, "runoff_a": 0, "runoff_b": 0 }
```

`data/fixtures/ballotage.json`:
```json
{ "tally": [42, 35, 12, 6, 5], "elected_first_round": 0, "winner": 0, "runoff_a": 0, "runoff_b": 1 }
```

- [ ] **Step 2: Failing tests (one per fixture + soundness)**

```javascript
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, it, expect, beforeAll } from "vitest";
import { ROOT, compileCircuit, groth16FullProve, groth16Verify } from "./helpers.mjs";
import { execSync } from "node:child_process";

const CIRCUIT = "tally_argentina_ballotage";
const fixtures = ["elected_45", "elected_40_10", "ballotage"];

describe("tally_argentina_ballotage", () => {
  beforeAll(() => {
    compileCircuit(path.join(ROOT, "circuits", `${CIRCUIT}.circom`), CIRCUIT);
    execSync(`node scripts/setup.mjs ${CIRCUIT}`, { stdio: "inherit", cwd: ROOT });
  });

  for (const name of fixtures) {
    it(`completeness: ${name}`, async () => {
      const fx = JSON.parse(
        readFileSync(path.join(ROOT, "data/fixtures", `${name}.json`), "utf8"),
      );
      const { proof, publicSignals } = await groth16FullProve(CIRCUIT, { tally: fx.tally });
      expect(publicSignals[0]).toBe(String(fx.elected_first_round));
      expect(publicSignals[1]).toBe(String(fx.winner));
      expect(publicSignals[2]).toBe(String(fx.runoff_a));
      expect(publicSignals[3]).toBe(String(fx.runoff_b));
      expect(await groth16Verify(CIRCUIT, publicSignals, proof)).toBe(true);
    });
  }

  it("soundness: wrong runoff pair rejected", async () => {
    const fx = JSON.parse(
      readFileSync(path.join(ROOT, "data/fixtures", "ballotage.json"), "utf8"),
    );
    const { proof, publicSignals } = await groth16FullProve(CIRCUIT, { tally: fx.tally });
    publicSignals[2] = "2";
    expect(await groth16Verify(CIRCUIT, publicSignals, proof)).toBe(false);
  });
});
```

- [ ] **Step 3: Implement `circuits/tally_argentina_ballotage.circom`**

Core logic (pseudocode structure for implementer):

```circom
pragma circom 2.1.9;

include "lib/argmax.circom";
include "circomlib/comparators.circom";

template TallyArgentinaBallotage(n) {
    signal input tally[n];
    signal output elected_first_round;
    signal output winner;
    signal output runoff_a;
    signal output runoff_b;

    signal total;
    var s = 0;
    for (var i = 0; i < n; i++) { s += tally[i]; }
    total <== s;

    component first = ArgMax(n);
    component second = ArgMaxSecond(n);
    for (var j = 0; j < n; j++) { first.values[j] <== tally[j]; }
    second.values[j] <== tally[j]; // wire in loop
    second.firstIndex <== first.indexOut;

    signal t_first;
    signal t_second;
    t_first <== first.valueOut;
    t_second <== second.valueOut;

    // cond_45: t_first * 100 > 45 * total
    signal lhs45; lhs45 <== t_first * 100;
    signal rhs45; rhs45 <== 45 * total;
    component gt45 = GreaterThan(32);
    gt45.a <== lhs45;
    gt45.b <== rhs45;

    // cond_40: t_first * 100 >= 40 * total
    component ge40 = GreaterThanEq(32);
    ge40.in[0] <== t_first * 100;
    ge40.in[1] <== 40 * total;

    // margin: (t_first - t_second) * 100 > 10 * total
    component gtMargin = GreaterThan(32);
    gtMargin.a <== (t_first - t_second) * 100;
    gtMargin.b <== 10 * total;

    signal cond_40_10;
    cond_40_10 <== ge40.out * gtMargin.out;

    signal elected;
    elected <== gt45.out + cond_40_10 - gt45.out * cond_40_10; // OR

    elected_first_round <== elected;

    // winner = first.index if elected else 0
    winner <== elected * first.indexOut;

    // runoff = if NOT elected: first and second index, else 0
    signal notElected;
    notElected <== 1 - elected;
    runoff_a <== notElected * first.indexOut;
    runoff_b <== notElected * second.indexOut;
}

component main { public [elected_first_round, winner, runoff_a, runoff_b] } = TallyArgentinaBallotage(5);
```

Fix wiring bugs during implementation (ArgMaxSecond loop, OR gate, public signal order).

- [ ] **Step 4: Run tests until all fixtures pass**

Run: `npm test -- test/tally_argentina.test.mjs`

- [ ] **Step 5: Commit**

```bash
git add circuits/tally_argentina_ballotage.circom test/tally_argentina.test.mjs data/fixtures/
git commit -m "feat: Argentina ballotage tally circuit with fixtures"
```

---

### Task 6: End-to-end script + mock election

**Files:**
- Create: `scripts/prove_tally.mjs`, `scripts/verify.mjs`
- Create: `data/election_example.json`

**Interfaces:**
- Consumes: fixture or CLI path to tally JSON
- Produces: `build/<circuit>/proof.json`, `public.json`

- [ ] **Step 1: `scripts/prove_tally.mjs`**

```javascript
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { groth16FullProve } from "../test/helpers.mjs";
import * as snarkjs from "snarkjs";

const circuit = process.argv[2] ?? "tally_argentina_ballotage";
const inputPath = process.argv[3] ?? "data/fixtures/ballotage.json";
const input = JSON.parse(readFileSync(inputPath, "utf8"));

const { proof, publicSignals } = await groth16FullProve(circuit, { tally: input.tally });
const out = path.join("build", circuit);
writeFileSync(path.join(out, "proof.json"), JSON.stringify(proof, null, 2));
writeFileSync(path.join(out, "public.json"), JSON.stringify(publicSignals, null, 2));
console.log("public signals:", publicSignals);
```

- [ ] **Step 2: `scripts/verify.mjs`** — reads proof + public, prints VALID/INVALID

- [ ] **Step 3: Manual E2E**

```bash
npm run compile
node scripts/setup.mjs tally_argentina_ballotage
node scripts/prove_tally.mjs tally_argentina_ballotage data/fixtures/elected_45.json
node scripts/verify.mjs tally_argentina_ballotage
```

Expected: VALID

- [ ] **Step 4: Commit**

```bash
git add scripts/prove_tally.mjs scripts/verify.mjs data/election_example.json
git commit -m "feat: CLI prove/verify for tally circuits"
```

---

### Task 7: Benchmarks

**Files:**
- Create: `scripts/benchmark.mjs`
- Create: `benchmarks/results.json` (gitignored or committed per preference — commit for course reproducibility)

**Interfaces:**
- Measures per circuit: constraints (from r1cs), prove time ms, verify time ms, proof bytes
- Compares `tally_most_votes` vs `tally_argentina_ballotage` on same random tallies

- [ ] **Step 1: Implement benchmark script**

```javascript
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { performance } from "node:perf_hooks";
import { groth16FullProve, groth16Verify, BUILD, ROOT } from "../test/helpers.mjs";
import * as snarkjs from "snarkjs";

const circuits = ["tally_most_votes", "tally_argentina_ballotage"];
const tally = [42, 35, 12, 6, 5];
const results = { hardware: "DOCUMENT_CPU_RAM", timestamp: new Date().toISOString(), rows: [] };

for (const circuit of circuits) {
  const t0 = performance.now();
  const { proof, publicSignals } = await groth16FullProve(circuit, { tally });
  const proveMs = performance.now() - t0;

  const t1 = performance.now();
  await groth16Verify(circuit, publicSignals, proof);
  const verifyMs = performance.now() - t1;

  const r1cs = await snarkjs.r1cs.info(path.join(BUILD, circuit, `${circuit}.r1cs`));
  results.rows.push({
    circuit,
    constraints: r1cs.nConstraints,
    proveMs,
    verifyMs,
    proofBytes: Buffer.byteLength(JSON.stringify(proof)),
  });
}

mkdirSync(path.join(ROOT, "benchmarks"), { recursive: true });
writeFileSync(path.join(ROOT, "benchmarks", "results.json"), JSON.stringify(results, null, 2));
console.table(results.rows);
```

- [ ] **Step 2: Run and paste hardware info into results**

Run: `npm run benchmark`

- [ ] **Step 3: Commit results + script**

```bash
git add scripts/benchmark.mjs benchmarks/results.json
git commit -m "feat: benchmark most-votes vs argentina tally"
```

---

### Task 8: GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: CI workflow**

```yaml
name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
      - name: Install circom
        run: |
          curl -L https://github.com/iden3/circom/releases/download/v2.1.9/circom-linux-amd64 -o circom
          chmod +x circom
          sudo mv circom /usr/local/bin/circom
      - run: npm ci
      - name: Download powers of tau
        run: |
          mkdir -p build
          curl -L -o build/powersOfTau28_hez_final.ptau https://hermez.s3-eu-west-1.amazonaws.com/powersOfTau28_hez_final.ptau
      - run: npm run compile
      - run: npm test
```

- [ ] **Step 2: Push to GitHub, confirm badge green**

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run completeness and soundness tests"
```

---

### Task 9: README (course report)

**Files:**
- Modify: `README.md`

**Interfaces:**
- ≤ 1500 words
- Sections 1–6 per course rubric
- Link to CI badge
- Build/run instructions
- Statement: solo authorship

- [ ] **Step 1: Write README sections using design spec + benchmark table**

Include:
- Argentina rules verbatim (45%, 40%+10pp, ballotage pair)
- Kryvos trust model caveat (talliers see tally)
- Comparison: your benchmark rows + paper Figure 1 trend (tally dominated by opening proof; result function negligible)

- [ ] **Step 2: Word count check**

Run: `wc -w README.md` — must be ≤ 1500

- [ ] **Step 3: Final commit**

```bash
git add README.md
git commit -m "docs: final project report README"
```

---

## Spec coverage self-review

| Spec requirement | Task |
|------------------|------|
| Ballot single-vote | Task 3 |
| Most Votes baseline | Task 4 |
| Argentina `fres` + runoff pair | Task 5 |
| Completeness tests | Tasks 3–5 |
| Soundness tests | Tasks 4–5 |
| Benchmarks | Task 7 |
| CI | Task 8 |
| README rubric | Task 9 |
| Mock BB / scripts | Task 6 |
| Pedersen commitments | Out of scope per spec |

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-07-kryvos-argentina-ballotage.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — implement task-by-task in this session with checkpoints

**Which approach do you want?**

Also: implementation should live in a **new repo** (`kryvos-argentina-ballotage`). Say if you want me to start Task 1 and create that repo now (inside or outside Vela).
