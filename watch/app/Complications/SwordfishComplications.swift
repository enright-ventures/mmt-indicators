import SwiftUI
import WidgetKit

// Complications for Modular Ultra (and any face with the same slot shapes):
//   centre slot (rectangular): Levels or Trap
//   round slots (circular):    Trap, Delta, Weekly VWAP, Price
//   corner / inline slots:     Delta, Weekly VWAP, Price; Levels inline
// They share one snapshot from FeedStore. WidgetKit spends a refresh budget per complication, so timelines ask to
// reload every 15 minutes and reuse a snapshot fetched in the last four by another complication.

@main
struct SwordfishComplications: WidgetBundle {
    var body: some Widget {
        LevelsWidget()
        TrapWidget()
        DeltaWidget()
        VWAPWidget()
        PriceWidget()
    }
}

// MARK: timeline

struct SnapEntry: TimelineEntry {
    let date: Date
    let snap: Snapshot?

    var readout: Readout? { snap.map { Readout(snap: $0, now: date) } }
}

struct SnapProvider: TimelineProvider {
    func placeholder(in context: Context) -> SnapEntry {
        SnapEntry(date: .now, snap: .sample)
    }

    func getSnapshot(in context: Context, completion: @escaping (SnapEntry) -> Void) {
        if context.isPreview {
            completion(SnapEntry(date: .now, snap: FeedStore.cached ?? .sample))
            return
        }
        Task { completion(SnapEntry(date: .now, snap: await FeedStore.snapshot())) }
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<SnapEntry>) -> Void) {
        Task {
            let snap = await FeedStore.snapshot()
            let now = Date()
            // A second entry a little later keeps the trap age and staleness honest between reloads.
            let entries = [SnapEntry(date: now, snap: snap), SnapEntry(date: now.addingTimeInterval(10 * 60), snap: snap)]
            completion(Timeline(entries: entries, policy: .after(now.addingTimeInterval(15 * 60))))
        }
    }
}

// MARK: shared bits

let bullish = Color(red: 92 / 255, green: 156 / 255, blue: 255 / 255)   // Swordfish buying / trapped shorts
let bearish = Color(red: 255 / 255, green: 92 / 255, blue: 102 / 255)   // Swordfish selling / trapped longs

struct NoData: View {
    @Environment(\.widgetFamily) private var family

    var body: some View {
        switch family {
        case .accessoryRectangular:
            VStack(alignment: .leading) {
                Text("Swordfish").font(.headline).widgetAccentable()
                Text("No feed yet").foregroundStyle(.secondary)
                Text("Open the app to set it up").font(.caption2).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        case .accessoryInline:
            Text("Swordfish: no feed")
        default:
            Image(systemName: "fish").font(.title3)
        }
    }
}

extension View {
    func staleness(_ readout: Readout) -> some View {
        opacity(readout.isStale ? 0.45 : 1)
    }

    func complicationBackground() -> some View {
        containerBackground(.fill.tertiary, for: .widget)
    }
}

// MARK: Levels (rectangular, inline)

struct LevelsWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "levels", provider: SnapProvider()) { entry in
            LevelsView(entry: entry).complicationBackground()
        }
        .configurationDisplayName("Swordfish Levels")
        .description("Price against the daily composite value area, the weekly VWAP and the nearest 4h swings.")
        .supportedFamilies([.accessoryRectangular, .accessoryInline])
    }
}

struct LevelsView: View {
    let entry: SnapEntry
    @Environment(\.widgetFamily) private var family

    var body: some View {
        if let r = entry.readout {
            switch family {
            case .accessoryInline:
                Text("\(r.snap.symbol ?? "BTC") \(Fmt.k(r.price)) · \(inlinePosition(r))")
            default:
                VStack(alignment: .leading, spacing: 1) {
                    HStack(alignment: .firstTextBaseline) {
                        Text("\(r.snap.symbol ?? "BTC") \(Fmt.k(r.price))").font(.headline).widgetAccentable()
                        Spacer(minLength: 2)
                        Text(Fmt.signedPct(r.snap.change24hPct))
                            .font(.caption).foregroundStyle((r.snap.change24hPct ?? 0) >= 0 ? bullish : bearish)
                    }
                    Text(r.positionText("D", r.dailyVA) ?? r.positionText("W", r.weeklyVA) ?? "Composites n/a")
                        .font(.caption)
                    Text(vwapLine(r)).font(.caption2).foregroundStyle(.secondary)
                }
                .lineLimit(1)
                .minimumScaleFactor(0.75)
                .frame(maxWidth: .infinity, alignment: .leading)
                .staleness(r)
            }
        } else {
            NoData()
        }
    }

    private func inlinePosition(_ r: Readout) -> String {
        switch r.position(in: r.dailyVA) {
        case .above: return "above D VAH"
        case .below: return "below D VAL"
        case .inside: return "in D value"
        case nil: return Fmt.sigma(r.weeklySigma) + " W"
        }
    }

    private func vwapLine(_ r: Readout) -> String {
        var parts = ["W \(Fmt.sigma(r.weeklySigma))"]
        if let s = r.snap.traps?.support { parts.append("S \(Fmt.k(s))") }
        if let res = r.snap.traps?.resistance { parts.append("R \(Fmt.k(res))") }
        return parts.joined(separator: " · ")
    }
}

// MARK: Trap (rectangular, circular, corner)

struct TrapWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "trap", provider: SnapProvider()) { entry in
            TrapView(entry: entry).complicationBackground()
        }
        .configurationDisplayName("Swordfish Offside")
        .description("The newest failed breakdown or breakout on 4h swing levels, and whether it is holding.")
        .supportedFamilies([.accessoryRectangular, .accessoryCircular, .accessoryCorner])
    }
}

struct TrapView: View {
    let entry: SnapEntry
    @Environment(\.widgetFamily) private var family

    var body: some View {
        if let r = entry.readout {
            content(r).staleness(r)
        } else {
            NoData()
        }
    }

    @ViewBuilder
    private func content(_ r: Readout) -> some View {
        let active = r.trap
        let color = active.map { $0.side == .breakdown ? bullish : bearish } ?? .secondary
        let arrow = active.map { $0.side == .breakdown ? "arrow.up.circle.fill" : "arrow.down.circle.fill" } ?? "circle.dashed"
        switch family {
        case .accessoryCircular:
            VStack(spacing: 0) {
                Image(systemName: arrow).font(.title3).foregroundStyle(color).widgetAccentable()
                Text(active.map { Fmt.k($0.trap.level) } ?? "none").font(.caption2).minimumScaleFactor(0.6)
                if let active { Text(active.trap.isHolding ? "HOLD" : "END").font(.system(size: 8, weight: .bold)) }
            }
        case .accessoryCorner:
            Image(systemName: arrow).font(.title2).foregroundStyle(color).widgetAccentable()
                .widgetLabel(active.map { "\($0.trap.isHolding ? "Holding" : "Ended") \(Fmt.k($0.trap.level))" } ?? "No trap")
        default:
            VStack(alignment: .leading, spacing: 1) {
                if let active {
                    HStack(spacing: 4) {
                        Image(systemName: arrow).foregroundStyle(color)
                        Text(active.side == .breakdown ? "Failed breakdown" : "Failed breakout").font(.headline)
                    }
                    .widgetAccentable()
                    Text("\(Fmt.full(active.trap.level)) · \(active.trap.isHolding ? "holding" : active.trap.ended ?? "ended")")
                        .font(.caption)
                    Text("stop \(Fmt.full(active.trap.stop)) · \(r.age(of: active.trap.time)) ago")
                        .font(.caption2).foregroundStyle(.secondary)
                } else {
                    Text("No trap").font(.headline).widgetAccentable()
                    Text("watching 4h swings").font(.caption)
                    Text("S \(Fmt.k(r.snap.traps?.support)) · R \(Fmt.k(r.snap.traps?.resistance))")
                        .font(.caption2).foregroundStyle(.secondary)
                }
            }
            .lineLimit(1)
            .minimumScaleFactor(0.75)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

// MARK: Delta (circular, corner)

struct DeltaWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "delta", provider: SnapProvider()) { entry in
            DeltaView(entry: entry).complicationBackground()
        }
        .configurationDisplayName("Swordfish Delta")
        .description("The forming 30m bar's net taker buying or selling as a share of its volume (Binance).")
        .supportedFamilies([.accessoryCircular, .accessoryCorner])
    }
}

struct DeltaView: View {
    let entry: SnapEntry
    @Environment(\.widgetFamily) private var family

    var body: some View {
        if let r = entry.readout, let share = r.deltaShare {
            let color = share >= 0 ? bullish : bearish
            let text = String(format: "%+.0f", share * 100)
            switch family {
            case .accessoryCorner:
                Text(text + "%").font(.title3).foregroundStyle(color).widgetAccentable()
                    .widgetLabel {
                        Gauge(value: share, in: -1...1) { Text("Δ") }
                            .tint(Gradient(colors: [bearish, .gray, bullish]))
                    }
                    .staleness(r)
            default:
                Gauge(value: share, in: -1...1) {
                    Text("Δ")
                } currentValueLabel: {
                    Text(text).foregroundStyle(color)
                }
                .gaugeStyle(.accessoryCircular)
                .tint(Gradient(colors: [bearish, .gray, bullish]))
                .widgetAccentable()
                .staleness(r)
            }
        } else {
            NoData()
        }
    }
}

// MARK: Weekly VWAP (circular, corner)

struct VWAPWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "vwap", provider: SnapProvider()) { entry in
            VWAPView(entry: entry).complicationBackground()
        }
        .configurationDisplayName("Swordfish Weekly VWAP")
        .description("Price against this week's pooled VWAP, in standard deviations.")
        .supportedFamilies([.accessoryCircular, .accessoryCorner])
    }
}

struct VWAPView: View {
    let entry: SnapEntry
    @Environment(\.widgetFamily) private var family

    var body: some View {
        if let r = entry.readout, let s = r.weeklySigma {
            let clamped = max(-2, min(2, s))
            switch family {
            case .accessoryCorner:
                Text(Fmt.sigma(s)).font(.title3).widgetAccentable()
                    .widgetLabel {
                        Gauge(value: clamped, in: -2...2) { Text("W") }
                            .tint(Gradient(colors: [bearish, .gray, bullish]))
                    }
                    .staleness(r)
            default:
                Gauge(value: clamped, in: -2...2) {
                    Text("W")
                } currentValueLabel: {
                    Text(String(format: "%+.1f", s))
                } minimumValueLabel: {
                    Text("-2")
                } maximumValueLabel: {
                    Text("+2")
                }
                .gaugeStyle(.accessoryCircular)
                .tint(Gradient(colors: [bearish, .gray, bullish]))
                .widgetAccentable()
                .staleness(r)
            }
        } else {
            NoData()
        }
    }
}

// MARK: Price (circular, corner, inline)

struct PriceWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "price", provider: SnapProvider()) { entry in
            PriceView(entry: entry).complicationBackground()
        }
        .configurationDisplayName("Swordfish Price")
        .description("Last price and 24h change, with a ring for price inside the daily composite value area.")
        .supportedFamilies([.accessoryCircular, .accessoryCorner, .accessoryInline])
    }
}

struct PriceView: View {
    let entry: SnapEntry
    @Environment(\.widgetFamily) private var family

    var body: some View {
        if let r = entry.readout, let price = r.price {
            let up = (r.snap.change24hPct ?? 0) >= 0
            switch family {
            case .accessoryInline:
                Text("\(r.snap.symbol ?? "BTC") \(Fmt.k(price)) \(Fmt.signedPct(r.snap.change24hPct))")
            case .accessoryCorner:
                Text(Fmt.k(price)).font(.title3).widgetAccentable()
                    .widgetLabel(Fmt.signedPct(r.snap.change24hPct))
                    .staleness(r)
            default:
                // The ring places price between the daily composite's VAL (left) and VAH (right).
                let va = r.dailyVA
                Gauge(value: price, in: (va?.val ?? price - 1)...(max(va?.vah ?? price + 1, (va?.val ?? price - 1) + 1))) {
                    Text(r.snap.symbol ?? "BTC")
                } currentValueLabel: {
                    Text(Fmt.k(price)).minimumScaleFactor(0.6)
                }
                .gaugeStyle(.accessoryCircular)
                .tint(up ? bullish : bearish)
                .widgetAccentable()
                .staleness(r)
            }
        } else {
            NoData()
        }
    }
}

// MARK: preview data

extension Snapshot {
    static let sample = Snapshot(
        v: 1, asof: Date().timeIntervalSince1970, symbol: "BTC", price: 81_234, change24hPct: 1.4,
        rolling: .init(d7: 80_100, d30: 78_900, d365: 71_500),
        calendar: .init(week: .init(vwap: 80_600, sd: 900, start: 0), month: .init(vwap: 79_800, sd: 1_800, start: 0),
                        quarter: .init(vwap: 76_000, sd: 4_100, start: 0), year: .init(vwap: 72_000, sd: 9_000, start: 0)),
        composites: .init(daily: .init(c0: .init(vah: 80_900, poc: 80_200, val: 79_400, start: 0, end: 0, members: 2), c1: nil),
                          weekly: .init(c0: .init(vah: 82_500, poc: 79_900, val: 77_300, start: 0, end: 0, members: 1), c1: nil)),
        flow: .init(barTime: nil, delta: 120, volume: 2_400, oi: 82_000, dOi: 40, plusL: 80, plusS: -40,
                    formingDelta: 85, formingVolume: 700),
        traps: .init(failedBreakdown: .init(level: 80_345, stop: 79_980, time: Date().timeIntervalSince1970 - 7_200,
                                            status: "holding", ended: nil, breakVwap: 80_210),
                     failedBreakout: nil, support: 79_400, resistance: 83_050))
}
