"""NF-06 线程安全的进程内运行指标，进程重启即清零。"""
import threading


_OPERATIONS = ("parse", "index", "asr", "sse")
_OUTCOMES = ("success", "failure", "rejected", "disconnected")
_LOCK = threading.Lock()


def _empty_metrics():
    return {
        operation: {"total": 0, **{outcome: 0 for outcome in _OUTCOMES},
                    "duration_ms": 0.0}
        for operation in _OPERATIONS
    }


_metrics = _empty_metrics()


def record_runtime_metric(operation: str, outcome: str, duration_ms: float) -> None:
    with _LOCK:
        metric = _metrics[operation]
        metric["total"] += 1
        metric[outcome] += 1
        metric["duration_ms"] += duration_ms


def runtime_metrics_snapshot() -> dict:
    with _LOCK:
        return {
            operation: {
                "total": metric["total"],
                **{outcome: metric[outcome] for outcome in _OUTCOMES},
                "failure_rate": (
                    metric["failure"] / metric["total"] if metric["total"] else 0
                ),
                "avg_duration_ms": (
                    metric["duration_ms"] / metric["total"] if metric["total"] else 0
                ),
            }
            for operation, metric in _metrics.items()
        }


def reset_runtime_metrics() -> None:
    global _metrics
    with _LOCK:
        _metrics = _empty_metrics()
