from math import isnan, nan

from offside_fixed import Bar, Level, find_traps


def test_confirms_after_three_hold_closes_and_includes_reclaim_flow() -> None:
    bars = [Bar(0, 102, 101, 101, 1), Bar(300, 101, 98, 99, 2, 0, 10),
            Bar(600, 102, 99, 101, 3, 0, 20)]
    bars += [Bar(t, 103, 100, 102, 1, 0, 99) for t in (900, 1200, 1500)]
    level = Level(1, 100, 1, 99999)

    events = find_traps(bars, [level])

    assert len(events) == 1
    assert events[0].index == 5
    assert events[0].flow == 30
    assert events[0].break_vwap == ((101 + 98 + 99) / 3 * 2 + (102 + 99 + 101) / 3 * 3) / 5


def test_support_cannot_trigger_failed_breakout() -> None:
    bars = [Bar(0, 99, 98, 99, 1), Bar(300, 102, 98, 99, 1)]
    bars += [Bar(t, 100, 97, 98, 1) for t in (600, 900, 1200)]

    events = find_traps(bars, [Level(1, 100, 1, 99999)])

    assert events == []


def test_resistance_triggers_failed_breakout() -> None:
    bars = [Bar(0, 99, 98, 99, 1), Bar(300, 102, 98, 99, 1, 10, 0)]
    bars += [Bar(t, 100, 97, 98, 1) for t in (600, 900, 1200)]

    events = find_traps(bars, [Level(1, 100, -1, 99999)])

    assert len(events) == 1
    assert events[0].side == -1


def test_missing_flow_preserves_pattern_without_inventing_quantity() -> None:
    bars = [Bar(0, 102, 101, 101, 1), Bar(300, 102, 98, 101, 1, 0, nan)]
    bars += [Bar(t, 103, 100, 102, 1, 0, 10) for t in (600, 900, 1200)]

    events = find_traps(bars, [Level(1, 100, 1, 99999)])

    assert len(events) == 1
    assert isnan(events[0].flow)


def test_flush_during_hold_invalidates_trap() -> None:
    bars = [Bar(0, 102, 101, 101, 1), Bar(300, 102, 98, 101, 1),
            Bar(600, 103, 97, 102, 1)]
    bars += [Bar(t, 103, 100, 102, 1) for t in (900, 1200, 1500)]

    events = find_traps(bars, [Level(1, 100, 1, 99999)])

    assert events == []


def test_expired_level_does_not_start_trap() -> None:
    bars = [Bar(0, 102, 101, 101, 1), Bar(300, 102, 98, 101, 1)]
    bars += [Bar(t, 103, 100, 102, 1) for t in (600, 900, 1200)]

    events = find_traps(bars, [Level(1, 100, 1, 300)])

    assert events == []
