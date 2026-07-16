# Curation completion roadmap — tranches 12–23 (2026-07-15)

> Goal: curate every remaining RELEVANT program and mode. Post-tranche-11
> state: 134 curated / 302 total. Out of scope (standing decisions): the
> multichannel/spatial family (DAW-side of the micro/macro boundary),
> toolkit plumbing (cdparams, tkusage, dirsf, listdate...), Sound
> Loom-only paths, and multi-output programs with no outfile argv (drop
> with evidence, per precedent). Scope confirmed with the user
> 2026-07-15: everything else, INCLUDING pitch-data/FOF/data-conversion
> layers.
>
> Execution: waves of two parallel curation agents (tranche-2
> methodology verbatim, findings in tranche-9 shape, agents never touch
> tests/server.py), then the integrator folds pinned tables, runs the
> suite both ways (chunked real-CDP in-sandbox), commits per tranche +
> integration. Attrition expected everywhere — drops with recorded
> evidence beat forced entries. Mode lists below come from banner
> parsing and MUST be re-verified against the binaries; some listed
> "modes" are banner prose or params.

## Wave 1 — mix + envelope

**T12 — submix depth** (Phase 6 timeline() adjacency): merge, balance,
crossfade, inbetween, inbetween2, shuffle, timewarp, spacewarp, sync,
syncattack, faders, atstep, ongrid, mergemany, pan, getlevel (data
output — the P5-3 pre-flight, curating it makes timeline()'s headroom
staging a curated call), attenuate, addtomix, model; probe-and-likely-
drop: test, fileformat, dummy.

**T13 — envelope family**: envel modes create, cyclic, warp, reshape,
tremolo, swell, attack, pluck, curtail, scaled, timegrid + the data
conversions (envtobrk, envtodb, replot, dbtogain, gaintodb, brktoenv,
dbtoenv — data in/out kinds, envel extract precedent); programs
tremolo, tremenv, spike, topantail2, envcut, envnu (suite), gate;
housekeep gate. Note: a curated gate matters beyond itself — retime's
literal-zero event detection needs a gate upstream (tranche 11b).

## Wave 2 — editing + gesture

**T14 — sfedit depth + editing utilities**: sfedit modes cutend, zcut,
zcuts, excises, insert, replace, insil, masks, randcuts, randchunks,
cutmany, noisecut, syllables, joinseq, joindyn, twixt, sphinx;
programs isolate, rejoin (pairs with isolate), manysil, prefix,
constrict, dvdwind, flatten; housekeep modes copy, endclicks,
deglitch.

**T15 — gesture/time-domain programs**: extend modes freeze, drunk,
sequence (the 1-input sibling of curated sequence2); programs freeze,
hover, hover2, shifter, repeater, verges, stretcha, strans, unknot,
phasor, grainex, packet, sfecho; sorter modes 2, 3, 4.

## Wave 3 — waveset + synthesis

**T16 — waveset/distort extensions**: distort modes replim, reverse,
envel, harmonic, shuffle (may hit the free-string gap like blur
shuffle — record if so), filter, pitch, telescope, overload, pulsed,
repeat2; programs distcut, distmark, distmore (suite), distortt,
distrep, distshift, partition, splinter, crumble, cascade, fracture.

**T17 — synthesis/generative**: synth modes silence, spectra, clicks,
chord; programs impulse, pulser, motor, ceracu, newsynth (suite),
multisynth, newtex (suite), strands, brownian, chirikov, fractal,
frfractal, synfilt, ts, tsconvert, spectrum, waveform. Arity-0
precedent: synth_wave_2.json; many take score/data aux files.

## Wave 4 — texture/filter depth + grain/FOF

**T18 — texture + filter depth**: texture modes ornate, preornate,
postornate, motifs, motifsin, tmotifs, tmotifsin, predecor, postdecor,
timed, tgrouped; filter modes fixed, variable, userbank, varibank,
varibank2, iterated, phasing (bankfrqs = data/info output, probe).
Texture notedata conventions per texture_simple/grouped/decorated;
filter vintage warning (P5-1) applies to anything with the
normalization pre-pass — verify per mode.

**T19 — grain depth + FOF family**: grain modes count (data out?),
omit, repitch, find, reorder, remotif, align, grev, r_extend,
noise_extend, assess; programs psow (pitch-synchronous grain suite,
many modes — curate the ST-covered subset first), fofex, iterfof,
tweet. Grain-gate landmines from the generalization matrix carry to
every entry here (articulation constraints in known_issues).

## Wave 5 — spectral tail

**T20 — spectral tail I** (modes of curated programs + lighter
programs): blur weave (free-string risk like shuffle — record); combine
sum, mean (+ make/make2 utilities — probe, likely data/utility drops);
focus freeze, hold; spec gate, bare, clean; hilite filter, greq, band,
arpeg, pluck, bltr, vowels; programs specfold, specav, specenv,
speclean, specnu, suppress, subtract, cantor, caltrain, notchinvert,
peakiso, glisten.

**T21 — spectral tail II** (heavy/multi-input spectral): selfsim,
superaccu, speculate, spectwin, specross, newmorph, specgrids,
spectune, specanal, specvu (data out), peak, get_partials, oneform,
tunevary, features, fturanal.

## Wave 6 — pitch-data + text-data

**T22 — pitch/repitch family**: pitch modes altharms, octmove, transp,
pick, chordf, chord; repitch modes getpitch, approx, exag, invert,
quantise, randomise, smooth, vibrato, cut, fix, combine, combineb,
synth, vowels, insertzeros, insertsil, pitchtosil, noisetosil,
analenv, generate, interp, pchtotext, pchshift, transposef; programs
pitchinfo, ptobrk, brktopi, convert_to_midi. Most consume/produce
binary pitch data (.frq) — data in/out kinds throughout; expect shared
argv shapes and heavy attrition into grouped entries.

**T23 — data/text utilities**: columns (large text-data suite),
getcol, putcol, vectors, matrix, newscales, hfperm, histconv,
cubicspline, smooth. Pure data→data; curate what the engine's data
kinds can express, drop the rest with evidence.

## Bookkeeping per wave (integrator)

Pinned counts (loader + list_programs), breakpoint matrix rows,
duration rows (use _AUX_FILES for aux-referencing rows), stub
retirement for first-curated programs, domain-pin updates for spectral
additions (waves 5–6 WILL change the pinned spectral sets), suite both
ways + ruff, SESSION-STATE checkpoint. Sandbox landmines unchanged
(chunked real-CDP runs; fresh output names; same-second seeds).
