"""
timesfm_signal.py - TimesFM 3.0 wrapper.

Loads the model once (~1.3 GB, cached in ~/.cache/huggingface/) and exposes
get_signal() + _load() for the bots.
"""

import sys
import time

import numpy as np

_MODEL_ID = "google/timesfm-3.0-pytorch"
_forecaster = None
_load_ms = None


def _load():
    """Load TimesFM once. Cached at module level so repeated calls are free."""
    global _forecaster, _load_ms
    if _forecaster is not None:
        return _forecaster
    t0 = time.time()
    print("loading TimesFM 3.0...")
    from timesfm3 import TimesFM3Forecaster
    _forecaster = TimesFM3Forecaster.from_pretrained(_MODEL_ID)
    _load_ms = int((time.time() - t0) * 1000)
    print(f"TimesFM ready in {_load_ms} ms")
    return _forecaster


def get_signal(candles, horizon_steps: int = 3, debug: bool = False):
    """Convert OHLC candles into a directional signal."""
    if not candles or len(candles) < 32:
        return None

    closes = np.array([float(c[2]) for c in candles], dtype=np.float32)
    last_price = float(closes[-1])

    try:
        forecaster = _load()
        t0 = time.time()
        out = forecaster.predict(context=closes, horizon=int(horizon_steps))
        infer_ms = int((time.time() - t0) * 1000)
    except Exception as e:
        print(f"TimesFM inference failed: {e}")
        return None

    median = np.asarray(out.forecast).flatten()[:horizon_steps]

    quantiles = None
    for attr in ("quantiles", "forecast_quantiles", "quantile_forecast"):
        q = getattr(out, attr, None)
        if q is not None:
            quantiles = np.asarray(q)
            break

    if quantiles is not None and quantiles.ndim == 2:
        step = quantiles[min(horizon_steps - 1, quantiles.shape[0] - 1)]
        call_prob = float((step > last_price).mean())
        put_prob = 1.0 - call_prob
    else:
        projected = float(median[-1])
        delta = projected - last_price
        scale = max(abs(last_price) * 1e-4, 1e-8)
        z = delta / scale
        call_prob = 1.0 / (1.0 + np.exp(-z))
        put_prob = 1.0 - call_prob

    if debug:
        print(f"TimesFM ({infer_ms} ms) last={last_price:.5f} "
              f"median_last={float(median[-1]):.5f}  "
              f"PUT={put_prob:.2f}  CALL={call_prob:.2f}")

    return {
        "put": put_prob,
        "call": call_prob,
        "forecast": median.tolist(),
        "inference_ms": infer_ms,
    }


if __name__ == "__main__":
    if "--test" in sys.argv:
        print("TimesFM 3.0 smoke test")
        _load()
        dummy = np.sin(np.linspace(0, 20, 128)).tolist()
        candles = [[0, v, v, v, v] for v in dummy]
        _ = get_signal(candles, horizon_steps=3)
        print("measuring inference latency (5 runs)...")
        times = []
        for _ in range(5):
            t0 = time.time()
            _ = get_signal(candles, horizon_steps=3)
            times.append((time.time() - t0) * 1000)
        print(f"inference: min={min(times):.0f} ms  "
              f"avg={sum(times)/len(times):.0f} ms  "
              f"max={max(times):.0f} ms")
        print("done")
    else:
        print("Run with --test, or import from the bot.")
