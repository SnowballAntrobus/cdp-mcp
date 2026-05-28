# Phase 2 — `breakpoint_capable` curation review

## Why this exists

The Phase 1a curated entries were shipped with `breakpoint_capable: false` on 21 of 22 parameters — a conservative placeholder, never empirically verified against the CDP r8 binary. Phase 2 Task 6 will introduce a `breakpoint()` DSL constructor for envelope-driven parameter control; before that ships, the curation must reflect which parameters CDP actually accepts envelopes for. This doc records the empirical pass that resolved that question.

## Methodology

For each of the 22 curated parameters across the 5 entries:

1. **Capture the mode banner.** Run `<program> <mode>` (without further args) and read the usage section. Some banners contain an explicit "may vary over time" claim — that's a strong prior but not a substitute for verification.
2. **Construct a 2-point breakpoint envelope.** Two lines, `0.0 <low>` / `1.0 <high>`, with both values inside the parameter's `min`/`max` range.
3. **Invoke CDP** with the envelope substituted for the parameter at its argv position (positional or `-X<brk>` attached — CDP r8 rejects `-X <brk>` with a space).
4. **Classify by outcome**:
   - **Exit 0 + output file produced** → CDP accepts envelopes here → `breakpoint_capable: true`.
   - **`ERROR: ... brkpnt_files not permitted`** (on stdout or stderr — CDP r8 emits errors to either) → `breakpoint_capable: false`.
   - **Anything else** → forensic anomaly; surface for human review.

The probe script is at `/tmp/probe_breakpoint_capable.sh` during a working session and is reproducible from the methodology above. Outcomes are pinned in `tests/test_breakpoint_curation.py::_EXPECTED_BREAKPOINT_CAPABLE` — any drift between the JSONs and that table trips a test failure.

## Test environment

- CDP version (`detect_cdp().version`): `r8`
- CDP install root: `cdpr8/_cdp/_cdprogs` (x86_64 binaries running under Rosetta on arm64 macOS)
- Host OS / arch: `Darwin 24.6.0 (arm64)`
- Python: `3.13.2`
- Repo commit SHA: `3a7000e` (parent of the Task 5 changeset)

## Results

22 parameters classified — **6 True (5 new flips + 1 baseline)**, **16 False**, **0 anomalies**.

| Entry             | Param      | Status                            | Evidence |
| ----------------- | ---------- | --------------------------------- | -------- |
| `blur blur`       | `blurring` | True (already; baseline)          | Banner: "blurring may vary over time." Probe exit 0, output 2.87 MB |
| `extend loop`     | `cnt`      | False                             | `brkpnt_files not permitted` |
| `extend loop`     | `start`    | False                             | `brkpnt_files not permitted` |
| `extend loop`     | `len`      | False                             | `brkpnt_files not permitted` |
| `extend loop`     | `step`     | False (`-l<brk>`)                 | `brkpnt_files not permitted` |
| `extend loop`     | `splen`    | False (`-w<brk>`)                 | `brkpnt_files not permitted` |
| `extend loop`     | `scat`     | False (`-s<brk>`)                 | `brkpnt_files not permitted` |
| `filter sweeping` | `acuity`   | **True** (flip)                   | Banner: "ACUITY, LOFRQ, HIFRQ and SWEEPFRQ may all vary over time." Probe exit 0, output 531 KB |
| `filter sweeping` | `gain`     | False                             | Not in banner's "may vary" list; `brkpnt_files not permitted` |
| `filter sweeping` | `lofrq`    | **True** (flip)                   | Banner-confirmed; probe exit 0 |
| `filter sweeping` | `hifrq`    | **True** (flip)                   | Banner-confirmed; probe exit 0 |
| `filter sweeping` | `sweepfrq` | **True** (flip)                   | Banner-confirmed; probe exit 0 |
| `filter sweeping` | `tail`     | False (`-t<brk>`)                 | `brkpnt_files not permitted` |
| `filter sweeping` | `phase`    | False (`-p<brk>`)                 | `brkpnt_files not permitted` |
| `modify brassage` | `velocity` | **True** (flip)                   | No banner claim, but probe exit 0, output 259 KB (vs 351 KB scalar baseline — different duration since envelope changes speed dynamically) |
| `morph morph`     | `as`       | False                             | `brkpnt_files not permitted` |
| `morph morph`     | `ae`       | False                             | `brkpnt_files not permitted` |
| `morph morph`     | `fs`       | False                             | `brkpnt_files not permitted` |
| `morph morph`     | `fe`       | False                             | `brkpnt_files not permitted` |
| `morph morph`     | `expa`     | False                             | `brkpnt_files not permitted` |
| `morph morph`     | `expf`     | False                             | `brkpnt_files not permitted` |
| `morph morph`     | `stagger`  | False (`-s<brk>`)                 | `brkpnt_files not permitted` |

## `tail` anomaly — final resolution

Background (Task 4 forensic note): the `filter sweeping` knowledge JSON includes a `tail` parameter (`flag: "-t"`), but the CDP HTML docs at [cgrofilt.htm#SWEEPING](https://www.composersdesktop.com/docs/html/cgrofilt.htm) list only `-p phase` as an optional flag in SWEEPING mode.

Task 5 empirical pass settles it:

- **`-t` is a real flag in CDP r8.** Scalar probe `filter sweeping 2 in.wav out.wav 0.1 0.5 200 4000 1.0 -t0.3` succeeds with exit 0; the output is the expected ~0.3 s longer than the no-`-t` baseline. The mode banner shows `[-ttail]` in the USAGE line and a `TAIL: decay tail duration` description. The HTML docs are simply incomplete.
- **`-t` does NOT accept envelopes.** Probe `-tb_tail.brk` fails with `ERROR: Cannot read parameter 6 [tail.brk]: brkpnt_files not permitted.` The JSON's `breakpoint_capable: false` is correct.

Resolution: **keep `tail` in `filter_sweeping.json`**; **`breakpoint_capable` stays `false`**. The Task 4 conservative omission from the determinism-sweep canonical params was over-cautious — `tail` can be invoked as a scalar in any subsequent curation work without issue.

## Implications for Phase 2 Task 6

Task 6's `breakpoint()` DSL constructor will target 6 parameters across 3 entries:

- `blur blur`: `blurring`
- `filter sweeping`: `acuity`, `lofrq`, `hifrq`, `sweepfrq`
- `modify brassage`: `velocity`

The other 16 curated parameters reject envelopes at the CDP level and stay scalar-only. `extend loop` and `morph morph` have no envelope-capable parameters at all — Task 6's DSL has nothing to offer them.

## Schema additions (landed in Task 5)

Two fields added to `src/cdp_mcp/schema.py` ahead of where Task 8 will consume them:

- **`ParameterSpec.breakpoint_duration_source: Literal["input1", "input2", "max", "min"] | None`** — for multi-input entries, picks which input's duration anchors a relative-time breakpoint envelope. Enforced at the `KnowledgeEntry` level: must be `None` on single-input entries; required when `breakpoint_capable=True` on a multi-input entry. No current entry needs this field; `morph morph` is the only multi-input entry and none of its params are breakpoint-capable.
- **`KnowledgeEntry.default_length_strategy: str | None`** — default behavior when multi-input lengths differ. Accepts `"pad_with_fade"`, `"truncate_to_shortest"`, `"fail"`, `"stagger:<float>"`, or `None`. Set to `"stagger:0"` on `morph morph` (which has its own `-s` flag) and left `None` on the four single-input entries.

Both fields are pre-positioned for Task 8 (`combine cross` and the multi-input engine wiring).

## Caveats

- Single canonical input per probe (2 s synthetic noise burst). A future curation-expansion pass may discover edge cases where a parameter accepts envelopes only under certain input shapes — but the `brkpnt_files not permitted` error is generic enough that this is unlikely.
- Single CDP build (r8 from `cdpr8/_cdp/_cdprogs`). Re-verify if the CDP install changes.
- `morph morph` was probed in mode 1 (linear/exponential). Mode 2 (cosinusoidal spline) is not curated and was not probed; should it be added in a future curation expansion, its parameters need their own pass.
