# texture simple mode 5 — re-curation probe transcript (Phase 3 close-out)

Re-curates the entry dropped in tranche 3 (`tranche3_timedomain.md` §6,
`tranche3_timedomain_findings.json` dropped[0], reason `schema_gap_aux_file`),
now that the engine has the `aux_file` ParameterSpec type the drop record
recommended. Every tranche-3 claim was re-verified from scratch against the
real binary, and the probe surface was widened to *all* numeric parameters
(the tranche did spot probes only) plus the option flags.

## Environment

- **Binaries:** `/tmp/CDP8/NewRelease` (ComposersDesktop/CDP8 source build; `texture`
  self-reports "CDP Release 7.1 2016"), Linux x86_64 sandbox.
- **Inputs:** written fresh in `/tmp/texprobe` — `n2.wav` mono 44100 Hz float32
  enveloped noise 2.0 s (`np.random.default_rng(0)`, ±0.2); `st2.wav` the same signal
  duplicated to stereo; `nd.txt` containing the single line `60`.
- **Methodology:** replicates the tranche transcripts. Breakpoint probes substitute a
  2-line file `0 <lo>\n5 <hi>` at the parameter's argv slot (or attach `-X<file>` for
  flags). Determinism compares sha256 of **decoded samples** (soundfile, float64);
  unseeded pairs launched > 1.1 s apart. Fresh output name per run (CDP
  refuses to clobber).
- **Engine side:** re-verified end-to-end through `process_impl` by the CDP-gated tests
  in `tests/test_aux_file.py` (aux resolution, stereo output, honest duration bounds,
  fixed-seed determinism, packing breakpoint, outdur breakpoint refusal).

Refusal errors quoted below are verbatim (stdout, exit 255).

## Usage banner (mode 5 pinned)

```
texture simple mode infile [infile2...] outfile notedata outdur packing scatter
   tgrid sndfirst sndlast  mingain maxgain  mindur maxdur  minpich maxpich omit
             [-aatten] [-pposition] [-sspread] [-rseed] [-w -c -p]
```

Working argv (re-confirmed): `texture simple 5 n2.wav out.wav nd.txt 5 0.25 0.3 0 1 1
64 64 0.2 0.5 60 60 0 -r5` — exit 0. `nd.txt` = `60` (mode 5 "NONE" needs only the
assumed MIDI pitch of each input sound; fractional pitch `60.3` also accepted, exit 0).
A notedata path with a directory component (`sub/nd.txt`) works — the engine's
cwd-relative `data/nd.txt` rendering is safe.

## 1. Stochasticity + seed (re-verified)

| run | decoded sha (16) | frames | outdur actual |
| --- | ---------------- | ------ | ------------- |
| `-r5` (t) | `33dc8c6cd3de32ae` | 217768 | 4.9380 |
| `-r5` (t + 1.1 s) | `33dc8c6cd3de32ae` | 217768 | 4.9380 |
| `-r9` | `69637362ca1c9596` | 225681 | 5.1175 |
| unseeded (t) | `e641d171a28c5625` | 225275 | 5.1083 |
| unseeded (t + 1.1 s) | `1ab315a03f139a8e` | 221850 | 5.0306 |

GENUINELY STOCHASTIC with a WORKING `-r` seed: same seed byte-identical 1.1 s apart;
different seeds differ; unseeded differs run-to-run in both samples *and frame count*.
Seed range is CDP-enforced **0 to 32767** (`-r-1` → `Parameter[18] Value (-1.000000)
out of range (0.000000 to 32767.000000)`; `-r11` exit 0 — afta8's max 10 is a UI cap).
`-r5.5` is accepted (exit 0). Seed brk file refused: `ERROR: Cannot read parameter 30
[b_at.brk]: brkpnt_files not permitted.`

## 2. Duration model (set_by outdur, honest bounds re-measured)

All runs seeded `-r5` unless marked (u). Base params packing 0.25 scatter 0.3
mindur 0.2, pitch 60/60, omit 0.

| outdur | maxdur | actual | rel err |
| ------ | ------ | ------ | ------- |
| 3 | 0.5 | 2.9783 | −0.72% |
| 5 | 0.5 | 4.9380 | −1.24% |
| 8 | 0.5 | 7.9795 | −0.26% |
| 8 (u) | 0.5 | 8.0979 | +1.22% |
| 5 | 1.5 | 5.5780 | +11.56% |
| 5 (u) | 1.5 | 5.5407 | +10.81% |
| 5 | 2.0 | 5.9235 | +18.47% |
| 5 | 2.5 | 6.2690 | +25.38% |
| 5 (packing 0.1, scatter 2.0) | 0.5 | 5.2876 | +5.75% |

Combined with the tranche-3 table (−0.7%…+16.7%): **actual lands between ≈1.3% below
outdur and ≈ outdur + maxdur** — the overshoot is the final event's tail and grows with
maxdur; the undershoot contradicts the banner's "(min) duration of outfile" claim
(re-confirmed: 7.98 from outdur 8). Curated `set_by outdur` with these bounds in
`known_issues`; keep maxdur ≪ outdur when length matters. Suggested pinned duration row
uses maxdur 0.5 + seed with rel_tol 0.15 (bound ≈ maxdur/outdur = 10% + undershoot).

## 3. Channels (re-verified)

Every successful run above: mono input → **2-channel output** (events placed in a
stereo image via -p/-s). Stereo input refused: `Application doesn't work with this type
of infile.` → `channel_constraint: "mono"` (input side), output always stereo .wav.

## 4. Breakpoint probes — ALL params (manual claim: all but notedata/outdur/seed vary)

Positional slots probed with a 2-point brk at the slot, `-r5`, fresh outputs:

| param | brk probe | verdict |
| ----- | --------- | ------- |
| outdur | `ERROR: Cannot read parameter 1 [b_od.brk]: brkpnt_files not permitted.` | **false** |
| packing | exit 0; differs from BOTH scalar-endpoint renders at same seed (0.1 → `c7367fdb91e1`/5.385 s, 0.5 → `ef8701f00f82`/4.630 s, brk → `f005178fb8ce`/4.768 s) | **true (verified varying)** |
| scatter | exit 0 | true |
| tgrid | exit 0 | true |
| sndfirst | exit 0 (constant-1 brk; range is 1..#snds) | true |
| sndlast | exit 0 | true |
| mingain | exit 0 | true |
| maxgain | exit 0 | true |
| mindur | exit 0 | true |
| maxdur | exit 0 | true |
| minpich | exit 0 | true |
| maxpich | exit 0 | true |
| omit | exit 0 | true |
| atten (-a) | `-ab_at.brk` exit 0 (flag order caveat, §5) | true |
| position (-p) | `-pb_po.brk` exit 0 | true |
| spread (-s) | `-sb_sp.brk` exit 0 (flag order caveat) | true |
| seed (-r) | refused (`parameter 30 ... brkpnt_files not permitted`) | **false** |

## 5. Flag ORDER trap (new finding, first-class)

CDP enforces the banner's flag order **-a -p -s -r -w** after the positionals:

- `... 0 -r5 -a0.5` → `ERROR: option flag -a out of order on cmdline.` (exit 255)
- `... 0 -a0.5 -r5`, `... -s0.5 -r5`, and full `-a0.5 -p0.5 -s0.5 -r5 -w` → exit 0.
- Flags before the positionals also fail (`-a0.5` in the notedata slot →
  `Can't open file -a0.5 to read data.`).

The engine emits parameters in entry declaration order, so the curated entry declares
atten, position, spread, seed, whole in banner order. (The tranche-3 spot probes never
hit this because they only ever passed `-r`.)

## 6. Scalar ranges (CDP-enforced, verbatim)

| param | probe | refusal |
| ----- | ----- | ------- |
| outdur | 0 | `Parameter[2] Value (0.000000) out of range (0.010000 to 32767.000000)` |
| packing | 0 / 61 | `Parameter[3] ... out of range (0.000023 to 60.000000)` |
| scatter | 11 | `Parameter[4] ... out of range (0.000000 to 10.000000)` |
| tgrid | 10001 | `Parameter[5] ... out of range (0.000000 to 10000.000000)` |
| sndfirst | 2 (1 input) | `FIRST SND-IN-LIST TO USE > count of files entered: cannot proceed.` |
| mingain | 0 | `Parameter[8] ... out of range (1.000000 to 127.000000)` |
| maxgain | 128 | `Parameter[9] ... out of range (1.000000 to 127.000000)` |
| mindur | 0.001 | `Parameter[10] ... out of range (0.016000 to 32767.000000)` |
| maxdur | 61 | fails obscurely: `ERROR: INVALID DATA / ERROR: Cannot open output file ...` (2.5 on the 2 s input is fine, exit 0, 6.269 s) |
| minpich | −1 | `Parameter[12] ... out of range (1.000000 to 127.000000)` |
| maxpich | 128 | `Parameter[13] ... out of range (1.000000 to 127.000000)` |
| omit | 65 | `Parameter[14] ... out of range (0.000000 to 64.000000)` |
| atten | 100 / 101 | `Parameter[15] ... out of range (0.000002 to 1.000000)` — **afta8's 0–100 is wrong; it's a ≤1 multiplier** |
| position | 2 | **accepted, exit 0** — NOT range-enforced (the -p slot doubles as the bare permute switch); curated 0–1 is engine-enforced |
| spread | 2 | `Parameter[17] ... out of range (0.000000 to 1.000000)` |
| seed | −1 | `Parameter[18] ... out of range (0.000000 to 32767.000000)` |

Fractional pitch bounds fine: `minpich 59.5 maxpich 60.5` exit 0.

## 7. -w whole switch

`-w` exit 0; output differs from the base run and extends the tail (6.7188 s from
outdur 5 with other flags set, +36% — each event plays the whole 2 s source). Exposed
as a `bool` `no_value` param, `default: false` (correct semantics after the Phase 3
falsy-switch fix). `-c` (cyclic file choice) and the bare `-p` permute switch are
multi-input machinery and are left to `execute()`.

## 8. notedata error surface

- Non-numeric content (`abc`): `ERROR: INVALID DATA / ERROR: Insufficient pitch values
  in notedata file.`
- A pitch line plus extra rows without a `#N` count header: `ERROR: '#' missing before
  datacount in notedata file: motif 1 (or more notes listed than indicated by #N)`.

## Verdict — SHIPPED

`src/cdp_mcp/knowledge/data/texture_simple.json`: submode 5 pinned, `notedata` as the
first `aux_file` parameter in the index, `set_by outdur` with honest bounds,
`phase_sensitive: true`, `channel_constraint: "mono"` with the stereo-output divergence
documented in `known_issues`, working `-r` seed, all 15 breakpoint-capable params
marked from the table above. Findings record: `docs/curation/texture_findings.json`.
