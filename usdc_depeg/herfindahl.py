"""Reported Number 2 — the redemption Herfindahl (concentration).

Raw HHI = ``sum_i s_i**2`` over per-wallet redemption shares ``s_i``; this is the
empirical analogue of the model's arbitrageur-concentration kappa (Derivation 3).
Also provided: the size-normalized HHI*, the top-k share, and a seeded
wallet-level bootstrap CI.
"""
import numpy as np

from constants import SEED


def _shares(volumes) -> np.ndarray:
    v = np.asarray(volumes, dtype=float)
    v = v[v > 0]
    if v.size == 0:
        raise ValueError("No positive redemption volumes.")
    return v / v.sum()


def hhi_raw(volumes) -> float:
    """Raw Herfindahl: sum of squared shares, in (0, 1]. Maps to model kappa."""
    s = _shares(volumes)
    return float(np.sum(s ** 2))


def hhi_normalized(volumes) -> float:
    """Size-normalized ``HHI* = (H - 1/N) / (1 - 1/N)``, in [0, 1].
    0 = perfectly even across N wallets, 1 = a single redeemer."""
    s = _shares(volumes)
    n = s.size
    h = float(np.sum(s ** 2))
    if n == 1:
        return 1.0
    return (h - 1.0 / n) / (1.0 - 1.0 / n)


def top_k_share(volumes, k: int = 10) -> float:
    """Share of total redemption volume held by the k largest wallets."""
    s = np.sort(_shares(volumes))[::-1]
    return float(s[:k].sum())


def bootstrap_hhi(volumes, n_boot: int = 10_000, seed: int = SEED, alpha: float = 0.05) -> dict:
    """Seeded wallet-level bootstrap CI for the raw HHI.

    Resample wallets (with their volumes) with replacement, recompute the HHI on
    each draw, and return the point estimate with a (1 - alpha) percentile CI.
    Deterministic given ``seed``.
    """
    v = np.asarray(volumes, dtype=float)
    v = v[v > 0]
    n = v.size
    point = hhi_raw(v)
    if n < 2:
        return {"hhi": point, "lo": point, "hi": point, "n_wallets": int(n)}
    rng = np.random.default_rng(seed)
    boots = np.empty(n_boot)
    for b in range(n_boot):
        sample = v[rng.integers(0, n, n)]
        sh = sample / sample.sum()
        boots[b] = np.sum(sh ** 2)
    lo, hi = np.percentile(boots, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return {"hhi": point, "lo": float(lo), "hi": float(hi),
            "n_wallets": int(n), "n_boot": n_boot, "seed": seed}
