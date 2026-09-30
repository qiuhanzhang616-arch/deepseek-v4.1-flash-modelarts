# PD customer-shaped75 P0 screen contract

User authorized deployment acceptance followed by separate PD customer-shape
tuning. Core functional gates passed; this contract starts an independent PD
baseline, not a mixed-engine comparison or measured improvement.

Source75 manifest: D:/dataprev/w4a8-customer-shaped-75-20260930.json.
75synthetic requests,13shapes, C1/C4/C8 counts8/24/43, inputsum6275072,
outputsum42496, hot56/cold19 with4balancedhotgroups. Derived from historical
customer distribution, NOT customer originals/clean08–18arrival traces.
Closed-loop phases are NOT natural arrival replay. Do not infer actual APC
hit ratio from hot labels. Baseline and candidates must retain this version.

Capacity: unchanged P0, 2P2D/fourA2nodes32NPUs. Local PD proxy9000 path,
client on the same selected PD Pod for every candidate; backendtokenize8000
exact chat input withlow template and generationprompt. No productionroute
changes. Fresh namespace per run, preserved rawrequest/SSE/results.

Output: streaming,temp0,low+budget128,max_tokens per manifest,ignore_eostrue,
include_usage; must actualinput/output match manifest, marker in finalbody,
SSEDONE, no clientretry/fallback. This is length-shaped output, not natural
early-stop code generation. Longtool semantics tested separately. Tool
finishstop and externalModelArtsrawSSE limitations remain disclosed.

Preparation: tokenize every request before timer, no inference during prep.
4excluded hotgroup primes, each largest group's input and256outputtokens,
concurrency4 within300s warmup. Hotgroup designs do not ensure every P engine
cache is warm. Fixed phase starts300/900/1620, ends900/1620/2400sec from
warmupstart. C1/C4/C8 concurrencyfixed, stop submitting after any failure.
All alreadyactive requests drain; unsubmitted IDs explicitly reported.
No failedsubset SLA. Limits/deadlines unchanged for candidates.

Metrics: E2E, firststreamtoken, firstfinalcontent, usage, cachedtoken counts,
requestTPS; stream TPOT estimate=(laststreamtoken-first)/(usagecompletion-1),
coalescedchunks limitation disclosed. No unsupported exacttoken-level timing
claims. Enginequeue/APC/resource/log evidence collected before/after run;
final pass requires enginehealth and rawerror review, not justHTTP200.

Candidate P1 changes onlyPbatch8192→4096. P2 independently changes only
Dbatch512→1024 fromP0. Need functionalgate and samecapacity run per candidate,
two independent benefit reproductions; no blind combinations.
Targets: E2EP95/firstusableP95≥25% improvement, longoutputTPOTP95≥15%,
importantbucketregression≤5%, qualitystable, zeroengine/HCCL/OOM/SSEfailures.
Synthetic benefits alone cannot prove customerperceived gains.
