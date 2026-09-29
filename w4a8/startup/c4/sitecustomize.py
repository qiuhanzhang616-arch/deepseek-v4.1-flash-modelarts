"""ModelArts-safe OpenTelemetry resource detection for the W4A8 A2 runtime.

The current ModelArts W4A8 container fails while importing OpenTelemetry:
Resource.create() calls get_aggregated_resources(), which creates a worker
thread before vLLM or model loading. Keep the two built-in detectors, but run
them synchronously so the SDK import does not require a ThreadPoolExecutor.
The startup wrapper constrains OTEL_EXPERIMENTAL_RESOURCE_DETECTORS to these
built-ins and probes actual thread creation before allowing model loading.
"""

import logging
import sys

try:
    import opentelemetry.sdk.resources as _resources
except Exception as exc:
    print(f"[w4a8-otel-shim][ERROR] OpenTelemetry resources import failed: {exc}", file=sys.stderr, flush=True)
    raise

_logger = logging.getLogger("opentelemetry.sdk.resources")


def _serial_resource_detection(detectors, initial_resource=None, timeout=5):
    """Match SDK resource merging without creating worker threads.

    timeout is retained for signature compatibility. The startup environment
    selects only service_instance and otel built-ins, whose detect() calls are
    local, non-blocking operations.
    """
    del timeout
    if initial_resource is not None:
        merged = initial_resource
    else:
        merged = getattr(
            _resources,
            "_DEFAULT_RESOURCE",
            _resources.Resource.get_empty(),
        )

    for detector in detectors:
        try:
            detected = detector.detect()
        except Exception as exc:
            if getattr(detector, "raise_on_error", False):
                raise
            _logger.warning("Exception %s in detector %s, ignoring", exc, detector)
            detected = _resources.Resource.get_empty()
        merged = merged.merge(detected)
    return merged


_resources.get_aggregated_resources = _serial_resource_detection
_resources._w4a8_serial_resource_detection = True
print("[w4a8-otel-shim] synchronous built-in resource detection enabled", file=sys.stderr, flush=True)

