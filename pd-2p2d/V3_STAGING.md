# W4A8 PD v3 staging (not deployed)

This directory is an independent copy of the v2 2P2D scripts. Do not replace
the live v2 SFS directory or submit a new ModelArts deployment while v2 holds
the four 8-NPU nodes.

## Evidence and narrow change

In v2, at least one prefill Pod completed peer discovery, but the vLLM import
path emitted `OpenBLAS blas_thread_init: pthread_create failed ... Operation not
permitted`; the ModelArts default log ended in `KeyboardInterrupt` and
`[pd] engine exited before /health`. The verified C5 W4A8 service uses an
additive clone3-EPERM-to-ENOSYS launcher and one BLAS/OMP thread. v2 did not.
This correlation does not prove a unique root cause until v3 is tested on A2.

v3 installs compatibility at the entrypoint, so discovery, engine, health
checks and proxy all inherit it. `pd_common.sh` exports one default OMP thread
and exactly one OpenBLAS/MKL/NumExpr thread and preserves the vLLM argument
array. A new v3 rendezvous namespace prevents reuse of stale v2 records.
The `pd_clone3_compat.py` launcher fails closed
unless the inherited AArch64 policy returns EPERM for clone3, adds a narrow
ENOSYS filter without removing inherited restrictions, verifies a Python
thread can start, and execs the original vLLM command. Address rendezvous,
topology, weights, image, API/proxy, mounts and health probe are unchanged.

## Offline checks

- `python -m py_compile pd_clone3_compat.py`
- `python -m unittest -v test_pd_ranktable` (5 tests)
- `bash -n pd_common.sh pd_entrypoint.sh`

These do not prove A2 runtime compatibility. Before deployment, copy this
directory to a new versioned SFS subdirectory, verify file hashes there,
and change only the two ModelArts unit startup paths. Wait for v2 to reach a
supported terminal state and for all four nodes to show 8/8/8 available.
After submitting, require peer discovery, clone3 before/after and thread
probe logs, eight TP ranks per Pod, four healthy Pods, port 9000, and API
functional smoke tests. Do not call it online before those gates pass.
