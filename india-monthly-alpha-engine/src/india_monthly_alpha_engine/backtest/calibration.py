"""Phase 14 calibration utilities.

- bucket_calibration: PES bucket monotonicity test per
  backtest_validity_methodology.md section 6.
- decile_monotonicity: Monthly Buy Score decile monotonicity test
  per backtest_validity_methodology.md section 10.4.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass


@dataclass(frozen=True)
class BucketCalibrationRow:
    bucket_label: str
    n: int
    mean_excess_return: float
    median_excess_return: float


@dataclass(frozen=True)
class BucketCalibrationResult:
    rows: list[BucketCalibrationRow]
    monotonic: bool
    spread_top_minus_bottom: float


# PES bucket boundaries from scoring_methodology.md section 5.3
PES_BUCKETS = ((0, 50), (50, 60), (60, 70), (70, 80), (80, 90), (90, 101))


def _bucket_label(lo: int, hi: int) -> str:
    return f"({lo},{hi}]"


def bucket_calibration(
    pes_values: list[int], forward_excess_returns: list[float]
) -> BucketCalibrationResult:
    """Group (PES, forward_excess_return) pairs by PES bucket; check monotonicity.

    Returns the per-bucket means and a monotonic flag (mean
    monotonically non-decreasing across buckets).
    """
    if len(pes_values) != len(forward_excess_returns):
        raise ValueError("input length mismatch")

    rows: list[BucketCalibrationRow] = []
    for lo, hi in PES_BUCKETS:
        members = [
            r for p, r in zip(pes_values, forward_excess_returns, strict=True) if lo <= p < hi
        ]
        if not members:
            rows.append(BucketCalibrationRow(_bucket_label(lo, hi), 0, 0.0, 0.0))
            continue
        rows.append(
            BucketCalibrationRow(
                _bucket_label(lo, hi),
                len(members),
                statistics.fmean(members),
                statistics.median(members),
            )
        )

    populated = [r for r in rows if r.n > 0]
    if len(populated) < 2:
        return BucketCalibrationResult(rows, monotonic=False, spread_top_minus_bottom=0.0)

    monotonic = all(
        populated[i].mean_excess_return >= populated[i - 1].mean_excess_return
        for i in range(1, len(populated))
    )
    spread = populated[-1].mean_excess_return - populated[0].mean_excess_return
    return BucketCalibrationResult(rows, monotonic=monotonic, spread_top_minus_bottom=spread)


@dataclass(frozen=True)
class DecileMonotonicityResult:
    decile_means: list[float]
    spearman_rho: float
    monotonic: bool


def decile_monotonicity(
    monthly_buy_scores: list[int], forward_excess_returns: list[float]
) -> DecileMonotonicityResult:
    if len(monthly_buy_scores) != len(forward_excess_returns):
        raise ValueError("input length mismatch")
    paired = sorted(
        zip(monthly_buy_scores, forward_excess_returns, strict=True), key=lambda x: x[0]
    )
    n = len(paired)
    if n < 10:
        return DecileMonotonicityResult([], 0.0, False)

    decile_size = n // 10
    decile_means: list[float] = []
    for d in range(10):
        start = d * decile_size
        end = (d + 1) * decile_size if d < 9 else n
        slice_returns = [r for _, r in paired[start:end]]
        decile_means.append(statistics.fmean(slice_returns))

    # Spearman rho: simple variant on the decile means against rank
    ranks = list(range(1, 11))
    mean_x = statistics.fmean(ranks)
    mean_y = statistics.fmean(decile_means)
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(ranks, decile_means, strict=True))
    den_x = sum((x - mean_x) ** 2 for x in ranks)
    den_y = sum((y - mean_y) ** 2 for y in decile_means)
    rho = num / ((den_x * den_y) ** 0.5) if den_x and den_y else 0.0

    monotonic = all(decile_means[i] >= decile_means[i - 1] for i in range(1, 10))
    return DecileMonotonicityResult(decile_means, rho, monotonic)
