# S4 — Findings

## FIND-01 (addressed by the change itself): single-thread flags do not fix it
450 renders of the VO-ducking audio chain WITH -filter_threads 1
-filter_complex_threads 1 -> 6 distinct PCM hashes; 60 renders WITHOUT the
flags -> the SAME 6 hashes. The nondeterminism is NOT caused by threaded
filter execution. The flags were tried, proven ineffective, and NOT shipped.
(Evidence: ~/workspace/t044-mismatch/duck_determinism_exp.py, results in
/tmp/t044-duck-exp/results.json — experiment dir is per-task temp, tier a.)

## FIND-02 (accepted): byte-exact assertion incompatible with product chain
ffmpeg 8.1.2 sidechaincompress emits a per-render audio-tail perturbation
(~25 ms, max |Δ| -48.6 dBFS measured across 450 renders; -48.4 dBFS on the
original incident pair). The old sha256-of-mp4 assertion failed ~2.5%/render
through no fault of the recovery path. Relaxed per Dino's decision: video
bytes bit-identical (proven: 626/626 frames identical in the incident), audio
within -40 dBFS (~8.6 dB margin over measured max).

## Rejected leads
- R1 "just pin thread flags and keep byte-exact": REJECTED with traced
  counter-evidence — 450 renders, identical variant set with/without flags.
- R2 "remove sidechaincompress": out of scope — changes product audio
  behavior; needs Dino's product decision, not a test fix.
- R3 "pin makes renders slower/fragile": the pin is one ffmpeg -version call
  (~10 ms) placed after the skip path; mocked-subprocess tests still green.
