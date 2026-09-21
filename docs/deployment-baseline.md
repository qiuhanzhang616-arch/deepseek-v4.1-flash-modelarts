# Deployment baseline

## Project identity

- Deployment type: reusable new-deployment template.
- Target platform: Huawei Cloud public cloud, ModelArts real-time inference
  (new version), dedicated inference resource pool.
- Service form: synchronous OpenAI-compatible text-generation API.
- Target workload: long-context chat and coding workloads.

## Validated reference baseline

- Model: `Eco-Tech/DeepSeek-V4.1-Flash-w8a8`.
- Pinned revision: `44201f6d0e14cbc5e73067029762676557a3e7e9`.
- Image: `quay.io/ascend/vllm-ascend:deepseek-v4.1-flash` pinned to digest
  `sha256:521f866a8d45b5af40cde09c46664838dae41031f4a0ed0183091bdd8ebed2d8`.
- Hardware: four 8-NPU Atlas 800 A2 nodes, ARM64, 64 GiB HBM per NPU.
- Topology: DP4/TP8/EP32, colocated Prefill and Decode.
- Runtime: vLLM V1 with vLLM Ascend, Ascend W8A8, INT8 Engram, DSpark
  speculative decoding, and `FULL_DECODE_ONLY` graph mode.
- Context baseline: 1,048,576 tokens.
- Saved configuration: 32 sequences, 4,096 batched tokens, 0.94 memory
  fraction, 128-token KV blocks.
- Storage: SFS Turbo shared by all four nodes.
- API: port 8000, model alias `deepseek-v4.1-flash`.

## Target-project values that must be supplied

| Item | Required value |
|---|---|
| Region and ModelArts endpoint | Target Huawei Cloud public-cloud region |
| Project and workspace IDs | Target account/project |
| Dedicated inference pool ID | Pool containing four free 8-NPU A2 nodes |
| A2 flavor ID | Exact flavor exposed in that pool and region |
| SFS Turbo ID and subdirectory | Same region, associated with the pool |
| SWR registry path | Private repository in the target region |
| API access channel | Private, public, or ELB according to project security policy |
| Allowed client CIDRs | Project-owned network ranges |
| API key owner and rotation | Project security owner |
| Logging and retention | Project operations policy |

These values are intentionally absent from this repository. They are blocking
inputs for deployment, but not for static validation of the package.

## Acceptance contract

- Infrastructure: four A2 nodes free, SFS attached, SWR pull works, network
  paths and ports are open.
- Runtime: four ranks agree on DP4/TP8/EP32 and all engines become ready.
- Interface: health, model listing, non-streaming, streaming, reasoning, and
  tool-call smoke tests pass.
- Reliability: no restart, OOM, HCCL error, rank mismatch, or invalid stream.
- Security: API key authentication is bound; no credentials appear in files or
  logs; public access is disabled unless explicitly approved.
- Minimum capacity: a project-approved request shape completes once. Formal
  throughput and concurrency testing are separate activities.

## Stop conditions

Stop deployment or testing on any weight-integrity failure, insufficient NPU
count, model load failure, OOM, HCCL error, repeated pod restart, incompatible
image architecture, or unexpected public exposure. Do not change context,
quantization, or topology merely to hide a failed gate.

