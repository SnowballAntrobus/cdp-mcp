"""Phase 2 Task 5 — `breakpoint_capable` curation review tests.

Locks in the empirical verdict from the Task 5 probe pass: which curated
parameters CDP r8 actually accepts breakpoint envelopes for, and which
reject them with ``brkpnt_files not permitted``.

Two tiers of coverage:

1. **Knowledge-index integrity.** The expectation table below mirrors the
   forensic findings in ``docs/phase-2-breakpoint-review.md``. Any drift
   between the JSON and the empirical record trips a test failure here.
   This makes accidental flips visible to the test suite long before they
   reach a real-CDP session.

2. **Compiler behavior** for each newly-flipped parameter — a 2-point
   envelope compiles successfully (positive case). Stay-False parameters
   are not asserted at the unit-compiler level (the
   ``param_breakpoint_not_capable`` rejection is enforced one layer up in
   ``validate_node``; covering all 16 negatives at the JSON-integrity
   level keeps the matrix tight without duplicating compiler tests).
"""

from __future__ import annotations

import pytest

from cdp_mcp.breakpoint_compiler import compile_breakpoint_value
from cdp_mcp.knowledge.loader import KnowledgeIndex

# Empirical findings from the Task 5 probe pass (run against CDP r8 in
# cdpr8/_cdp/_cdprogs). Updating any cell in this table is a curation
# decision and must pair with an entry in docs/phase-2-breakpoint-review.md.
_EXPECTED_BREAKPOINT_CAPABLE: dict[tuple[str, str, int | None], dict[str, bool]] = {
    # --- Wave 6 (tranches 22-23: pitch-data + text utilities; see
    # docs/curation/tranche22_pitchdata_findings.json +
    # tranche23_datautil_findings.json) ---
    ("repitch", "getpitch", 1): {
        "pitchdata": False,
        "tuning_range": False,
        "min_group": False,
        "signal_noise_ratio": False,
        "min_harmonics": False,
        "lopitch": False,
        "hipitch": False,
        "alt_algorithm": False,
        "retain_unpitched": False,
    },
    ("repitch", "getpitch", 2): {
        "pitchdata": False,
        "tuning_range": False,
        "min_group": False,
        "signal_noise_ratio": False,
        "min_harmonics": False,
        "lopitch": False,
        "hipitch": False,
        "data_reduce": False,
        "alt_algorithm": False,
    },
    ("repitch", "combineb", 1): {
        "pitchfile": False,
        "pitchfile2": False,
        "data_reduce": False,
    },
    ("repitch", "transposef", 3): {
        "formant_bands": False,
        "quicksearch": False,
        "transpos": True,
        "minfrq": False,
        "maxfrq": False,
        "fullspec": False,
    },
    ("repitch", "transposef", 4): {
        "transposition": False,
        "formant_bands": False,
        "quicksearch": False,
        "minfrq": False,
        "maxfrq": False,
        "fullspec": False,
    },
    ("repitch", "synth", None): {
        "pitchfile": False,
        "harmonics": False,
    },
    ("repitch", "vowels", None): {
        "pitchfile": False,
        "vowel_data": False,
        "halfwidth": False,
        "curve": False,
        "pk_range": False,
        "fweight": False,
        "foffset": False,
    },
    ("repitch", "analenv", None): {
        # no numeric parameters
    },
    ("ptobrk", "withzeros", None): {
        "pitchfile": False,
        "min_pitch_dur": False,
    },
    ("pitch", "transp", 6): {
        "frq_split": True,
        "transpos1": True,
        "transpos2": True,
        "depth": True,
    },
    ("pitch", "pick", 1): {
        "fundamental": False,
        "clarity": True,
    },
    ("matrix", "matrix", 3): {
        "analchans": False,
        "winoverlap": False,
    },
    ("matrix", "matrix", 4): {
        "analchans": False,
        "winoverlap": False,
    },
    ("matrix", "matrix", 2): {
        "inmatrixfile": False,
        "cyclic": False,
    },
    ("hfperm", "hfchords", 1): {
        "notes": False,
        "srate": False,
        "notedur": False,
        "gapdur": False,
        "pausedur": False,
        "minset": False,
        "bottomnote": False,
        "bottomoctave": False,
        "topnote": False,
        "topoctave": False,
        "sortby": False,
        "minonly": False,
        "smallfirst": False,
        "altsort": False,
        "elimoctdups": False,
    },
    ("hfperm", "hfchords", 4): {
        "notes": False,
        "minset": False,
        "bottomnote": False,
        "bottomoctave": False,
        "topnote": False,
        "topoctave": False,
        "sortby": False,
        "minonly": False,
        "smallfirst": False,
        "altsort": False,
        "elimoctdups": False,
    },
    # --- Phase 6 schema unblocks (free_string + .frq/.trn kinds; entries
    # authored from the tranche-10a/16/22 pinned empirics, re-verified
    # against the binaries — see tests/test_free_string.py) ---
    ("blur", "shuffle", None): {
        "domain_image": False,
        "grpsize": False,
    },
    ("distort", "shuffle", None): {
        "domain_image": False,
        "cyclecnt": True,
        "skipcycles": False,
    },
    ("repitch", "approx", 1): {
        "pitchfile": False,
        "prange": True,
        "trange": False,
        "srange": False,
    },
    ("repitch", "exag", 6): {
        "pitchfile": False,
        "meanpch": True,
        "range": True,
        "contour": True,
    },
    ("repitch", "invert", 2): {
        "pitchfile": False,
        "map": False,
        "meanpch": True,
        "bot": False,
        "top": False,
    },
    ("repitch", "pchshift", None): {
        "pitchfile": False,
        "transposition": False,
    },
    ("repitch", "quantise", 2): {
        "pitchfile": False,
        "qset": False,
        "all_octaves": False,
    },
    ("repitch", "randomise", 2): {
        "pitchfile": False,
        "maxinterval": True,
        "timestep": False,
        "slew": False,
    },
    ("repitch", "smooth", 1): {
        "pitchfile": False,
        "timeframe": False,
        "peak_from": False,
        "hold_last": False,
    },
    ("repitch", "vibrato", 2): {
        "pitchfile": False,
        "vibfreq": True,
        "vibrange": True,
    },
    # --- Wave 5 (tranches 20-21: spectral tail; see
    # docs/curation/tranche20_spectral1_findings.json +
    # tranche21_spectral2_findings.json) ---
    ("blur", "weave", None): {
        "weavfile": False,
    },
    ("combine", "sum", None): {
        "crossover": True,
    },
    ("combine", "mean", 1): {
        "lofrq": False,
        "hifrq": False,
        "chans": False,
        "zero_outside": False,
    },
    ("combine", "mean", 3): {
        "lofrq": False,
        "hifrq": False,
        "chans": False,
        "zero_outside": False,
    },
    ("focus", "freeze", 3): {
        "freezedata": False,
    },
    ("focus", "hold", None): {
        "holddata": False,
    },
    ("spec", "gate", None): {
        "threshold": True,
    },
    ("spec", "bare", None): {
        "pitchfile": False,
        "less_body": False,
    },
    ("spec", "clean", 2): {
        "skiptime": False,
        "noisgain": False,
    },
    ("hilite", "filter", 7): {
        "frq1": True,
        "frq2": True,
        "q": True,
    },
    ("hilite", "greq", 1): {
        "filtfile": False,
        "band_reject": False,
    },
    ("hilite", "band", None): {
        "banddata": False,
    },
    ("hilite", "pluck", None): {
        "gain": True,
    },
    ("hilite", "bltr", None): {
        "blurring": True,
        "tracing": True,
    },
    ("hilite", "vowels", None): {
        "vowelfile": False,
        "halfwidth": False,
        "steepness": False,
        "range": False,
        "threshold": False,
    },
    ("specfold", "specfold", 3): {
        "stt": False,
        "len": False,
        "seed": False,
        "amps_only": False,
    },
    ("specav", "specav", 1): {
        "starttime": False,
        "endtime": False,
        "normalise": False,
    },
    ("specenv", "specenv", None): {
        "windowsize": False,
        "bal": False,
        "pitchwise": False,
        "impose": False,
        "keep_loudness": False,
    },
    ("specnu", "remove", 1): {
        "midimin": False,
        "midimax": False,
        "rangetop": False,
        "atten": False,
    },
    ("specnu", "subtract", None): {
        "persist": False,
        "noisgain": False,
    },
    ("specnu", "rand", None): {
        "timescale": True,
        "grouping": False,
    },
    ("specnu", "squeeze", None): {
        "centrefrq": True,
        "squeeze": True,
    },
    ("suppress", "partials", None): {
        "timeslots": False,
        "lofrq": False,
        "hifrq": False,
        "chancnt": False,
    },
    ("subtract", "subtract", None): {
        "chan": False,
    },
    ("caltrain", "caltrain", None): {
        "blurfact": False,
        "blurabov": False,
        "locut": False,
    },
    ("glisten", "glisten", None): {
        "grpdiv": True,
        "setdur": True,
        "pitchshift": False,
        "durrand": False,
        "divrand": False,
    },
    ("specross", "partials", None): {
        "tuning": False,
        "minwin": False,
        "signois": False,
        "harmcnt": False,
        "lo": False,
        "hi": False,
        "thresh": False,
        "level": False,
        "interp": True,
    },
    ("newmorph", "newmorph", 1): {
        "stagger": False,
        "startmorph": False,
        "endmorph": False,
        "exponent": False,
        "peaks": False,
        "retain_env": False,
        "peaks_only": False,
        "frq_only": False,
    },
    ("newmorph", "newmorph2", 1): {
        "peakcnt": False,
    },
    ("newmorph", "newmorph2", 2): {
        "peaksfile": False,
        "startmorph": False,
        "endmorph": False,
        "exponent": False,
        "peakcnt": False,
        "rand": False,
    },
    ("spectwin", "spectwin", 4): {
        "frqint": False,
        "envint": False,
        "dupl": False,
        "step": False,
        "dec": False,
    },
    ("selfsim", "selfsim", None): {
        "selfsim": False,
    },
    ("superaccu", "superaccu", 1): {
        "decay": True,
        "glis": True,
        "reassign": False,
    },
    ("spectune", "tune", 1): {
        "match": False,
        "lop": False,
        "hip": False,
        "stim": False,
        "etim": False,
        "intune": False,
        "wins": False,
        "nois": False,
        "loudness_blind": False,
        "smooth_first": False,
        "ignore_formants": False,
    },
    ("tunevary", "tunevary", None): {
        "pitch_template": False,
        "focus": False,
        "clarity": False,
        "trace": False,
        "bcut": False,
    },
    ("peak", "extract", 4): {
        "winsiz": False,
        "peak": False,
        "floor": False,
        "lo": False,
        "hi": False,
        "tune": False,
        "lose_amps": False,
        "as_midi": False,
        "quantise": False,
        "varibank": False,
    },
    ("get_partials", "harmonic", 3): {
        "fundamental": False,
        "threshold": False,
        "time": False,
        "varibank2": False,
    },
    ("specanal", "specanal", 1): {
        "chs": False,
        "ovlp": False,
    },
    ("oneform", "get", None): {
        "formantfile": False,
        "time": False,
    },
    ("oneform", "put", 2): {
        "onefile": False,
        "lolim": False,
        "hilim": False,
        "gain": False,
    },
    ("fturanal", "anal", 1): {
        "marklist": False,
        "rand": False,
    },
    ("fturanal", "synth", 1): {
        "featurefile": False,
        "splicelen": False,
    },
    # --- Wave 4 (tranches 18-19: texture/filter depth + grain/FOF; see
    # docs/curation/tranche18_texture_filter_findings.json +
    # tranche19_grain_fof_findings.json) ---
    ("filter", "iterated", 1): {
        "fbank": False,
        "q": False,
        "gain": False,
        "delay": False,
        "dur": False,
        "prescale": False,
        "rand": False,
        "pshift": True,
        "ashift": True,
        "double": False,
        "interp_off": False,
        "expdecay": False,
        "nonorm": False,
    },
    ("filter", "userbank", 1): {
        "fbank": False,
        "q": True,
        "gain": False,
        "tail": False,
        "double": False,
    },
    ("filter", "varibank", 1): {
        "fdata": False,
        "q": True,
        "gain": False,
        "tail": False,
        "hcnt": False,
        "rolloff": False,
        "double": False,
        "overflow_dropout": False,
        "normalize": False,
    },
    ("filter", "varibank2", 1): {
        "fdata": False,
        "q": True,
        "gain": False,
        "tail": False,
        "double": False,
        "normalize": False,
    },
    ("filter", "fixed", 3): {
        "bwidth": False,
        "boost_cut": False,
        "freq": False,
        "tail": False,
        "prescale": False,
    },
    ("filter", "variable", 1): {
        "acuity": True,
        "gain": False,
        "frq": True,
        "tail": False,
    },
    ("filter", "phasing", 2): {
        "gain": False,
        "delay": True,
        "tail": False,
        "prescale": False,
        "linear": False,
    },
    ("filter", "bankfrqs", 1): {
        "lof": False,
        "hif": False,
    },
    ("texture", "ornate", 5): {
        "notedata": False,
        "outdur": False,
        "skiptime": True,
        "sndfirst": True,
        "sndlast": True,
        "mingain": True,
        "maxgain": True,
        "mindur": True,
        "maxdur": True,
        "phgrid": True,
        "gpspace": False,
        "gpsprange": True,
        "amprise": True,
        "contour": False,
        "multlo": True,
        "multhi": True,
        "atten": True,
        "position": True,
        "spread": True,
        "seed": False,
        "whole": False,
        "samedur": False,
        "instrvary": False,
        "orntop": False,
        "ornall": False,
    },
    ("texture", "preornate", 5): {
        "notedata": False,
        "outdur": False,
        "skiptime": True,
        "sndfirst": True,
        "sndlast": True,
        "mingain": True,
        "maxgain": True,
        "mindur": True,
        "maxdur": True,
        "phgrid": True,
        "gpspace": False,
        "gpsprange": True,
        "amprise": True,
        "contour": False,
        "multlo": True,
        "multhi": True,
        "atten": True,
        "position": True,
        "spread": True,
        "seed": False,
        "whole": False,
        "samedur": False,
        "instrvary": False,
        "orntop": False,
        "ornall": False,
    },
    ("texture", "postornate", 5): {
        "notedata": False,
        "outdur": False,
        "skiptime": True,
        "sndfirst": True,
        "sndlast": True,
        "mingain": True,
        "maxgain": True,
        "mindur": True,
        "maxdur": True,
        "phgrid": True,
        "gpspace": False,
        "gpsprange": True,
        "amprise": True,
        "contour": False,
        "multlo": True,
        "multhi": True,
        "atten": True,
        "position": True,
        "spread": True,
        "seed": False,
        "whole": False,
        "samedur": False,
        "instrvary": False,
        "orntop": False,
        "ornall": False,
    },
    ("texture", "motifs", 5): {
        "notedata": False,
        "outdur": False,
        "packing": True,
        "scatter": True,
        "tgrid": True,
        "sndfirst": True,
        "sndlast": True,
        "mingain": True,
        "maxgain": True,
        "minpich": True,
        "maxpich": True,
        "phgrid": True,
        "gpspace": False,
        "gpsprange": True,
        "amprise": True,
        "contour": False,
        "multlo": True,
        "multhi": True,
        "atten": True,
        "position": True,
        "spread": True,
        "seed": False,
        "whole": False,
        "samedur": False,
        "instrvary": False,
    },
    ("texture", "timed", 5): {
        "notedata": False,
        "outdur": False,
        "skiptime": True,
        "sndfirst": True,
        "sndlast": True,
        "mingain": True,
        "maxgain": True,
        "mindur": True,
        "maxdur": True,
        "minpich": True,
        "maxpich": True,
        "atten": True,
        "position": True,
        "spread": True,
        "seed": False,
        "whole": False,
    },
    ("texture", "tgrouped", 5): {
        "notedata": False,
        "outdur": False,
        "skip": True,
        "sndfirst": True,
        "sndlast": True,
        "mingain": True,
        "maxgain": True,
        "mindur": True,
        "maxdur": True,
        "minpitch": True,
        "maxpitch": True,
        "phgrid": True,
        "gpspace": False,
        "gpsprange": True,
        "amprise": True,
        "contour": False,
        "gpsizelo": True,
        "gpsizehi": True,
        "gppacklo": True,
        "gppackhi": True,
        "gpranglo": True,
        "gpranghi": True,
        "atten": True,
        "position": True,
        "spread": True,
        "seed": False,
        "whole": False,
        "fixstep": False,
        "instrvary": False,
    },
    ("texture", "tmotifs", 5): {
        "notedata": False,
        "outdur": False,
        "skip": True,
        "sndfirst": True,
        "sndlast": True,
        "mingain": True,
        "maxgain": True,
        "minpitch": True,
        "maxpitch": True,
        "phgrid": True,
        "gpspace": False,
        "gpsprange": True,
        "amprise": True,
        "contour": False,
        "multlo": True,
        "multhi": True,
        "atten": True,
        "position": True,
        "spread": True,
        "seed": False,
        "whole": False,
        "samedur": False,
        "instrvary": False,
    },
    ("texture", "predecor", 5): {
        "notedata": False,
        "outdur": False,
        "skiptime": True,
        "sndfirst": True,
        "sndlast": True,
        "mingain": True,
        "maxgain": True,
        "mindur": True,
        "maxdur": True,
        "phgrid": True,
        "gpspace": False,
        "gpsprange": True,
        "amprise": True,
        "contour": False,
        "gpsizlo": True,
        "gpsizhi": True,
        "gppaklo": True,
        "gppakhi": True,
        "gpranglo": True,
        "gpranghi": True,
        "centring": False,
        "atten": True,
        "position": True,
        "spread": True,
        "seed": False,
        "whole": False,
        "fixstep": False,
        "instrvary": False,
        "dectop": False,
        "decall": False,
        "discardline": False,
    },
    ("texture", "postdecor", 5): {
        "notedata": False,
        "outdur": False,
        "skiptime": True,
        "sndfirst": True,
        "sndlast": True,
        "mingain": True,
        "maxgain": True,
        "mindur": True,
        "maxdur": True,
        "phgrid": True,
        "gpspace": False,
        "gpsprange": True,
        "amprise": True,
        "contour": False,
        "gpsizlo": True,
        "gpsizhi": True,
        "gppaklo": True,
        "gppakhi": True,
        "gpranglo": True,
        "gpranghi": True,
        "centring": False,
        "atten": True,
        "position": True,
        "spread": True,
        "seed": False,
        "whole": False,
        "fixstep": False,
        "instrvary": False,
        "dectop": False,
        "decall": False,
        "discardline": False,
    },
    ("grain", "find", None): {
        "len": False,
        "gate": True,
        "minhole": False,
        "winsize": False,
        "ignore_last": False,
    },
    ("grain", "omit", None): {
        "keep": True,
        "out_of": False,
        "len": False,
        "gate": True,
        "minhole": False,
        "winsize": False,
        "ignore_last": False,
    },
    ("grain", "repitch", 1): {
        "transpfile": False,
        "len": False,
        "gate": True,
        "minhole": False,
        "winsize": False,
        "ignore_last": False,
    },
    ("grain", "reorder", None): {
        "code": False,
        "len": False,
        "gate": True,
        "minhole": False,
        "winsize": False,
        "ignore_last": False,
    },
    ("grain", "remotif", 1): {
        "transpmultfile": False,
        "len": False,
        "gate": True,
        "minhole": False,
        "winsize": False,
        "ignore_last": False,
    },
    ("grain", "align", None): {
        "offset": False,
        "gate2": True,
        "len": False,
        "gate": True,
        "minhole": False,
        "winsize": False,
        "ignore_last": False,
    },
    ("grain", "grev", 1): {
        "wsiz": False,
        "trof": False,
        "gpcnt": True,
    },
    ("grain", "grev", 5): {
        "wsiz": False,
        "trof": False,
        "gpcnt": False,
        "tstretch": True,
    },
    ("psow", "stretch", None): {
        "pitchdata": False,
        "timestretch": True,
        "segcnt": False,
    },
    ("psow", "dupl", None): {
        "pitchdata": False,
        "repeats": True,
        "segcnt": False,
    },
    ("psow", "delete", None): {
        "pitchdata": False,
        "propkeep": True,
        "segcnt": False,
    },
    ("psow", "strtrans", None): {
        "pitchdata": False,
        "timestretch": True,
        "segcnt": False,
        "trans": True,
    },
    ("fofex", "extract", 2): {
        "pitchdata": False,
        "time": False,
        "fofcnt": False,
        "windowed": False,
    },
    ("iterfof", "iterfof", 3): {
        "linedata": False,
        "outduration": False,
        "prand": False,
        "ampcut": False,
        "trimto": False,
        "trimby": False,
        "trimslope": False,
        "rand": False,
        "vibmin": False,
        "vibmax": False,
        "depmin": False,
        "depmax": False,
        "seed": False,
    },
    ("tweet", "tweet", 1): {
        "exclude": False,
        "pitchdata": False,
        "minlevel": False,
        "pkcnt": False,
        "chirp": False,
        "windowed": False,
    },
    # --- Wave 3 (tranches 16-17: waveset/distort + synthesis; see
    # docs/curation/tranche16_waveset_findings.json +
    # tranche17_synthesis_findings.json) ---
    ("distort", "replim", None): {
        "multiplier": True,
        "cyclecnt": True,
        "skipcycles": False,
        "hilim": False,
    },
    ("distort", "reverse", None): {
        "cyclecnt": True,
    },
    ("distort", "envel", 2): {
        "cyclecnt": True,
        "troughing": True,
        "exponent": True,
    },
    ("distort", "harmonic", None): {
        "harmonics_file": False,
        "pre_attenuation": False,
    },
    ("distort", "pitch", None): {
        "octvary": True,
        "cyclelen": True,
        "skipcycles": False,
    },
    ("distort", "telescope", None): {
        "cyclecnt": True,
        "skipcycles": False,
        "average": False,
    },
    ("distort", "filter", 1): {
        "freq": True,
        "skipcycles": False,
    },
    ("distort", "overload", 1): {
        "clip_level": False,
        "depth": True,
    },
    ("distort", "overload", 2): {
        "gate": False,
        "depth": True,
        "freq": True,
    },
    ("distort", "pulsed", 1): {
        "env": False,
        "stime": False,
        "dur": False,
        "frq": True,
        "frand": False,
        "trand": False,
        "arand": False,
        "transp": False,
        "tranrand": False,
        "keep_start": False,
        "keep_end": False,
    },
    ("distort", "repeat2", None): {
        "multiplier": True,
        "cyclecnt": True,
        "skipcycles": False,
    },
    ("distrep", "distrep", 1): {
        "multiplier": True,
        "cyclecnt": True,
        "skipcycles": False,
        "splicelen": False,
    },
    ("distshift", "distshift", 1): {
        "grpcnt": False,
        "shift": False,
    },
    ("distortt", "repeat", None): {
        "gpcnt": False,
        "rpt": False,
        "offset": False,
        "dur": False,
        "telescope": False,
    },
    ("distmark", "distmark", 1): {
        "marklist": False,
        "unitlen": True,
        "tstretch": False,
        "rand": False,
        "flip_phase": False,
        "keep_tail": False,
    },
    ("distmore", "double", None): {
        "mult": False,
    },
    ("distmore", "segszig", 2): {
        "repets": False,
        "shrinkto": False,
        "prop": False,
        "log_shrink": False,
    },
    ("distmore", "segsbkwd", 3): {
        "marklist": False,
    },
    ("splinter", "splinter", 2): {
        "target": False,
        "wcnt": False,
        "shrcnt": False,
        "ocnt": False,
        "p1": False,
        "p2": False,
        "ecnt": False,
        "scv": False,
        "pcv": False,
        "frq": False,
        "rand": True,
        "shrand": False,
        "mix_all": False,
        "mix_none": False,
    },
    ("crumble", "sound", 1): {
        "stt": False,
        "dur1": False,
        "dur2": False,
        "orient": False,
        "size": True,
        "rand": False,
        "iscat": False,
        "oscat": False,
        "ostrch": False,
        "pscat": True,
        "seed": False,
        "splice": False,
        "tail": False,
    },
    ("cascade", "cascade", 3): {
        "clipsize": False,
        "echos": False,
        "clipmax": False,
        "echosmax": False,
        "rand": False,
        "seed": False,
        "shredno": False,
        "shredcnt": False,
        "shred_original": False,
        "linear_decay": False,
        "normalise_low": False,
    },
    ("fracture", "fracture", 1): {
        "etab": False,
        "chns": False,
        "strms": False,
        "pulse": True,
        "edpth": False,
        "stkint": False,
        "seed": False,
        "min_frag": False,
        "max_frag": False,
        "rrnd": False,
        "prnd": False,
        "disp": False,
        "lrnd": False,
        "trnd": False,
    },
    ("synth", "spectra", None): {
        "dur": False,
        "frq": True,
        "spread": True,
        "maxfoc": True,
        "minfoc": True,
        "timevar": True,
        "srate": False,
        "spread_is_ratio": False,
    },
    ("synth", "chord", 1): {
        "datafile": False,
        "srate": False,
        "chans": False,
        "dur": False,
        "amp": False,
        "tabsize": False,
    },
    ("synth", "chord", 2): {
        "datafile": False,
        "srate": False,
        "chans": False,
        "dur": False,
        "amp": False,
        "tabsize": False,
    },
    ("synth", "clicks", 1): {
        "clickfile": False,
    },
    ("impulse", "impulse", None): {
        "dur": False,
        "pitch": True,
        "chirp": True,
        "slope": True,
        "pkcnt": True,
        "level": True,
        "gap": True,
        "srate": False,
    },
    ("motor", "motor", 1): {
        "dur": False,
        "freq": True,
        "pulse": False,
        "fratio": True,
        "pratio": True,
        "sym": False,
        "frand": True,
        "prand": False,
        "jitter": True,
        "tremor": False,
        "shift": False,
        "edge": False,
        "bite": False,
        "vary": False,
        "advance": False,
        "seed": False,
    },
    ("ceracu", "ceracu", None): {
        "cyclcnts": False,
        "mincycdur": False,
        "chans": False,
        "outdur": False,
        "echo": False,
        "echshift": False,
        "override": False,
        "linear": False,
    },
    ("newsynth", "synthesis", 1): {
        "spectrum": False,
        "srate": False,
        "dur": False,
        "frq": True,
    },
    ("newsynth", "synthesis", 5): {
        "srate": False,
        "dur": False,
        "frq": True,
        "damping": True,
        "k": False,
        "b": False,
    },
    ("pulser", "pulser", 1): {
        "dur": False,
        "pitch": True,
        "minrise": False,
        "maxrise": False,
        "minsus": False,
        "maxsus": False,
        "mindecay": False,
        "maxdecay": False,
        "speed": True,
        "scatter": False,
        "expr": False,
        "expd": False,
        "pscat": True,
        "ascat": False,
        "octav": False,
        "bend": False,
        "seed": False,
    },
    ("synfilt", "synfilt", 1): {
        "data": False,
        "srate": False,
        "chans": False,
        "q": True,
        "hcnt": False,
        "rolloff": False,
        "seed": False,
        "double_filter": False,
        "drop_on_overflow": False,
    },
    ("ts", "oscil", None): {
        "indata": False,
        "downsample": True,
        "maxdur": False,
        "force_loop": False,
    },
    ("chirikov", "chirikov", 1): {
        "dur": False,
        "frq": True,
        "damping": True,
        "srate": False,
        "dovesplice": False,
    },
    ("newtex", "newtex", 1): {
        "transposes": False,
        "dur": False,
        "chans": False,
        "maxrange": False,
        "step": True,
        "spacetype": False,
    },
    ("fractal", "wave", 2): {
        "shape": False,
        "dur": False,
    },
    ("spectrum", "fixed", None): {
        "datafile": False,
        "pointcnt": False,
        "srate": False,
        "dur": False,
        "atten": False,
    },
    ("spectrum", "format", None): {
        "indatafile": False,
        "pointcnt": False,
        "srate": False,
    },
    ("waveform", "make", 2): {
        "time": False,
        "dur": False,
    },
    ("brownian", "motion", 2): {
        "chans": False,
        "dur": False,
        "plo": True,
        "phi": False,
        "pstart": False,
        "sstart": False,
        "step": False,
        "sstep": False,
        "tick": True,
        "seed": False,
        "arange": False,
        "minamp": False,
        "linear": False,
    },
    # --- Wave 2 (tranches 14-15: sfedit/editing + gesture; see
    # docs/curation/tranche14_sfedit_editing_findings.json +
    # tranche15_gesture_findings.json) ---
    ("sfedit", "cutend", 1): {
        "length": False,
        "splice": False,
    },
    ("sfedit", "zcut", 1): {
        "start": False,
        "end": False,
    },
    ("sfedit", "excises", 1): {
        "excisefile": False,
        "splice": False,
    },
    ("sfedit", "masks", 1): {
        "excisefile": False,
        "splice": False,
    },
    ("sfedit", "insert", 1): {
        "time": False,
        "splice": False,
        "level": False,
        "overwrite": False,
    },
    ("sfedit", "replace", 1): {
        "time": False,
        "endtime": False,
        "splice": False,
        "level": False,
    },
    ("sfedit", "insil", 1): {
        "time": False,
        "duration": False,
        "splice": False,
        "overwrite": False,
        "keep_end_silence": False,
    },
    ("sfedit", "noisecut", None): {
        "splicelen": False,
        "noisfrq": False,
        "maxnoise": False,
        "mintone": False,
        "keep_noise": False,
    },
    ("sfedit", "joinseq", None): {
        "pattern": False,
        "splice": False,
        "maxlen": False,
        "splice_start": False,
        "splice_end": False,
    },
    ("sfedit", "joindyn", None): {
        "pattern": False,
        "splice": False,
        "splice_start": False,
        "splice_end": False,
    },
    ("sfedit", "twixt", 1): {
        "switchtimes": False,
        "splicelen": False,
        "weight": False,
        "randomize_order": False,
    },
    ("sfedit", "sphinx", 1): {
        "switchtimes": False,
        "splicelen": False,
        "weight": False,
        "randomize_order": False,
    },
    ("rejoin", "rejoin", 2): {
        "gain": False,
        "reverse": False,
    },
    ("manysil", "manysil", None): {
        "silencedata": False,
        "splicelen": False,
    },
    ("prefix", "silence", None): {
        "dur": False,
    },
    ("constrict", "constrict", None): {
        "constriction": True,
    },
    ("dvdwind", "dvdwind", None): {
        "contraction": True,
        "clipsize": True,
    },
    ("flatten", "flatten", None): {
        "elementsize": False,
        "shoulder": False,
        "tail": False,
    },
    ("housekeep", "copy", 1): {
        # no numeric parameters
    },
    ("housekeep", "endclicks", None): {
        "gate": False,
        "splicelen": False,
        "trim_start": False,
        "trim_end": False,
    },
    ("housekeep", "deglitch", None): {
        "glitch": False,
        "sil": False,
        "thresh": False,
        "splice": False,
        "window": False,
        "report": False,
    },
    ("extend", "freeze", 1): {
        "outduration": False,
        "delay": True,
        "rand": True,
        "pshift": False,
        "ampcut": False,
        "start": False,
        "end": False,
        "gain": False,
        "seed": False,
    },
    ("extend", "freeze", 2): {
        "repetitions": False,
        "delay": True,
        "rand": True,
        "pshift": False,
        "ampcut": False,
        "start": False,
        "end": False,
        "gain": False,
        "seed": False,
    },
    ("extend", "drunk", 1): {
        "outdur": False,
        "locus": True,
        "ambitus": True,
        "step": True,
        "clock": True,
        "splicelen": False,
        "clokrand": True,
        "overlap": True,
        "seed": False,
    },
    ("extend", "drunk", 2): {
        "outdur": False,
        "locus": True,
        "ambitus": True,
        "step": True,
        "clock": True,
        "mindrnk": False,
        "maxdrnk": False,
        "splicelen": False,
        "clokrand": True,
        "overlap": True,
        "seed": False,
        "losober": False,
        "hisober": False,
    },
    ("extend", "sequence", None): {
        "seqfile": False,
        "attenuation": False,
    },
    ("sorter", "sorter", 2): {
        "esiz": False,
        "smooth": False,
    },
    ("sorter", "sorter", 3): {
        "esiz": False,
        "smooth": False,
    },
    ("sorter", "sorter", 4): {
        "esiz": False,
        "smooth": False,
    },
    ("hover", "hover", None): {
        "frq": True,
        "loc": True,
        "frqrand": True,
        "locrand": True,
        "splice": False,
        "dur": False,
    },
    ("hover2", "hover2", None): {
        "frq": True,
        "loc": True,
        "frqrand": True,
        "locrand": True,
        "dur": False,
        "step": False,
        "normalise": False,
    },
    ("modify", "speed", 6): {
        "vibfrq": True,
        "vibdepth": True,
    },
    ("sfecho", "echo", None): {
        "delay": True,
        "attenuation": True,
        "totaldur": False,
        "rand": True,
        "cutoff": False,
    },
    ("verges", "verges", None): {
        "times": False,
        "transp": True,
        "exp": True,
        "glissdur": True,
        "usetimes": False,
        "boost": False,
        "suppress": False,
    },
    ("grainex", "extend", None): {
        "wsiz": False,
        "trof": False,
        "plus": False,
        "stt": False,
        "end": False,
    },
    ("repeater", "repeater", 1): {
        "datafile": False,
        "rand": True,
        "prand": True,
    },
    ("repeater", "repeater", 3): {
        "datafile": False,
        "accel": False,
        "warp": False,
        "fade": False,
        "rand": True,
        "prand": True,
    },
    ("phasor", "phasor", None): {
        "streams": False,
        "phasfrq": True,
        "shift": True,
        "ochans": False,
        "offset": False,
    },
    ("shifter", "shifter", 1): {
        "cycles": False,
        "cycdur": False,
        "dur": False,
        "ochans": False,
        "subdiv": False,
        "linger": False,
        "transit": False,
        "boost": False,
        "zigzag": False,
        "random": False,
    },
    # --- Wave 1 (tranches 12-13: submix depth + envelope family; see
    # docs/curation/tranche12_submix_depth_findings.json +
    # tranche13_envelope_findings.json) ---
    ("submix", "attenuate", None): {
        "inmixfile": False,
        "gain": False,
        "startline": False,
        "endline": False,
    },
    ("submix", "balance", None): {
        "balance": True,
        "begin": False,
        "end": False,
    },
    ("submix", "crossfade", 1): {
        "stagger": False,
        "begin": False,
        "end": False,
    },
    ("submix", "crossfade", 2): {
        "stagger": False,
        "begin": False,
        "end": False,
        "powfac": False,
    },
    ("submix", "faders", None): {
        "balance_data": False,
        "envelope_data": False,
    },
    ("submix", "getlevel", 3): {
        "mixfile": False,
        "start": False,
        "end": False,
    },
    ("submix", "merge", None): {
        "stagger": False,
        "skip": False,
        "skew": False,
        "begin": False,
        "end": False,
    },
    ("submix", "mergemany", None): {
        # no numeric parameters
    },
    ("submix", "pan", None): {
        "inmixfile": False,
        "pan": True,
    },
    ("submix", "shuffle", 3): {
        "inmixfile": False,
        "startline": False,
        "endline": False,
    },
    ("submix", "spacewarp", 5): {
        "inmixfile": False,
        "minpos": False,
        "maxpos": False,
        "startline": False,
        "endline": False,
    },
    ("submix", "sync", 1): {
        "intextfile": False,
    },
    ("submix", "sync", 2): {
        "intextfile": False,
    },
    ("submix", "syncattack", None): {
        "intextfile": False,
        "attackwin": False,
        "peakpower": False,
    },
    ("submix", "timewarp", 6): {
        "inmixfile": False,
        "scatter": False,
        "startline": False,
        "endline": False,
    },
    ("envel", "attack", 3): {
        "time": False,
        "gain": False,
        "onset": False,
        "decay": False,
        "envtype": False,
    },
    ("envel", "brktoenv", None): {
        "inbrkfile": False,
        "wsize": False,
    },
    ("envel", "create", 1): {
        "createfile": False,
        "wsize": False,
    },
    ("envel", "curtail", 2): {
        "fadestart": False,
        "fadedur": False,
        "envtype": False,
        "times": False,
    },
    ("envel", "cyclic", 3): {
        "wsize": False,
        "totaldur": False,
        "celldur": True,
        "phase": False,
        "trough": True,
        "expo": False,
    },
    ("envel", "envtobrk", None): {
        "inenvfile": False,
        "datareduce": False,
    },
    ("envel", "scaled", None): {
        "envelope": False,
    },
    ("envel", "swell", None): {
        "peaktime": False,
        "peaktype": False,
    },
    ("envel", "warp", 11): {
        "wsize": False,
        "trofdel": True,
        "peak_separation": True,
    },
    ("envel", "warp", 8): {
        "wsize": False,
        "gate": True,
        "smoothing": False,
    },
    ("envnu", "expdecay", None): {
        "starttime": False,
        "endtime": False,
    },
    ("envnu", "peakchop", 1): {
        "wsize": False,
        "pkwidth": True,
        "risetime": True,
        "tempo": True,
        "gain": True,
        "gate": False,
        "skew": False,
        "scatter": True,
        "norm": False,
        "repeat": True,
        "miss": True,
    },
    ("envnu", "peakchop", 2): {
        "wsize": False,
        "pkwidth": False,
        "risetime": False,
        "gate": False,
        "skew": False,
    },
    ("gate", "gate", 1): {
        "gatelevel": False,
    },
    ("gate", "gate", 2): {
        "gatelevel": False,
    },
    ("spike", "spike", None): {
        "peak": False,
        "upslope": True,
        "downslope": True,
        "maxdown": False,
    },
    ("topantail2", "topantail", None): {
        "startgate": False,
        "endgate": False,
        "splicelen": False,
        "backtrack": False,
    },
    ("tremenv", "tremenv", None): {
        "frq": False,
        "depth": False,
        "winsize": False,
        "fineness": False,
    },
    ("tremolo", "tremolo", 1): {
        "frq": True,
        "depth": True,
        "gain": True,
        "fineness": False,
    },
    # --- Phase 6 tranche 11 (iteration/sequence + event-timing; see
    # docs/curation/tranche11{a_iteration,b_event_timing}_findings.json) ---
    ("extend", "sequence2", None): {
        "seqfile": False, "attenuation": False, "splice": False,
    },
    ("extend", "iterate", 1): {
        "outduration": False, "delay": True, "rand": True, "pshift": True,
        "ampcut": True, "fade": False, "gain": False, "seed": False,
    },
    ("extend", "iterate", 2): {
        "repetitions": False, "delay": True, "rand": True, "pshift": True,
        "ampcut": True, "fade": False, "gain": False, "seed": False,
    },
    ("iterline", "iterline", 1): {
        "tdata": False, "outduration": False, "delay": True, "rand": True,
        "pshift": True, "ampcut": True, "gain": False, "seed": False,
        "normalise": False,
    },
    ("iterline", "iterline", 2): {
        "tdata": False, "outduration": False, "delay": True, "rand": True,
        "pshift": True, "ampcut": True, "gain": False, "seed": False,
        "normalise": False,
    },
    ("iterlinef", "iterlinef", 1): {
        "tdata": False, "outduration": False, "delay": True, "rand": True,
        "pshift": True, "ampcut": True, "gain": False, "seed": False,
        "normalise": False,
    },
    ("shrink", "shrink", 1): {
        "shrinkage": False, "gap": False, "contract": False, "dur": False,
        "spl": False, "small": False, "minsep": False, "rnd": False,
        "eqlevel": False, "invert": False,
    },
    ("shrink", "shrink", 4): {
        "time": False, "shrinkage": False, "gap": False, "contract": False,
        "dur": False, "spl": False, "small": False, "minsep": False,
        "rnd": False, "eqlevel": False, "invert": False,
    },
    ("texture", "decorated", 5): {
        "notedata": False, "outdur": False, "skiptime": True,
        "sndfirst": True, "sndlast": True, "mingain": True, "maxgain": True,
        "mindur": True, "maxdur": True, "phgrid": True, "gpspace": False,
        "gpsprange": True, "amprise": True, "contour": False,
        "gpsizlo": True, "gpsizhi": True, "gppaklo": True, "gppakhi": True,
        "gpranglo": True, "gpranghi": True, "centring": False,
        "atten": True, "position": True, "spread": True, "seed": False,
        "whole": False, "fixstep": False, "instrvary": False,
        "dectop": False, "decall": False, "discardline": False,
    },
    ("retime", "retime", 1): {
        "refpoints": False, "tempo": False,
    },
    ("retime", "retime", 3): {
        "minsil": False, "inevwidth": False, "outevwidth": False,
        "splicelen": False,
    },
    ("retime", "retime", 4): {
        "tempo": False, "minsil": False, "pregain": False,
    },
    ("retime", "retime", 5): {
        "factor": True, "minsil": False, "start": False, "end": False,
        "sync": False,
    },
    ("retime", "retime", 6): {
        "retempodata": False, "tempo": False, "offset": False,
        "minsil": False, "pregain": False,
    },
    ("retime", "retime", 7): {
        "retempodata": False, "offset": False, "minsil": False,
        "pregain": False,
    },
    ("retime", "retime", 8): {
        "tempo": False, "eventtime": False, "cnt": False,
        "repeats": False, "minsil": False,
    },
    ("retime", "retime", 9): {
        "maskdata": False, "minsil": False,
    },
    ("retime", "retime", 10): {
        "minsil": False, "evening": False, "meter": False,
    },
    ("retime", "retime", 12): {
        # no numeric parameters
    },
    ("peakfind", "peakfind", None): {
        "windowsize": False, "threshold": False,
    },
    ("clicknew", "clicks", None): {
        "clicktimes": False, "srate": False,
    },
    ("sorter", "sorter", 1): {
        "esiz": False, "smooth": False,
    },
    ("sorter", "sorter", 5): {
        "esiz": False, "seed": False, "smooth": False,
    },
    ("stutter", "stutter", None): {
        "slicedata": False, "dur": False, "segjoins": False,
        "silprop": False, "silmin": False, "silmax": False, "seed": False,
        "trans": True, "atten": True, "bias": False, "mindur": False,
        "permute": False,
    },
    ("housekeep", "chans", 3): {
        "channo": False,
    },
    ("housekeep", "chans", 4): {
        "phase": False,
    },
    ("housekeep", "chans", 5): {
        # no numeric parameters
    },
    # --- Phase 5 wave 4 (tranche 10: ST-covered singles; see
    # docs/curation/tranche10{a,b}_st_singles_findings.json) ---
    ("blur", "chorus", 5): {
        "aspread": True, "fspread": True,
    },
    ("blur", "noise", None): {
        "noise": True,
    },
    ("focus", "focus", None): {
        "fchans": False, "pbands": False, "quicksearch": False,
        "pk": False, "bw": True, "bt": True, "tp": True, "stable": False,
    },
    ("spec", "cut", None): {
        "starttime": False, "endtime": False,
    },
    ("spec", "gain", None): {
        "gain": True,
    },
    ("spectstr", "stretch", None): {
        "timestretch": True, "dratio": False, "dirand": False,
    },
    ("strange", "waver", 1): {
        "vibfrq": True, "stretch": True, "botfrq": False,
    },
    ("extend", "baktobak", None): {
        "join_time": False, "splice": False,
    },
    ("housekeep", "extract", 4): {
        "shift": False,
    },
    ("modify", "sausage", None): {
        "velocity": True, "density": True, "hvelocity": True,
        "hdensity": True, "grainsize": True, "pitchshift": True,
        "amp": True, "space": True, "bsplice": True, "esplice": True,
        "hgrainsize": True, "hpitchshift": True, "hamp": True,
        "hspace": True, "hbsplice": True, "hesplice": True,
        "range": True, "jitter": True,
    },
    ("multiosc", "multiosc", 3): {
        "dur": False, "frq1": True, "frq2": True, "amp2": True,
        "frq3": True, "amp3": True, "frq4": True, "amp4": True,
        "srate": False, "dovesplice": False,
    },
    ("phase", "phase", 1): {
        # no numeric parameters
    },
    ("phase", "phase", 2): {
        "transfer": False,
    },
    ("repitch", "transpose", 3): {
        "transpos": True, "minfrq": False, "maxfrq": False,
        "fullspec": False,
    },
    ("sfedit", "excise", 1): {
        "start": False, "end": False, "splice": False,
    },
    ("sfedit", "join", None): {
        "splice": False, "splice_start": False, "splice_end": False,
    },
    ("synspline", "synspline", None): {
        "srate": False, "dur": False, "frq": True, "splinecnt": True,
        "interpval": True, "seed": False, "maxspline": True,
        "maxinterp": True, "pdrift": False, "driftrate": False,
        "normalize": False,
    },
    # --- Phase 5 wave 3 (tranche 9: sibling submodes of already-curated
    # pairs; see docs/curation/tranche9_submodes_findings.json) ---
    ("scramble", "scramble", 9): {
        "seed": False,
        "cnt": False,
        "trns": True,
        "atten": True,
    },
    ("filter", "bank", 5): {
        "q": True, "gain": False, "lof": False, "hif": False,
        "filtcnt": False, "tail": False, "scat": False, "double": False,
    },
    ("filter", "bank", 6): {
        "q": True, "gain": False, "lof": False, "hif": False,
        "interval": False, "tail": False, "scat": False, "double": False,
    },
    ("morph", "bridge", 2): {
        "offset": False, "sf2": False, "sa2": False,
        "ef2": False, "ea2": False, "start": False, "end": False,
    },
    ("morph", "bridge", 3): {
        "offset": False, "sf2": False, "sa2": False,
        "ef2": False, "ea2": False, "start": False, "end": False,
    },
    ("modify", "radical", 2): {
        "repeats": False, "chunklen": False,
        "scatter": False, "smooth": False,
    },
    ("modify", "radical", 5): {
        "modfrq": True,
    },
    ("modify", "speed", 5): {
        "accel": False, "goaltime": False, "starttime": False,
    },
    ("envspeak", "envspeak", 2): {
        "wsize": False, "splice": False, "offset": False,
    },
    ("synth", "wave", 2): {
        "srate": False, "chans": False, "dur": False,
        "frq": True, "amp": True, "tabsize": False,
    },
    ("synth", "wave", 4): {
        "srate": False, "chans": False, "dur": False,
        "frq": True, "amp": True, "tabsize": False,
    },
    ("specfnu", "specfnu", 2): {
        "squeeze": True, "centre": False, "gain": False,
        "at_trough": False, "force_fundamental": False,
        "short_window": False, "exclude_nonharmonic": False,
        "kill_harmonic": False, "silence_unpitched": False,
    },
    # --- Phase 5 wave 2b (tranche 8; see docs/curation/) ---
    ("scramble", "scramble", 10): {
        "seed": False,
        "cnt": False,
        "trns": True,
        "atten": True,
    },
    ("texture", "grouped", 5): {
        "notedata": False,
        "outdur": False,
        "packing": True,
        "scatter": True,
        "tgrid": True,
        "sndfirst": True,
        "sndlast": True,
        "mingain": True,
        "maxgain": True,
        "mindur": True,
        "maxdur": True,
        "minpich": True,
        "maxpich": True,
        "phgrid": True,
        "gpspace": False,
        "gpsprange": True,
        "amprise": True,
        "contour": False,
        "gpsizelo": True,
        "gpsizehi": True,
        "gppaklo": True,
        "gppakhi": True,
        "gpranglo": True,
        "gpranghi": True,
        "atten": True,
        "position": True,
        "spread": True,
        "seed": False,
        "whole": False,
        "fixstep": False,
    },
    ("envspeak", "envspeak", 1): {
        "wsize": False,
        "splice": False,
        "offset": False,
        "repet": True,
        "rand": True,
    },
    ("morph", "bridge", 1): {
        "offset": False,
        "sf2": False,
        "sa2": False,
        "ef2": False,
        "ea2": False,
        "start": False,
        "end": False,
    },
    ("distort", "reform", 6): {
        # no numeric parameters
    },
    ("distort", "delete", 2): {
        "cyclecnt": True,
        "skipcycles": False,
    },
    ("distort", "replace", None): {
        "cyclecnt": True,
        "skipcycles": False,
    },
    ("analjoin", "join", None): {
        # no numeric parameters
    },
    ("newdelay", "newdelay", None): {
        "midipitch": True,
        "mix": False,
        "feedback": False,
    },
    ("quirk", "quirk", 1): {
        "powfac": False,
    },
    ("silend", "silend", 1): {
        "sildur": False,
    },
    # --- Phase 5 wave 2a (tranche 7: unblocked entries; see docs/curation/) ---
    ("submix", "mix", None): {
        "atten": False,
    },
    ("envel", "extract", 1): {
        "wsize": False,
    },
    ("formants", "get", None): {
        "fbands": False,
    },
    ("formants", "put", 1): {
        "quicksearch": False, "lof": False, "hif": False, "gain": False,
    },
    ("synth", "noise", None): {
        "srate": False, "chans": False, "dur": False, "amp": True,
    },
    ("synth", "wave", 1): {
        "srate": False, "chans": False, "dur": False,
        "frq": True, "amp": True, "tabsize": False,
    },
    # --- Phase 5 tranches 5-6 (sandbox-CDP probed; see docs/curation/) ---
    ("submix", "interleave", None): {
        # no numeric parameters
    },
    ("envel", "impose", 1): {
        "wsize": False,
    },
    ("envel", "replace", 1): {
        "wsize": False,
    },
    ("formants", "vocode", None): {
        "fbands": False,
        "lof": False,
        "hif": False,
        "gain": False,
    },
    ("spec", "grab", None): {
        "time": False,
    },
    ("modify", "loudness", 1): {
        "gain": True,
    },
    ("filter", "bank", 1): {
        "q": True,
        "gain": False,
        "lof": False,
        "hif": False,
        "tail": False,
        "scat": False,
        "double": False,
    },
    ("grain", "reverse", None): {
        "len": False,
        "gate": True,
        "minhole": False,
        "winsize": False,
        "ignore_last": False,
    },
    ("grain", "duplicate", None): {
        "repeats": True,
        "len": False,
        "gate": True,
        "minhole": False,
        "winsize": False,
        "ignore_last": False,
    },
    ("grain", "timewarp", None): {
        "ratio": True,
        "len": False,
        "gate": True,
        "minhole": False,
        "winsize": False,
        "ignore_last": False,
    },
    ("grain", "rerhythm", 1): {
        "multfile": False,
        "len": False,
        "gate": True,
        "minhole": False,
        "winsize": False,
        "ignore_last": False,
    },
    ("grain", "reposition", None): {
        "timefile": False,
        "offset": False,
        "len": False,
        "gate": True,
        "minhole": False,
        "winsize": False,
        "ignore_last": False,
    },
    ("pitch", "tune", 1): {
        "frequency": False,
        "focus": True,
        "clarity": True,
        "trace": True,
        "bcut": True,
    },
    ("combine", "interleave", None): {
        "leafsize": False,
    },
    ("combine", "max", None): {
        # no numeric parameters
    },
    ("strange", "shift", 4): {
        "frqshift": True,
        "frqlo": True,
        "frqhi": True,
        "log_interp": False,
    },
    ("distort", "interact", 2): {
        # no numeric parameters
    },
    ("clip", "clip", 2): {
        "fraction": False,
    },
    # --- Phase 3 tranche 3 (sandbox-CDP probed; see docs/curation/) ---
    ("texture", "simple", 5): {
        "notedata": False,
        "outdur": False,
        "packing": True,
        "scatter": True,
        "tgrid": True,
        "sndfirst": True,
        "sndlast": True,
        "mingain": True,
        "maxgain": True,
        "mindur": True,
        "maxdur": True,
        "minpich": True,
        "maxpich": True,
        "omit": True,
        "atten": True,
        "position": True,
        "spread": True,
        "seed": False,
        "whole": False,
    },
    ("modify", "stack", None): {
        "transpos": False,
        "count": False,
        "lean": False,
        "atk_offset": False,
        "gain": False,
        "dur": False,
        "normalise": False,
    },
    ("distort", "divide", None): {
        "divider": True,
        "interpolate": False,
    },
    ("distort", "omit", None): {
        "omit": True,
        "group": False,
    },
    ("extend", "doublets", None): {
        "segdur": True,
        "repets": False,
        "sync": False,
    },
    ("bounce", "bounce", None): {
        "count": False,
        "startgap": False,
        "shorten": False,
        "endlevel": False,
        "ewarp": False,
        "shrink": False,
        "cut_overlap": False,
        "trim_start": False,
    },
    ("specfnu", "specfnu", 1): {
        "narrow": True,
        "gain": False,
    },
    ("stretch", "spectrum", 1): {
        "frq_divide": False,
        "maxstretch": False,
        "exponent": False,
        "depth": True,
    },
    ("focus", "fold", None): {
        "lofrq": True,
        "hifrq": True,
    },
    ("focus", "step", None): {
        "timestep": False,
    },
    ("blur", "spread", None): {
        "fchans": False,
        "pbands": False,
        "spread": True,
    },
    ("blur", "suppress", None): {
        "n": True,
    },
    # --- Phase 3 tranche 2 (sandbox-CDP probed; see docs/curation/) ---
    ("modify", "revecho", 2): {
        "delay": False,
        "mix": False,
        "feedback": False,
        "lfomod": False,
        "lfofreq": False,
        "lfophase": False,
        "lfodelay": False,
        "tail": False,
        "prescale": False,
        "seed": False,
    },
    ("distort", "average", None): {
        "cyclecnt": True,
        "maxwavelen": False,
        "skipcycles": False,
    },
    ("distort", "fractal", None): {
        "scaling": True,
        "loudness": True,
        "pre_attenuation": False,
    },
    ("distort", "interpolate", None): {
        "multiplier": True,
        "skipcycles": False,
    },
    ("envel", "dovetail", 1): {
        "infadedur": False,
        "outfadedur": False,
        "intype": False,
        "outtype": False,
        "times": False,
    },
    ("sfedit", "cut", 1): {
        "start": False,
        "end": False,
        "splice": False,
    },
    ("stretch", "time", 1): {
        "timestretch": True,
    },
    ("strange", "glis", 1): {
        "fchans": False,
        "pbands": False,
        "glisrate": True,
        "topfrq": False,
    },
    ("strange", "invert", 1): {
        # no numeric parameters
    },
    ("hilite", "trace", 1): {
        "n": True,
    },
    ("spec", "magnify", None): {
        "time": False,
        "dur": False,
    },
    ("focus", "accu", None): {
        "decay": True,
        "glis": True,
    },
    # --- Phase 3 tranche 1 (sandbox-CDP probed; see docs/curation/) ---
    ("modify", "radical", 1): {
        # no numeric parameters
    },
    ("modify", "speed", 2): {
        "semitones": True,
    },
    ("distort", "multiply", None): {
        "multiplier": True,
    },
    ("distort", "repeat", None): {
        "multiplier": True,
        "cyclecnt": True,
        "skipcycles": False,
    },
    ("extend", "zigzag", 1): {
        "start": False,
        "end": False,
        "dur": False,
        "minzig": False,
        "splicelen": False,
        "maxzig": False,
        "seed": False,
    },
    ("extend", "scramble", 1): {
        "minseglen": False,
        "maxseglen": False,
        "outdur": False,
        "splen": False,
        "seed": False,
    },
    ("filter", "lohi", 1): {
        "attenuation": False,
        "passband": False,
        "stopband": False,
        "tail": False,
        "prescale": False,
    },
    ("blur", "avrg", None): {
        "n": True,
    },
    ("blur", "scatter", None): {
        "keep": True,
        "blocksize": True,
    },
    ("blur", "drunk", None): {
        "range": False,
        "starttime": False,
        "duration": False,
    },
    ("focus", "exag", None): {
        "exaggeration": True,
    },
    ("combine", "diff", None): {
        "crossover": True,
        "subzero": False,
    },
    ("morph", "glide", None): {
        "duration": False,
    },
    ("blur", "blur", None): {
        "blurring": True,
    },
    ("extend", "loop", 3): {
        "cnt": False, "start": False, "len": False,
        "step": False, "splen": False, "scat": False,
    },
    ("filter", "sweeping", 2): {
        "acuity": True, "gain": False,
        "lofrq": True, "hifrq": True, "sweepfrq": True,
        "tail": False, "phase": False,
    },
    ("modify", "brassage", 2): {
        "velocity": True,
    },
    ("morph", "morph", 1): {
        "as": False, "ae": False, "fs": False, "fe": False,
        "expa": False, "expf": False, "stagger": False,
    },
}


def _matrix_cases() -> list[tuple[str, str, int | None, str, bool]]:
    """Flatten the expectation table to one (program, mode, submode, param,
    expected) case per row for pytest's parametrize. Since the
    (program, mode, submode) re-keying (commit 728b986) each key carries
    its entry's declared submode — None for submode-less entries — so
    lookups stay exact-triple even on pairs curated in several submodes."""
    return [
        (program, mode, submode, param, expected)
        for (program, mode, submode), params in _EXPECTED_BREAKPOINT_CAPABLE.items()
        for param, expected in params.items()
    ]


@pytest.fixture(scope="module")
def knowledge_index() -> KnowledgeIndex:
    return KnowledgeIndex.load()


@pytest.mark.parametrize(
    ("program", "mode", "submode", "param", "expected"), _matrix_cases(),
    ids=[
        f"{p}_{m}_sm{s}_{param}_{expected}"
        for (p, m, s, param, expected) in _matrix_cases()
    ],
)
def test_breakpoint_capable_matches_empirical(
    knowledge_index: KnowledgeIndex,
    program: str,
    mode: str,
    submode: int | None,
    param: str,
    expected: bool,
) -> None:
    """Each curated parameter's ``breakpoint_capable`` matches the Task 5
    empirical probe outcome. The probe ran scalar + envelope invocations
    against real CDP r8; ``brkpnt_files not permitted`` → False, exit-0
    with output produced → True. See docs/phase-2-breakpoint-review.md."""
    entry = knowledge_index.get(program, mode, submode)
    assert entry is not None, (
        f"No curated entry for {program} {mode} sm{submode}"
    )
    spec = entry.parameters[param]
    assert spec.breakpoint_capable is expected, (
        f"{program} {mode} sm{submode}.{param}: knowledge JSON says "
        f"breakpoint_capable={spec.breakpoint_capable}, empirical Task 5 "
        f"probe says {expected}. Either CDP r8's behavior changed (re-run "
        f"the probe in docs/phase-2-breakpoint-review.md §methodology) "
        f"or the JSON was edited without updating the empirical record."
    )


def _flipped_to_true() -> list[tuple[str, str, int | None, str]]:
    return [
        (p, m, s, param)
        for (p, m, s), params in _EXPECTED_BREAKPOINT_CAPABLE.items()
        for param, expected in params.items()
        if expected
    ]


@pytest.mark.parametrize(
    ("program", "mode", "submode", "param"), _flipped_to_true(),
    ids=[f"{p}_{m}_sm{s}_{param}" for (p, m, s, param) in _flipped_to_true()],
)
def test_newly_capable_param_compiles_an_envelope(
    knowledge_index: KnowledgeIndex,
    program: str,
    mode: str,
    submode: int | None,
    param: str,
    tmp_path,
) -> None:
    """For each parameter Task 5 flipped to True, a 2-point relative-time
    envelope compiles cleanly. Source-duration / source-kind aren't
    behaviorally relevant at this layer — the compiler just needs a
    breakpoint-capable spec, a non-empty value, and writeable envelope
    storage."""
    entry = knowledge_index.get(program, mode, submode)
    assert entry is not None
    spec = entry.parameters[param]

    # Choose two values inside the param's declared range.
    lo = spec.min if spec.min is not None else 0.0
    hi = spec.max if spec.max is not None else (lo + 1.0)
    # Make sure hi > lo for the breakpoint to be a real ramp.
    if hi <= lo:
        hi = lo + 1.0

    result = compile_breakpoint_value(
        param_name=param,
        param_spec=spec,
        value=[[0.0, lo], [1.0, hi]],
        source_duration_s=2.0,
        source_kind="input_wav",
        session_root=tmp_path,
        envelopes_dir=tmp_path / "envelopes",
    )
    assert result.errors == [], (
        f"{program} {mode} sm{submode}.{param}: compile_breakpoint_value "
        f"returned errors despite breakpoint_capable=True: {result.errors}"
    )
    assert result.record is not None
    assert result.compiled_path is not None and result.compiled_path.exists()
