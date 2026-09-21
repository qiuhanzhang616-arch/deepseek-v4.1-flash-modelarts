# Validated architecture

```text
Huawei Cloud ModelArts real-time inference (new version)
  |
  +-- role-0: 1 x Atlas 800 A2 node, 8 NPUs, API port 8000
  |
  +-- role-1: 3 x Atlas 800 A2 nodes, 8 NPUs each, headless
  |
  +-- SFS Turbo: weights, scripts, manifests, runtime logs
  |
  +-- private SWR: pinned ARM64 vLLM Ascend image
```

Global topology:

- 4 physical A2 nodes and 32 NPUs total.
- Tensor parallelism: TP8 within each node.
- Data parallelism: DP4 across nodes.
- Expert parallelism: EP32 globally.
- Colocated Prefill and Decode; no P/D disaggregation.
- Node 0 exposes the OpenAI-compatible API. Nodes 1–3 use `--headless`.
- ModelArts injects `POD_IP` and
  `/user/global/config/global_rank_table.json`; `ma_rank.py` derives the stable
  node order and the node-0 DP RPC address.

Validated inference baseline:

| Setting | Value |
|---|---:|
| Context length | 1,048,576 |
| Max sequences per DP rank | 32 |
| Max batched tokens | 4,096 |
| NPU memory fraction | 0.94 |
| KV block size | 128 |
| Quantization | Ascend W8A8 |
| Engram storage | INT8 |
| Speculative decoding | DSpark, 5 draft tokens, eager drafter |
| Target graph mode | `FULL_DECODE_ONLY` |
| Tokenizer/reasoning/tool parser | `deepseek_v41` |

The 0.94 memory fraction is a measured requirement for the pinned A2 image and
checkpoint. A 0.90 baseline did not admit a 1M KV cache. Treat this as a
hardware/software-specific baseline, not a universal value for other Ascend
generations or image revisions.

