"""Point-in-time loader package.

The only module permitted to read raw history models. Per the
import-linter contract in pyproject.toml, no other module may import
from db.models_raw directly.

Public API:
- The eleven canonical loader functions (point_in_time_methodology.md
  section 3) are exported from `point_in_time_loader`.
- Universe queries from `universe`.
- Null sentinels and the snapshot-hash helper from this module.
"""

from __future__ import annotations

# Null sentinels (point_in_time_methodology.md section 9).
# Distinguishable null cases that the Evidence Quality rubric treats
# differently. Returned alongside null values so callers can dispatch.
SENTINEL_VALUE_NULL = "value_null"
SENTINEL_NOT_YET_AVAILABLE = "not_yet_available"
SENTINEL_NOT_APPLICABLE = "not_applicable"

NULL_SENTINELS = frozenset(
    {SENTINEL_VALUE_NULL, SENTINEL_NOT_YET_AVAILABLE, SENTINEL_NOT_APPLICABLE}
)
