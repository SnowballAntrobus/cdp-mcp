# CDP Forensics — institutional knowledge

Permanent reference: empirical findings about real CDP behavior (and the adjacent
macOS, Python, and MCP-client behavior that shapes how we drive CDP), discovered
through implementation and curation work. Each finding is a fact that cost real
investigation time and would otherwise have to be rediscovered; each cites its
source (doc, code comment, or commit) so the depth is one hop away.

**Provenance and ID scheme.** Findings `5.1.x`–`5.5.x` were extracted verbatim
(lightly edited for standalone reading) from `docs/phase-1b-handoff.md` §5 — the
numbering is preserved because code comments and commit messages already cite it
(e.g. "phase-1b handoff 5.5"). "Task N" in those entries means a Phase 1b task.
Findings `P2-n` were gathered during Phase 2; `P3-n` during Phase 3 curation.
Section 5.4 (test infrastructure findings) lives in `docs/testing-principles.md`.

**The evidence hierarchy** (institutionalized during Phase 3 curation, commit
`506a20b`): **binaries decide, source explains, manual describes, SoundThread +
afta8 prioritize and parameterize.** When these disagree — and they do, in every
tranche — the probed binary wins; the CDP8 source tree explains *why*; the HTML
manual and banners are treated as claims to verify; the two downstream toolkits
tell us which programs and parameter regions musicians actually reach for.

---

## 5.1 CDP-specific behavior (Phase 1b, macOS r8)

**5.1.1 — Stock CDP r8 has no `cdp` binary.** The closest binary names are `cdparams`, `cdparse`, etc. Before Phase 1b Task 4, every production session recorded `cdp_version: "unknown"` because `_detect_version()` looked for `cdp --version`. The fix: probe primary, fall back to walking `cdp_path.parts` in reverse for a `cdp[_-]?r?\d+(\.[\w.]+)?` pattern match. Most installs match `cdpr8` directly → version becomes `"r8"`. Documented in `src/cdp_mcp/config.py`.

**5.1.2 — CDP r8 emits error-class messages to STDOUT, not stderr.** Verified empirically with `pvoc synth` refuse-to-clobber and `sndinfo chandiff` channel mismatch. The error parser searches `combined = stderr + "\n" + stdout` for the patterns that benefit. Documented in `src/cdp_mcp/error_parsing.py`.

**5.1.3 — Real CDP error phrasings** (Task 5 refinement):
- Refuse-clobber: `"Cannot open output file ..."` (uses "open" not "create" — the broader regex matches both)
- Channel mismatch: `"Process only works with STEREO files."` or `"Process only works with MONO files."`
- "Application doesn't work with this type of infile" was considered as a `channel_mismatch` pattern and **rejected as too generic** — it could mean wrong sample rate, wrong format, wrong encoding, anything. A misleading `fix` hint is worse than no specific entry.

**5.1.4 — `pvoc anal` and `pvoc synth` are byte-deterministic** for the same input + CDP version. Verified empirically by hashing outputs across multiple runs in Tasks 10 and 11. The entire derivative cache premise rests on this; both directions confirmed. SHA of test PVOC anal output: `e4e6954…`. SHA of test PVOC synth output: `26fb3dba…`. *(Refined by P2-1 below: "byte-deterministic" holds within a CDP tick window; decoded samples are always identical.)*

**5.1.5 — Real PVOC scales nonlinearly with input duration.** Empirically on Apple Silicon M-series, 10 minutes of mono 44.1 kHz wav analyzes in ~5 seconds. The naive linear extrapolation from "37ms for a few-second wav" gives multi-hour estimates for 60+ seconds of PVOC work, which is wrong by orders of magnitude. There must be substantial per-call overhead that dominates at small sizes, then very efficient streaming behavior at larger sizes. **Don't extrapolate PVOC timings linearly.**

**5.1.6 — `modify brassage` SIGILLs (silently, no stderr) on absolute paths whose ancestry contains a `.`** Root cause is brassage's `_cdptemp1` sibling-derivation logic. Workaround: cwd-relative argv paths for in-session writes; absolute for cache reads outside the session tree. The acceptance test uses session name `frog_acceptance_v1.0` to lock the regression. Documented in `src/cdp_mcp/processing.py:_argv_path` and `tests/test_acceptance.py`.

**5.1.7 — PVOC `.ana` files are 10-20× the source WAV size.** Window-dependent. Surfaced when the 1 GB output cap kept firing on long-input PVOC steps. The disk watchdog message in `src/cdp_mcp/pvoc.py` mentions this.

**5.1.8 — CDP binaries are inconsistent about exit codes when printing the usage banner.** Some exit 0, others 1, 2, or 255. The right invariant is *behavioral*: "expected output missing AND 'Usage:' in stderr OR stdout", regardless of exit code. Documented in `src/cdp_mcp/error_parsing.py` for `_USAGE_BANNER_RE`.

**5.1.9 — `extend loop` may be silent during execution.** The design doc flagged this as an open question for stress-testing the keepalive. Phase 1b Task 13 sidestepped by using `fake_subprocess --sleep 80 --stderr-lines 20` instead — the keepalive is clock-driven, not stderr-driven, so the empirical question is moot for that test's purpose.

## 5.2 macOS-specific behavior

**5.2.1 — macOS's ReportCrash routes SIGILL/SIGABRT/SIGSEGV/SIGBUS/SIGFPE/SIGTRAP through a crash dialog.** Test fakes simulating CDP crashes should use **SIGTERM** (or SIGKILL/SIGINT/SIGHUP) to avoid triggering the dialog during every test run. Phase 1b Task 2's `--cdp-die-on-dot-path` was originally `--cdp-sigill-on-dot-path` and used SIGILL; the rename and signal change preserve the test's purpose (production only checks `exit_code != 0`, doesn't care about the specific signal) while avoiding ReportCrash noise. Documented in the `_trigger_signal_death` docstring in `tests/fixtures/fake_subprocess.py`.

**5.2.2 — macOS `/var → /private/var` symlink.** When test fixtures put cache directories under `tmp_path` (which resolves to `/var/folders/...` on macOS but `/private/var/folders/...` after `Path.resolve()`), the security gate's path-scope check fails because it compares resolved vs unresolved paths. Fix: `Path.resolve()` on the cache root before constructing the SessionManager in tests. Surfaced in the Phase 1b Task 10 verification driver.

## 5.3 Python / packaging behavior

**5.3.1 — `pip install -e ".[dev]"` may install into a different Python's site-packages.** Phase 1b Task 6's verification surfaced this: the venv's active Python was 3.11, but `pip install -e ...` installed into `python3.13/site-packages` (system-wide). The fix is `python -m pip install ...` which binds the install to the active interpreter. Worth flagging if you ever see "module not found" errors after a fresh install in a multi-Python-version environment.

**5.3.2 — `monkeypatch.setattr("module.X", ...)` doesn't catch from-imports.** If you do `from module import X` in caller code, you have to patch `caller_module.X`, not `module.X`. This bit Phase 1b Task 7 when patching `OUTPUT_FILE_SIZE_CAP_BYTES`: must patch BOTH `cdp_mcp.limits.OUTPUT_FILE_SIZE_CAP_BYTES` AND `cdp_mcp.tools.process.OUTPUT_FILE_SIZE_CAP_BYTES` because process.py from-imports.

**5.3.3 — `importlib.reload(module)` is required to test env-var rebinding.** Module-level constants computed at import (like `OUTPUT_DURATION_CAP_S = _resolve_positive_float(...)`) are frozen at first import. A test like "set env var, expect new constant value" needs `importlib.reload(limits)` after `monkeypatch.setenv`. `tests` has `test_env_var_override_round_trip` doing exactly this. Without that, future "lazy import" optimizations could silently break env-var overrides without test coverage.

**5.3.4 — `matplotlib.use("Agg")` must be called programmatically, before any pyplot import.** The `MPLBACKEND=Agg` environment variable is unreliable across launch wrappers (`uvx`, `npx`, IDE-spawned servers may drop or override it). A GUI backend on a headless server hangs `visualize()` indefinitely on first call. The forcing lives at the top of `src/cdp_mcp/visualization.py` (module-level, before pyplot).

**5.3.5 — `audioread` deprecation in Python 3.14.** `audioread` (transitive via librosa) deprecates `aifc` and `sunau` in 3.14. Mitigation: rely on `soundfile` exclusively (already in deps; librosa prefers it when available). `LIBROSA_AUDIO_BACKEND=soundfile` env var available in librosa 0.10+ for explicit selection. No `audioread=False` parameter on `librosa.load()` — that was a v6 mis-attribution in the design doc.

## 5.4 Test infrastructure findings

Relocated to `docs/testing-principles.md` (kept there with their original
`5.4.x` identifiers, alongside the Phase 1b test-infrastructure description
and the Phase 2/3 additions).

## 5.5 Determinism findings (cache correctness)

**5.5.1 — PVOC anal: deterministic** (`e4e6954…` across runs)
**5.5.2 — PVOC synth: deterministic** (`26fb3dba…` across runs)
**5.5.3 — The other five Phase 1a entries** (`blur blur`, `modify brassage`, `extend loop`, `filter sweeping`, `morph morph`) were presumed deterministic in Phase 1b but not byte-compared. **Superseded:** the Phase 2 determinism sweep settled this — all five are *sample*-deterministic with header-only byte instability (see P2-1), recorded in `docs/phase-2-determinism.md`. Phase 3 curation then verified determinism empirically for every new entry as part of the probe protocol (reruns ≥ 1.1 s apart, decoded-sample sha comparison — see the tranche transcripts under `docs/curation/`). Phase 4 Task 12 (process-output cache) must still re-verify against the then-current CDP version and entry set, and must key on **sample equivalence, not raw-file sha256**.

---

## P2 — Phase 2 findings (2026-05, hardening recorded 2026-07-13)

**P2-1 — CDP r8 embeds a tick counter in every output file's metadata; outputs are sample-deterministic but byte-unstable across tick boundaries.** `.wav` outputs carry the counter in a 32-bit LE field inside the PEAK chunk (~byte 80) and in a `LIST/adtl/note/sfif DATE` ASCII-hex subchunk; `.ana` outputs carry the same DATE field at offset 179 (a single-byte diff between consecutive ticks was observed against 2,866,661 identical bytes of frame data). Paired runs in the same tick window are byte-identical; runs straddling a boundary differ only in those metadata bytes; decoded samples were bit-identical in every observed case. Consequence: any content-addressed cache over CDP outputs must hash decoded samples (or header-stripped bytes), never raw files. This finding surfaced as a ~1-in-3 flake in the Phase 2 determinism sweep and was traced via env-guarded byte-level diagnostics. Source: `docs/phase-2-determinism.md` (full traces, ruled-out hypotheses, Phase 4 instructions).

**P2-2 — Process-group kill needs strict pid validation (`killpg(0)` kills *your own* process group).** The Phase 2 hardening pass (audit item C1, commit `d95d865`) wrapped the subprocess lifecycle in try/finally and switched to `start_new_session=True` + `os.killpg` — a plain `proc.kill()` leaves forked CDP children holding the stdout/stderr pipe write-ends, so the stream readers never see EOF and the tool call hangs past its own timeout. The trap: `os.killpg(pid, ...)` with pid 0 kills the caller's own process group (i.e., the test runner or server), and negative/1 pids target other groups entirely — and test doubles (MagicMock procs) present non-int pids. The guard is `os.name == "posix" and type(pid) is int and pid > 1` before killpg, falling through to `proc.kill()` otherwise. Source: `src/cdp_mcp/subprocess_core.py:_kill_process_tree` (comment records the reasoning); `docs/phase-2-audit-2026-07-13.md` §2.1.

**P2-3 — `.ana` duration is readable via `sfprops -d`, not `dirsf` or `pvoc info`.** Design doc v9 committed `dirsf` as the shell-out for pre-converted `.ana` durations; verification against r8 found `dirsf` is a directory-listing utility and `pvoc info` doesn't exist (pvoc's modes are anal/synth/extract). `sfprops -d <path>` writes exactly one float to stdout and is the right tool — and beat writing a custom parser for CDP's `.ana` header. Source: `docs/cdp-mcp-design.md` (Phase 2 operational fixes); `docs/phase-2-audit-2026-07-13.md` §1 Task 02b.

**P2-4 — CDP's own usage banners can state mathematically wrong formulas.** The Phase 2 curation formula audit caught `sweepfrq`'s banner giving a bound as `infiledur/2` where the true bound is `1/(2·infiledur)` — fixed in the curated entry and pinned in `tests/test_curation_formulas.py`. First instance of the pattern that Phase 3 turned into policy: banners are claims, not specifications. Source: `docs/phase-2-curation-audit.md`; `docs/phase-2-audit-2026-07-13.md` §1 Task 05.

---

## P3 — Phase 3 findings (2026-07 curation tranches + QA)

Environment for the curation findings: CDP8 built from source on Linux x86_64
(`scripts/build_cdp8_linux.sh`; banners self-report "CDP Release 7.1 2016"),
findings re-verified against macOS r8 via the CDP-gated suite. Full probe
transcripts: `docs/curation/tranche{1,2,3}_{spectral,timedomain}.md` (+
machine-readable `*_findings.json`).

### Stochasticity and seeding

**P3-1 — `blur scatter` is NOT stochastic (design-doc assumption overturned).** The design doc flagged it as a phase-sensitive/stochastic candidate; empirically, identical args give bit-identical output on every run — including runs > 2 s apart and runs with `-r`. Source-confirmed: `scat_preprocess()` (`dev/blur/ap_blur.c`) never calls `initrand48()`, and CDP's `drand48` shim (`dev/sfsys/osbind.c`) wraps unseeded `rand()`. No seed flag exists. Curated `stochastic: false, phase_sensitive: false`. Source: `docs/curation/tranche1_spectral.md` §2; commit `e6f95d4`.

**P3-2 — `blur drunk` IS stochastic and unreproducible: `srand(time(NULL))`, no seed flag.** Identical argv twice → different decoded output; `-s`/`-r` are rejected as unknown flags. Source-confirmed: `drnk_preprocess()` calls `initrand48()`, which is `srand(time(NULL))` (`dev/sfsys/osbind.c:331`). Corollary: two runs inside the same wall-clock second silently produce *identical* output. Curated `phase_sensitive: true`, `stereo_link_default: "related"`, with `known_issues` recording that there is no seed to drive. Source: `docs/curation/tranche1_spectral.md` §3.

**P3-3 — The clock-seed same-second collision trap (general CDP pattern).** CDP's `initrand48()` seeds from wall-clock seconds, so *any* unseeded stochastic program run twice inside one second reproduces itself exactly — observed directly on `extend zigzag` (back-to-back unseeded runs identical; runs 1.5 s apart different). This poisons naive determinism probes in both directions. Probe methodology across tranches 2–3 therefore mandates ≥ 1.1 s between unseeded paired runs. Source: `docs/curation/tranche1_timedomain.md` §5; methodology headers of `docs/curation/tranche2_*.md` / `tranche3_*.md`.

**P3-4 — `modify revecho`'s seed flag is a no-op off-Windows (`_WIN32` seeding split); the "random" LFO path is deterministic here.** Negative-lfofreq ("random oscillations") runs are identical unseeded vs seeded vs across distinct seeds — yet the random path *is* taken (+20 vs −20 Hz differ). Mechanism, source-confirmed: `dev/newsfsys/osbind.c` defines its own `drand48() { return rand()/RAND_MAX; }` which overrides libc's at link time (`nm` shows `T drand48` in the binary), while `dev/modify/delay.c` seeds via glibc `srand48(seed)` on non-Windows — a generator the shim never reads — and only calls `srand(seed)` under `_WIN32`, where the flag presumably works. Curated `stochastic: false`, `version_sensitive: true`, seed exposed with the no-op documented. Source: `docs/curation/tranche2_timedomain.md` §1.

**P3-5 — `texture simple` is genuinely stochastic with a WORKING `-r` seed — CDP's first controllable-seed find — and is mono-in/stereo-out.** Unseeded runs differ in decoded samples *and frame count*; `-r5` twice → identical; `-r5` vs `-r9` → different. Every run produces stereo from a mono input (stereo input refused). The entry itself was dropped over the `aux_file` schema gap (notedata text file), but the probe data is preserved: this is the seeding/channel profile the stereo seed-link machinery has been waiting for — except the stereo-out shape means it still doesn't exercise the mono-only L/R split. Source: `docs/curation/tranche3_timedomain.md` §6; `docs/curation/tranche3_timedomain_findings.json` (dropped record).

### Documentation-vs-binary divergences

**P3-6 — The banner-only `-t` tail bug class (×2, filter group): omitting `-t` appends exactly +1.00 s.** `filter sweeping` (curated in Phase 1a) carries a `tail` parameter that appears in the binary's banner but not in cgrofilt.htm — first flagged as an anomaly in `docs/phase-2-determinism.md` (caveats), then confirmed against the binary: no `-t` → +1.000 s appended (4.000 s → 5.000 s; `-t0.5` → 4.500 s; commit `7e88f3f`, reproduced identically on the Linux source build and macOS r8). `filter lohi` has the *same* banner-only tail with the same +1.00 s default (tranche 1), plus a residual ring-out at `-t0` that grows with filter order. Entries pin `tail` default 1.0 and model `indur + tail`. Source: `docs/curation/tranche1_timedomain.md` §7; `docs/phase-2-determinism.md` caveats; commit `7e88f3f`.

**P3-7 — The distort family accepts breakpoint files where its documentation is silent (×4).** `distort multiply`: banner AND manual silent, binary accepts a time-varying multiplier (SoundThread's automatable flag agreed with the binary). `distort average`: banner silent, manual confirms, binary accepts. `distort interpolate`: the banner has a copy-paste bug — "multiplier and cyclecnt may vary over time" though INTERPOLATE has no cyclecnt parameter (line lifted from distort repeat; the manual is correct). `distort divide`: banner AND manual silent, binary accepts (fourth undocumented-envelope find). Each capability was proven the strong way: the breakpointed render differs from *both* endpoint scalar renders. Source: `docs/curation/tranche1_timedomain.md` §3, `tranche2_timedomain.md` §2/§4, `tranche3_timedomain.md` §2; commits `e6f95d4`, `4777440`, `e737082`.

**P3-8 — `specfnu` mode 19 crashes at teardown (`double free or corruption (out)`, exit 134/SIGABRT) *after* writing a valid, resynthesisable `.ana`** — the exit contract fails, not the DSP, so any harness treating nonzero exit as failure rejects good output. Additionally, *every* specfnu run on this build — successes included — prints `WARNING: failed to write PEAK data`; harness and error-parsing code must not treat that stderr line as failure. Mode 19 was disqualified and mode 1 (NARROW FORMANTS) pinned after an 8-mode survey with non-silence checks. Source: `docs/curation/tranche3_spectral.md` §1; commit `e737082`.

**P3-9 — `spec magnify` silently emits zero-length audio when `dur` ≤ the analysis window length.** The manual's "MUST BE > the analysis window length" is unenforced: exit 0, a structurally valid `.ana` that resynthesises to ZERO frames — no error, empty audio. (Its `dur` otherwise sets output duration exactly, independent of input duration.) A silent-success trap for any pipeline that trusts exit codes; pinned in the entry's `known_issues`. Source: `docs/curation/tranche2_spectral.md` §5.

**P3-10 — `focus fold` silently swaps reversed bounds, and a zero-width band is a silent success.** `focus fold in.ana out.ana 1000 500` exits 0 with output bit-identical to `500 1000` — source: `if(hifrq_limit < lofrq_limit) swap(...)` (`dev/focus/focus.c:158`). And `lofrq == hifrq` exits 0 producing a `.ana` that resynthesises to pure silence. Same silent-swap behavior found independently in `sfedit cut` (reversed start/end accepted, byte-identical to the correct order — tranche 2). Source: `docs/curation/tranche3_spectral.md` §3; `docs/curation/tranche2_timedomain.md` §6.

**P3-11 — `extend doublets` silently drops the final segment — partial or exactly boundary-aligned — and `segdur == indur` yields a 0-frame output at exit 0.** Source-confirmed (`dev/extend/iterate.c do_doubling` + `extdcon.h SPLICEDUR`): each written repetition loses one fixed 5 ms crossfade splice, and the write is skipped whenever the input runs out during a segment's build, *including exactly at its end*. Hence the pinned duration model `repets * (segdur - 0.005) * ((indur - 0.0001) // segdur)` (sample-exact modulo splice quantisation) — and at the allowed maximum `segdur = indur`, exit 0 with a 0-frame file plus `WARNING: Can't close output sf-soundfile`. Source: `docs/curation/tranche3_timedomain.md` §4.

### Substrate, harness, and client constraints

**P3-12 — Stereo audio cannot even be *analysed*: `pvoc anal` refuses stereo with exit 255.** `Application doesn't work with this type of infile.` — so every spectral entry is `channel_constraint: "mono"` at the `.ana` level; the refusal happens upstream at PVOC, not in the individual spectral programs. Reproduced in all three tranches. Source: `docs/curation/tranche1_spectral.md` (shared channel-constraint section; reproduced in tranches 2–3).

**P3-13 — CDP's refuse-to-overwrite poisons probe batches (fresh-output-name hygiene).** CDP refuses to overwrite an existing output file with exit 255 (`ERROR: INVALID DATA / ERROR: Cannot open output file ...`). Two focus fold edge-probes and one distort divide breakpoint probe initially reported spurious 255s because they reused output names from a failed batch; re-run against fresh names they exit 0. Probe protocol now requires fresh output names per run. (Engine-side, this is the same behavior the Phase 1a pre-delete contract handles.) Source: `docs/curation/tranche3_spectral.md` (probe-hygiene note); `docs/curation/tranche3_timedomain.md` (probe trap).

**P3-14 — libsndfile cannot open CDP `.ana` files; measure spectral outputs via a synth round-trip.** The 2026-07-14 macOS QA run failed all 16 spectral duration-formula rows with `LibsndfileError`: the pinned harness measured process outputs with `sf.info()` directly — fine for the original all-time-domain rows, wrong for `.ana` outputs, which the curation agents had measured via pvoc-synth round-trips *outside* the shared test. Integration bug, not platform divergence. Fix: `_measured_duration()` routes `.ana`/`.pvx` through the engine's own `synth_for_audition` before measuring (duration-faithful modulo frame padding, per 5.5.2). The transferable lesson lives in `docs/testing-principles.md`: integration code extending a pinned table must EXECUTE the table, not just collect it. Source: commit `e97319d`; `tests/test_curation_formulas.py`.

**P3-15 — Claude Desktop rejects MCP tool results over ~1 MB.** Surfaced in 2026-07-14 manual QA when a 3-panel `progression()` composite blew the cap. Composite-producing tools now downscale in place to ≤ 700 KB on disk (base64 inflates ×4/3, plus envelope margin) via `visualization.shrink_png_under_cap`; the full-resolution path is always reported for external viewing. Source: `docs/cdp-mcp-design.md` Open Questions (resolved entry); `src/cdp_mcp/visualization.py`, `src/cdp_mcp/tools/compare.py`, `src/cdp_mcp/tools/progression.py`.

## P5 — Phase 5 findings (2026-07)

**P5-1 — `filter bank` hangs on pre-June-2025 binaries: unconditional out-of-bounds heap write, fixed upstream in CDP8 `11cdcb4`.** The 2026-07-15 macOS QA run's single failure (`test_duration_model_matches_cdp[filter-bank-...]`, 120 s timeout) reproduced nowhere on the Linux source build (0.00 s wall, exit 0, identical argv). Root cause, source-confirmed: before commit `11cdcb4` (2025-06-05, "fixed alloc bug for fixed filter bank"), `filter_process()` wrote `dz->iparam[FLT_FRQ_INDEX]` (index 21) and `dz->iparam[FLT_TIMES_CNT]` (index 20) unconditionally at the end of the normalization pre-pass — but FLTBANKN's internal-param structure is `"000diiiiid"` (`ap_filter.c set_legal_internalparam_structure`), which never allocates those slots; they exist only for the varybanks (FLTBANKV `"00iidiiiiididiiid"`). Every `filter bank` run on an old binary therefore corrupts the heap past `iparam`; observed as a hang on the shipped macOS r8 binary, but any UB outcome is possible. FLTBANKN is the only curated filter mode with the normalization pre-pass (`do_norm`), so `sweeping`/`lohi` are unaffected — consistent with the QA run failing exactly one row. The Linux substrate builds post-fix source and cannot reproduce it. Entry: `version_sensitive: true` + `known_issues` lead item; remedy is rebuilding `filter` from current CDP8 source (clean upstream cmake build, no patches needed — see `scripts/build_cdp8_linux.sh` for the shape). Source: CDP8 `git show 11cdcb4`; `dev/filter/filters0.c`; `tests/test_curation_formulas.py` (row unchanged — it is correct against fixed binaries and now doubles as the binary-vintage detector).

**P5-2 — `newdelay` hangs at feedback ±1.0 despite advertising the range.** CDP's own banner declares feedback `(-1.000000 to 1.000000)`, but `feedback 1.0` never terminates (killed at 40 s; the tail length is determined by an internal level-decay test pass — `domulti_test`, "Checking levels and length of tail" — which cannot converge at |fb| = 1). The curated entry narrows the range to ±0.99, which completes in under a second; the duration expression (Padé ln approximation) deliberately over-predicts on every probed row (+0.7% to +37.1%, never under) so the duration cap stays safe. First-class landmine: a range CDP itself advertises is a hang. Source: `docs/curation/tranche8_seed_singles.md` §9; entry `known_issues`.

**P5-3 — `submix mix` WRAPS integer overload instead of clipping; `-g` is the native headroom valve, `-a` is a no-op.** Three full-level overlapping copies produce output equal to `wrap_int16(3x)` to 1 LSB — wraparound distortion, not saturation, and exit 0 with no warning. `submix getlevel 1 <mixfile>` is the native pre-flight (prints the exact max sample and required normalisation factor), and `-g<factor>` attenuates the float sum BEFORE 16-bit quantisation: applying getlevel's factor to the wrap case renders clean (correlation 1.0 with the ideal scaled sum, maxdiff ~1.5 LSB). The `-a` flag, by contrast, is byte-identical to omitting it on the same case (tranche-5 verification) — attenuation applied where it can no longer help. Entry exposes `atten` (-g) and carries the mandated pair in `known_issues`: overload WRAPS + run `submix getlevel 1` (via `execute()`; the mode digit is required) before mixing hot material. Stage headroom pre-mix — this rule is also load-bearing for Phase 6's `timeline()`. Source: `docs/curation/tranche7_unblocked.md` (submix mix section); tranche-5 `-a` verification; entry `known_issues`.

**P5-4 — `quirk` on unipolar material: exit 0 and a ZERO-FRAME output.** A one-sided click train (no zero crossings) through `quirk quirk 1` succeeds by CDP's lights — exit 0, no error text — and writes a 0-frame file. Nothing CDP-side guards it; the engine's output verification (nonzero frames) is the only net. Curated `known_issues` carries the trap; the generalizable lesson is that exit 0 + existing file is not success for waveset-domain programs on pathological material — verify frames. Source: `docs/curation/tranche8_seed_singles.md` §10; entry `known_issues`.
