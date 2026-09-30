# User-selected Prefill batch recovery

Only inference change relative to paired-fast-r1: Prefill default batch32768
to8192. Prefillseq32 and GPUmemoryutil0.90 unchanged; Decode512/32/0.90,
pairedDSpark5/eagerdraft, ctx1M and actual mainP/D FULL_DECODE_ONLY retained.
Fresh isolated discovery epoch r3; oldr1 files and failed logs preserved.
0.85 memory trial r2 was staged but never submitted to ModelArts, not deployed.

Evidence13:49:54UTC r1 Prefill Engram reference gate allocated2.49GiB with
289.94MiB free; subsequent metadata/Gloo errors followed and both P engines
exited. Batch reduction targets per-step activation/temporary tensor pressure;
do not assume OOM resolved until short and long-input regression checks pass.
Global defaults for new upgrade: local platform cache acceleration enabled,
gracefulshutdown enabled, automaticrebuild disabled. Confirm actual UI settings,
do not substitute APC for platform caching or change authentication/routes.
