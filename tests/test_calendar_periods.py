import datetime as dt

import numpy as np

from offside_traps_htf import period_keys


def test_week_rolls_at_monday_utc() -> None:
    times = np.array([int(dt.datetime.fromisoformat(value).timestamp()) for value in (
        "2026-10-10T23:59:59+00:00", "2026-10-11T00:00:00+00:00",
        "2026-10-11T23:59:59+00:00", "2026-10-12T00:00:00+00:00",
    )])

    keys = period_keys(times, "week")

    assert keys[0] == keys[1] == keys[2]
    assert keys[3] == keys[2] + 1
