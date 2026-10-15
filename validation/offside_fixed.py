from dataclasses import dataclass
from enum import Enum, auto
from math import isfinite, nan
from typing import assert_never


@dataclass(frozen=True, slots=True)
class Bar:
    time: int
    high: float
    low: float
    close: float
    volume: float
    long_flow: float = nan
    short_flow: float = nan


@dataclass(frozen=True, slots=True)
class Level:
    available: int
    price: float
    side: int
    expires: int


@dataclass(frozen=True, slots=True)
class Trap:
    index: int
    side: int
    level: float
    flush: float
    flow: float
    break_vwap: float


class Phase(Enum):
    WATCHING = auto()
    BROKEN = auto()
    HOLDING = auto()
    DONE = auto()


@dataclass(slots=True)
class Watch:
    """Mutable state of one fixed-side level, advanced by successive 5m bars."""

    level: Level
    phase: Phase = Phase.WATCHING
    flush: float = 0.0
    bars: int = 0
    held: int = 0
    flow: float = 0.0
    flow_ok: bool = True
    pv: float = 0.0
    volume: float = 0.0

    def add_flow(self, bar: Bar) -> None:
        value = bar.short_flow if self.level.side > 0 else bar.long_flow
        self.flow_ok = self.flow_ok and isfinite(value)
        if isfinite(value):
            self.flow += max(value, 0.0)
        self.pv += (bar.high + bar.low + bar.close) / 3 * bar.volume
        self.volume += bar.volume

    def advance(self, bar: Bar, previous: float) -> bool:
        level = self.level
        back = bar.close > level.price if level.side > 0 else bar.close < level.price
        match self.phase:
            case Phase.DONE:
                return False
            case Phase.WATCHING:
                if bar.time >= level.expires:
                    self.phase = Phase.DONE
                    return False
                breaks = (previous > level.price and bar.low < level.price * 0.9997) if level.side > 0 else (previous < level.price and bar.high > level.price * 1.0003)
                if breaks:
                    self.phase = Phase.HOLDING if back else Phase.BROKEN
                    self.flush = bar.low if level.side > 0 else bar.high
                    self.bars = 1
                    self.add_flow(bar)
            case Phase.BROKEN:
                self.bars += 1
                self.flush = min(self.flush, bar.low) if level.side > 0 else max(self.flush, bar.high)
                self.add_flow(bar)
                if back:
                    self.phase = Phase.HOLDING
                    self.held = 0
                elif self.bars > 12:
                    self.phase = Phase.DONE
            case Phase.HOLDING:
                self.bars += 1
                flushed = bar.low < self.flush if level.side > 0 else bar.high > self.flush
                if flushed or not back:
                    self.phase = Phase.BROKEN if not flushed and self.bars <= 12 else Phase.DONE
                    if self.phase is Phase.BROKEN:
                        self.add_flow(bar)
                else:
                    self.held += 1
                    if self.held >= 3:
                        self.phase = Phase.DONE
                        return True
            case unreachable:
                assert_never(unreachable)
        return False


def find_traps(bars: list[Bar], levels: list[Level]) -> list[Trap]:
    """Default MMT fixed-side rules, including slot reuse, deduplication and reclaim-bar flow."""
    ordered = sorted(levels, key=lambda level: level.available)
    watches: list[Watch] = []
    events: list[Trap] = []
    next_level = 0
    last = {1: -10**18, -1: -10**18}
    previous = 0.0
    for index, bar in enumerate(bars):
        while next_level < len(ordered) and ordered[next_level].available <= index:
            level = ordered[next_level]
            next_level += 1
            duplicate = any(w.phase is not Phase.DONE and w.level.side == level.side and abs(w.level.price / level.price - 1) < 0.0002 for w in watches)
            if duplicate:
                continue
            free = next((i for i, w in enumerate(watches) if w.phase is Phase.DONE), None)
            if free is not None:
                watches[free] = Watch(level)
            elif len(watches) < 120:
                watches.append(Watch(level))
        for watch in watches:
            if watch.advance(bar, previous) and bar.time - last[watch.level.side] >= 3600:
                last[watch.level.side] = bar.time
                price = watch.pv / watch.volume if watch.volume > 0 else watch.level.price
                events.append(Trap(index, watch.level.side, watch.level.price, watch.flush, watch.flow if watch.flow_ok else nan, price))
        previous = bar.close
    return events
