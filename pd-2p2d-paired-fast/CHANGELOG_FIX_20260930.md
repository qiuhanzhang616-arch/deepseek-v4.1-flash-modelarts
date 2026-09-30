# Paired DSpark and explicit-role discovery fix

Authorized scope: isolated PD service84ca83ba-ff39-4f75-89af-a4f3fc35d771 only.
No mixed DeepSeek, GLM, gateway route or shared-pool configuration changes.

Current pressure-test logs at13:01UTC show MooncakeHybridConnector line709
IndexError indexing remote_block_ids in Decode. Prefill actual engine config
speculative_config=None, Decode DSpark5. Matching layout is required by this
connector; both roles now unconditionally pass identical DSpark5/eager draft.
The override PD_NUM_SPEC_TOKENS may only be5 in this immutable deployment.

Latest v1.0.5 logs show all four waiting local ranktable role matches found0,
before model loading. New discovery publishes explicit startup role + Pod IP
and identity to an independent SFS epoch; ranks use shared deterministic name
order within each role. No dependency on role strings in platform ranktable.
Four unique peers and equal script/DSpark/model/context contracts are required.
Registration heartbeats remain alive while engine/proxy run; stale or previous
epoch records cannot satisfy the fresh four-peer quorum. Poll1s, wait300s.
Failure remains closed with descriptive counts and preserves logs.

Compatibility shim retained; logging installed once across re-exec to avoid
duplicate tee output. Existing inference parameters retained: Prefill32768/32,
Decode512/32, ctx1048576, TP8/EP, INT8 host Engram. The actual SFS snapshot
already defaults both main engines to FULL_DECODE_ONLY (P supports an eager
override); this setting was preserved. Draft eager is identical on both roles.
This does not remove model weight loading or compile cost; no loading-speed
claim before runtime timing evidence. New SFS path:
/model/w4a8/pd-paired-fast-20260930-r1/pd_entrypoint.sh prefill|decode

Local and remote six tests passed, including real four-process discovery
without any ranktable. bash syntax checks passed. Remote validated hashes:
entry73d4fbe18e3952dce43dbfc11e65b1133278ae259eee5d458df37a8345e5dd4a
common0ec8016cd414425479637cdd91fcf34f8db9fcf35ed9b85b1fee681911506656
discoveryff5b11d47e855ba4fc5561d5678585c651c907249faa4a5925c8428f6c777e6f

Deployment not yet submitted: existing1.0.5 stopping; normal UI refused
upgrade while stopping. Wait for stopped/released then submit one normal
upgrade with only both command paths + description changed. Preserve image,
SFS, topology, ports, probes, authentication and scheduling controls.
After submission require actual four role registrations and discovery timings,
all ranks/health, actual paired DSpark5, stream correctness and no KV transfer
IndexError. No performance promotion from readiness alone. Rollback startup
directory pd-dspark5-20260930 remains untouched by this fix.
