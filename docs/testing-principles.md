# Test infrastructure principles

Permanent reference: how this project tests an engine whose core dependency is
a pile of 30-year-old C binaries that crash, lie in their banners, and embed
wall-clock ticks in their outputs. Extracted from `docs/phase-1b-handoff.md`
(§4.9 test infrastructure, §5.4 test-infrastructure findings — the `5.4.x`
identifiers are preserved because commits and comments cite them), then
extended with the Phase 2/3 principles that curation at scale forced.

Companion: `docs/forensics.md` (the CDP behavior these principles exist to
survive).

---

## 1. The substrate rule (5.4.5)

**Substrate choice depends on what the test verifies.** Tests verifying MECHANISMS (clock-driven keepalive, atomic-write contract, hardlink behavior) use synthetic substrate. Tests verifying END-TO-END properties (regex matching real CDP outputs, real PVOC determinism, security boundary against real path traversal) need real CDP. The Phase 1b Task 13 plan-vs-implementation divergence (substituted `fake_subprocess` for real PVOC in the keepalive stress test) is the clearest case: the test verifies the clock loop fires across 60 seconds, which is a mechanism property, so synthetic substrate is *purer* than real CDP with variable timing.

## 2. Test fakes should fail in the same ways production fails (5.4.1)

Phase 1a's `fake_subprocess.py` initially overwrote outputs unconditionally; production was broken on the same path (`pvoc synth` refuses-clobber). Phase 1b Task 2 added `--cdp-refuse-clobber` etc. Naming convention: `--cdp-<simulated-behavior>` — the flag names an observable behavior, not an implementation detail.

Corollary from forensics 5.2.1: fakes simulating crashes use **SIGTERM**, never SIGILL/SIGABRT/SIGSEGV — macOS ReportCrash pops a dialog for the latter on every test run, and production only checks `exit_code != 0` anyway.

## 3. The fixture inventory (Phase 1b baseline)

- **`tests/fixtures/fake_subprocess.py`** — the workhorse. Executable Python script that simulates CDP behavior: writes wav/ana files, emits stderr lines, sleeps, exits cleanly or fails specific ways. Flags: `--cdp-refuse-clobber`, `--cdp-die-on-dot-path`, `--cdp-silent-output`, `--cdp-grow-file`, `--sleep`, `--stderr-lines`, `--write-wav`, `--write-ana`.
- **`tests/conftest.py`** — two session-scoped autouse fixtures: `_isolated_sessions_root` (redirects `CDP_MCP_SESSIONS_ROOT` to `tmp_path` so test runs never touch the developer's real session dir) and `_disable_apple_silicon_arch_wrapping` (the venv Python that exec-runs `fake_subprocess.py` isn't a fat binary; wrapping it with `arch -x86_64` fails with "Bad CPU type in executable"). Tests exercising the arch-detection logic itself use `monkeypatch.delenv` for their scope.
- **Acceptance test** (`tests/test_acceptance.py`) — the full frog chain end-to-end against real CDP under the deliberately-dotted session name `frog_acceptance_v1.0` (locks in the brassage path-mangling regression, forensics 5.1.6).
- **Stress test** (`tests/test_stress.py`, `@pytest.mark.slow`) — opt-in (`pytest -m slow`): 80 s subprocess sleep, ≥ 5 progress calls, duration in `[60s, 180s]`. Lower bound proves the test exercised the keepalive; upper bound catches silent latency regression.

## 4. Direct proof over timing (5.4.3)

`monkeypatch.setattr` on `run_cdp_command` directly is the right way to prove "subprocess didn't run." Timing-based "second call was faster" leaves room for filesystem cache, GC, etc. Patching the entry point and asserting it wasn't entered is direct empirical proof. Used for the cross-tool audition-cache verification ("analyze hits viz-populated audition cache without subprocess").

## 5. Phantom session in cache dir (5.4.2)

`list_sessions()` returns every subdir of `sessions_root`. If tests put a cache directory under a `tmp_path` that doubles as a sessions_root, the cache appears as a "session." Fix: `tmp_path_factory.mktemp("cache")` outside the sessions root, or a separate `tmp_path / "cache"` dir. Pattern documented in `tests/test_workspace.py`.

## 6. pytest-timeout as belt-and-suspenders (5.4.4)

Global `timeout = 30` in `pyproject.toml` catches async-coordination bugs that would otherwise hang. Long tests override per-test (`@pytest.mark.timeout(200)` on the stress test).

---

## Phase 2/3 additions

### 7. Don't keep standing tests that guard deferred features

The Phase 2 determinism sweep guarded only the Phase 4 Task 12 process-output cache — deferred *and* conditional — while flaking ~1-in-3 under full-suite load (root cause: CDP's tick-counter metadata, forensics P2-1). It was investigated, tolerated, then deliberately **removed** (Task 6.7), with the durable finding recast into `docs/phase-2-determinism.md` and the reactivation obligation pinned on Phase 4. Two patterns from it are worth resurrecting if a sweep returns: `frozenset[str]` per-entry expectations (either legitimate outcome passes, anything else fails loudly) and an env-guarded byte-level diagnostic dump (`CDP_MCP_DETERMINISM_DIAGNOSTICS=1`). The decision+rationale+reactivation-condition write-up is itself the model for removing any test.

### 8. Real-CDP gating and the Linux build substrate

CDP-dependent tests skip when `CDP_PATH` is unset and become real when it's set — no fakes pretending to be curation evidence. Since Phase 3, `scripts/build_cdp8_linux.sh` builds ~211 real binaries from source in any Linux sandbox/CI, so the *full* suite runs with zero gated skips without a macOS machine in the loop. Division of authority is explicit: **the sandbox build is the exploration substrate; the user's macOS r8 install is the source of truth** — every sandbox-derived finding re-verifies on macOS via the same gated tests. First cross-check (the filter-sweeping tail default) reproduced exactly across both.

### 9. Pinned regression tables are the curation contract

Every empirically-probed curation outcome lands in a shared, executable table: duration formulas in `tests/test_curation_formulas.py` (predicted vs measured, per-row `rel_tol`), breakpoint capability in `tests/test_breakpoint_curation.py` (probe outcomes per parameter). A curated claim that isn't a pinned row is an opinion. The tables are what make "re-verify on macOS" a command instead of a project.

### 10. Execute the table you extend (the 2026-07-14 `.ana` lesson)

When tranches 1–3 added spectral rows to the pinned duration table, the *rows* were correct (their agents measured via pvoc-synth round-trips) but the *shared harness* still measured with `sf.info()` — which cannot open `.ana` files — and nobody had run the extended table end-to-end against real CDP until the macOS QA pass failed all 16 spectral rows at once (commit `e97319d`). The principle: **integration code extending a pinned table must EXECUTE the table, not just collect it.** "It parses and collects" verifies the data shape; only execution verifies the harness's assumptions still hold for the new row class. The in-sandbox build (item 8) makes this cheap — there is no longer an excuse for merging gated rows unexecuted.

### 11. Probe hygiene (curation methodology)

Locked in across tranches 2–3 after each rule was violated once and cost a re-run:

- **Fresh output names per probe.** CDP refuses to overwrite existing outputs with exit 255; a reused name from a failed batch masquerades as a refusal of the thing you're probing (forensics P3-13).
- **≥ 1.1 s between unseeded paired runs.** CDP's clock seeding makes same-second reruns of stochastic programs spuriously identical (forensics P3-3).
- **Compare decoded samples, never raw bytes.** CDP embeds tick timestamps in output headers (forensics P2-1); determinism claims hash `soundfile`-decoded data, and `.ana` outputs are compared via synth round-trips.
- **Check for non-silence, not just exit 0.** Several programs emit structurally valid, silent or zero-frame output at exit 0 (forensics P3-8, P3-9, P3-10, P3-11).

### 12. Test doubles vs the process-group kill

`_kill_process_tree` (Phase 2 C1 hardening) validates `type(pid) is int and pid > 1` before `os.killpg` — partly because `killpg(0)` would kill the test runner's own process group, and partly so MagicMock procs (whose `pid` is not an int) fall through safely to `proc.kill()` (forensics P2-2). When hardening subprocess paths, check what your fakes present to the new code *before* the suite finds out for you.
