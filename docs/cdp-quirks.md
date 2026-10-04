# CDP quirks

These are behaviors of the CDP binaries that differ from what their manual or usage banners say, or that would trip up anyone driving CDP from code. They were measured on CDP8 built from source by `scripts/build_cdp8_linux.sh` (Linux x86_64; the banners report "CDP Release 7.1 2016") and checked against the macOS r8 release. The knowledge entries record the program-specific details in their known issues.

## Running CDP

- **Errors often go to stdout.** Many error messages are printed to stdout, not stderr. Exit codes are unreliable too: a program that prints its usage banner may exit 0, 1, 2 or 255. The dependable signal is a missing output file together with `Usage:` in either stream.
- **Existing files are never overwritten.** Writing to an existing output path fails with exit 255 and `Cannot open output file`.
- **`modify brassage` crashes (SIGILL, no message) on absolute paths with a `.` in any directory name**, such as a session called `v1.0`, because it derives a temporary file name from the path. Pass paths relative to the working directory.
- **Kill the whole process group on timeout.** Some programs fork children that hold the output pipes open, so killing only the parent leaves the pipe readers waiting forever. Guard the call: `killpg(0)` kills your own process group.
- **Stereo can't be analyzed.** `pvoc anal` refuses stereo input (exit 255), so every spectral program works on mono only.
- **`.ana` files are 10–20 times the size of the source wav,** and libsndfile cannot read them. `sfprops -d file.ana` prints the duration.
- **Stock CDP r8 has no `cdp` binary to ask for a version.** The server infers it from the install path, such as `cdpr8`.
- **On aarch64 Linux every text input fails** with `... is not a valid CDP file`. `char` is unsigned there, and CDP's text readers compare `(char)fgetc()` with `EOF`, so the comparison never matches. Build with `-fsigned-char`, injected into each per-directory `CMakeLists.txt` because they overwrite `CMAKE_C_FLAGS`. The build script does this.

## Determinism and seeds

- **Outputs are deterministic in their samples but not their bytes.** Each output file carries a timestamp: in the wav PEAK chunk and a `DATE` field, and at byte 179 of `.ana` files. Compare decoded samples, never raw files. `pvoc anal` and `pvoc synth` are otherwise deterministic.
- **Unseeded random programs seed from the clock in whole seconds.** Two runs started within the same second produce identical output, while runs a second apart differ. Leave more than a second between runs when testing whether a program is random.
- **Seed options vary.** `blur drunk` is random with no seed option. `blur scatter` sounds random but is fully deterministic. `modify revecho`'s seed flag does nothing outside Windows, because CDP replaces libc's `drand48()` with its own and passes the seed to it only on Windows. `texture simple`'s `-r` seed works.

## Documentation errors

- **Banners can state wrong formulas.** `filter sweeping`'s banner gives the `sweepfrq` limit as `infiledur/2`; the real limit is `1/(2·infiledur)`.
- **`filter sweeping` and `filter lohi` have a `-t` tail flag that the manual omits.** Leaving it out appends exactly one second to the output.
- **Breakpoint support goes unmentioned.** `distort multiply`, `distort average` and `distort divide` accept breakpoint files where their banners don't say so. `distort interpolate`'s banner mentions a `cyclecnt` parameter the program doesn't have.
- **An advertised range can hang.** `newdelay` lists feedback from -1 to 1, but at ±1 it never finishes. At ±0.99 it completes in under a second.

## Silent failures

In these cases CDP exits 0, or crashes after doing its work, so the exit code doesn't say whether the run succeeded:

- **Zero-length or silent output:**
  - `spec magnify` writes an empty file when `dur` is no longer than the analysis window.
  - `focus fold` silently swaps reversed frequency bounds, and equal bounds produce silence. `sfedit cut` likewise accepts reversed start and end times.
  - `extend doublets` drops the final segment. With `segdur` equal to the input's duration, it writes a zero-length file.
  - `quirk` writes a zero-length file when given one-sided material with no zero crossings.
- **Exit codes and warnings:** `specfnu` mode 19 aborts with `double free or corruption` after writing a valid output. Every `specfnu` run also prints `WARNING: failed to write PEAK data`, which is harmless.
- **`submix mix` wraps around on overload instead of clipping,** and gives no warning. Run `submix getlevel 1 <mixfile>` first and pass the factor it reports as `-g`. The `-a` flag has no effect.
- **`filter bank` corrupts its heap and can hang** on binaries built before CDP8 commit `11cdcb4` (June 2025), including the macOS r8 release. Rebuild `filter` from current source.

## Material sensitivity

- **The `grain` programs treat any dip below the gate threshold as silence.** A slowly drifting noise bed is cut into pseudo-grains and loses its quiet parts: one 3.0 s input came out at 2.3 s.
- **`envspeak` refuses only envelopes with no dips at all.** A sustained tone with a soft attack and release counts as a single syllable.

## MCP hosts

- **Claude Desktop rejects tool results larger than about 1 MB.** Composite images are therefore downscaled to fit, and the full-size file is reported by path.
- **Force matplotlib's `Agg` backend in code, before pyplot is imported.** MCP launchers don't reliably pass `MPLBACKEND` through, and a GUI backend hangs a headless server.
