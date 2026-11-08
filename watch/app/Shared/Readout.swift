import Foundation

/// What the complications say, derived from a snapshot. Kept free of SwiftUI so it reads the same everywhere.
struct Readout {
    let snap: Snapshot
    var now: Date = Date()

    var price: Double? { snap.price }

    /// Older than an hour: the feed or the watch has stopped refreshing, so the faces dim.
    var isStale: Bool {
        guard let asof = snap.asof else { return true }
        return now.timeIntervalSince1970 - asof > 3600
    }

    // MARK: value areas

    enum Position {
        case above(Double), inside(poc: Double), below(Double)
    }

    func position(in va: Snapshot.ValueArea?) -> Position? {
        guard let va, let price else { return nil }
        if price > va.vah { return .above(va.vah) }
        if price < va.val { return .below(va.val) }
        return .inside(poc: va.poc)
    }

    func positionText(_ label: String, _ va: Snapshot.ValueArea?) -> String? {
        switch position(in: va) {
        case .above(let vah): return "\(label) above VAH \(Fmt.k(vah))"
        case .below(let val): return "\(label) below VAL \(Fmt.k(val))"
        case .inside(let poc): return "\(label) in value · POC \(Fmt.k(poc))"
        case nil: return nil
        }
    }

    var dailyVA: Snapshot.ValueArea? { snap.composites?.daily?.c0 }
    var weeklyVA: Snapshot.ValueArea? { snap.composites?.weekly?.c0 }

    // MARK: VWAPs

    /// Price against the current week's VWAP in standard deviations.
    var weeklySigma: Double? { sigma(snap.calendar?.week) }
    var monthlySigma: Double? { sigma(snap.calendar?.month) }

    func sigma(_ stat: Snapshot.VWAP?) -> Double? {
        guard let stat, let price, stat.sd > 0 else { return nil }
        return (price - stat.vwap) / stat.sd
    }

    func pct(from level: Double?) -> Double? {
        guard let level, let price, level > 0 else { return nil }
        return (price / level - 1) * 100
    }

    // MARK: flow

    /// The forming 30m bar's delta as a share of its volume, -1 (all selling) to +1 (all buying).
    var deltaShare: Double? {
        guard let d = snap.flow?.formingDelta, let v = snap.flow?.formingVolume, v > 0 else { return nil }
        return max(-1, min(1, d / v))
    }

    // MARK: traps

    enum TrapSide { case breakdown, breakout }

    struct ActiveTrap {
        let side: TrapSide
        let trap: Snapshot.Trap
    }

    /// The newest holding trap, else the newest trap of either side.
    var trap: ActiveTrap? {
        let all = [snap.traps?.failedBreakdown.map { ActiveTrap(side: .breakdown, trap: $0) },
                   snap.traps?.failedBreakout.map { ActiveTrap(side: .breakout, trap: $0) }].compactMap { $0 }
        let holding = all.filter(\.trap.isHolding)
        return (holding.isEmpty ? all : holding).max { $0.trap.time < $1.trap.time }
    }

    func age(of time: TimeInterval) -> String {
        let minutes = max(0, Int((now.timeIntervalSince1970 - time) / 60))
        if minutes < 60 { return "\(minutes)m" }
        if minutes < 48 * 60 { return "\(minutes / 60)h" }
        return "\(minutes / 1440)d"
    }
}

enum Fmt {
    /// 81,234 -> "81.2k"; below 10,000 the plain number.
    static func k(_ value: Double?) -> String {
        guard let value, value.isFinite else { return "--" }
        if abs(value) >= 10_000 { return String(format: "%.1fk", value / 1000) }
        if abs(value) >= 100 { return String(format: "%.0f", value) }
        return String(format: "%.2f", value)
    }

    /// Whole price with thousands separators, as the chart captions write levels.
    static func full(_ value: Double?) -> String {
        guard let value, value.isFinite else { return "--" }
        let f = NumberFormatter()
        f.numberStyle = .decimal
        f.maximumFractionDigits = value >= 1000 ? 0 : 2
        return f.string(from: NSNumber(value: value)) ?? "--"
    }

    static func signedPct(_ value: Double?, digits: Int = 1) -> String {
        guard let value, value.isFinite else { return "--" }
        return String(format: "%+.\(digits)f%%", value)
    }

    static func sigma(_ value: Double?) -> String {
        guard let value, value.isFinite else { return "--" }
        return String(format: "%+.1fσ", value)
    }

    /// Coins: "+340", "-1.2k".
    static func coins(_ value: Double?) -> String {
        guard let value, value.isFinite else { return "--" }
        if abs(value) >= 1000 { return String(format: "%+.1fk", value / 1000) }
        return String(format: "%+.0f", value)
    }
}
