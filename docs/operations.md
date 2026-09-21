# Operations, acceptance, and rollback

## Startup evidence

All four startup logs must report identical values for `candidate_id`,
`max_model_len`, `max_num_seqs`, `max_num_batched_tokens`, and
`gpu_memory_utilization`. Node 0 must expose port 8000; the other nodes must run
with `--headless` and connect to the node-0 DP RPC port 13399.

Do not send inference traffic until:

1. all four pods are Running;
2. every DP engine has finished weight loading and graph capture;
3. `scripts/health.sh` exits 0 on every pod;
4. `/v1/models` lists `deepseek-v4.1-flash`;
5. non-streaming and streaming smoke tests pass.

## Monitoring

`runtime_telemetry.sh` records the key vLLM metrics, NPU status, CPU, memory,
RSS, shared memory, NIC counters, KV usage, queues, speculative acceptance, and
graph fallback signals. The default 30-second interval is appropriate for
operations. Use one-second sampling only for an explicitly bounded benchmark;
it creates very large log files.

Alert on:

- any pod restart, engine death, HCCL timeout, OOM, or graph compilation error;
- `num_requests_waiting` growth without recovery;
- KV usage approaching exhaustion or any preemption;
- a rank using a different candidate or topology;
- HTTP 5xx, invalid SSE termination, or an empty response.

## Known service limit

Huawei Cloud ModelArts synchronous real-time inference has a fixed 3,600-second
end-to-end request limit. Streaming chunks refresh the ordinary request timeout,
but they do not extend that end-to-end ceiling. The service-level request
timeout field itself accepts at most 1,200 seconds.

This environment completed one directional capacity test with 833,776 input
tokens plus 204,800 output tokens in 3,488.7 seconds. That is evidence for the
tested combination, not a production SLO. The remaining 111-second margin is
too small to promise 200K output under arbitrary contention. Validate the real
workload separately.

Official limit: <https://support.huaweicloud.com/intl/en-us/inference-modelarts/inference2.0-modelarts-0016.html>

## Rollback

Before an update, record the currently running service version, rendered JSON,
SWR digest, model revision, and package manifest.

If a new version fails before receiving traffic, stop or delete only the failed
deployment version and keep the previous version active. If traffic has already
been switched, use ModelArts version switching to return to the recorded stable
version, then verify `/health`, `/v1/models`, non-streaming, and streaming calls.

Never delete the SFS checkpoint or previous SWR digest as part of a rollback.
Deletion is a separate, explicitly approved retention operation.

