# W4A8 2P2D on ModelArts Standard (isolated candidate)

This is a four-node, 32-A2-NPU **experimental** prefill/decode deployment for
DeepSeek-V4.1-Flash W4A8. It must not replace a working service before all
four roles, KV transfers, APIs and 128K/256K requests pass acceptance.

## Layout

| ModelArts unit | Instances | Launch command | Per-instance |
|---|---:|---|---|
| role-0-prefill | 2 | `bash /model/w4a8/pd-2p2d-20260929/pd_entrypoint.sh prefill` | 8 A2 NPUs, TP8/EP8, external DP2 rank 0/1 |
| role-1-decode | 2 | `bash /model/w4a8/pd-2p2d-20260929/pd_entrypoint.sh decode` | 8 A2 NPUs, TP8/EP8, external DP2 rank 0/1 |

Both units use the validated image tag
`modelarts/vllm-ascend:deepseek-v41-flash-w4a8-20260927-arm64` (pin its digest
in the deployment record) and the existing W4A8 SFS volume. Mount
the SFS root to `/model/w4a8` (read-only weights can be a separate submount),
so `/model/w4a8/model-view/config.json` and this script directory both exist.
The model-view must be `W4A8_DYNAMIC`, including tokenizer, quant metadata and
the preassembled INT8 Engram tensors. Do not use the W8A8 checkpoint.

Each Pod discovers the four Pod IPs from `GLOBAL_RANK_TABLE_FILE_PATH` and its
own `POD_IP`. It fails closed if the table is incomplete or contains anything
other than two prefill plus two decode Pods. **Never reuse the old B0 Pod IPs.**
All four Pods run an engine on HTTP 8000 plus the PD proxy on HTTP 9000. Use
`/healthcheck` on port 9000 for the ModelArts health check. ModelArts service
protocol must match the proxy's HTTP protocol; terminate HTTPS at the platform
front end if required. Do not set a production/default LiteLLM route for this
candidate.

Initial functional baseline: 1M context, P batch 8192/seq16, D batch
512/seq32, GPU memory utilization 0.90, P prefix cache enabled, D prefix cache
disabled, BF16 KV, INT8 host-resident Engram, no speculative decoding. These
are bring-up values, **not a measured optimum** for 128K/256K input and ~1K
output. `--attention-config indexer_kv_dtype=int8` is intentionally absent:
vLLM 0.27.1 rejects that value.

Run `python3 -m unittest -v test_pd_ranktable` and `bash -n *.sh` before
upload. After launch, verify the log for two P and two D ranks, no HCCL/OOM,
`/healthcheck`, `/v1/models`, non-streaming and SSE `[DONE]`, then one 128K
and one 256K input with ~1K output. A health response alone is not acceptance.

Rollback: stop only the new isolated deployment, preserve its logs and SFS
scripts. The pre-existing four-replica W4A8 service remains unchanged and is
the live fallback. B0 was stopped by explicit user instruction to free nodes.
