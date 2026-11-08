import SwiftUI
import WidgetKit

@main
struct SwordfishApp: App {
    var body: some Scene {
        WindowGroup {
            NavigationStack { DashboardView() }
        }
    }
}

/// Everything the complications summarise, plus the feed settings.
struct DashboardView: View {
    @State private var snap: Snapshot? = FeedStore.cached
    @State private var error: String?
    @State private var loading = false

    var body: some View {
        List {
            if let snap {
                let r = Readout(snap: snap)
                Section {
                    row(snap.symbol ?? "BTC", Fmt.full(snap.price), detail: Fmt.signedPct(snap.change24hPct))
                    if let asof = snap.asof {
                        Text("Updated \(Date(timeIntervalSince1970: asof), style: .relative) ago")
                            .font(.caption2).foregroundStyle(r.isStale ? .orange : .secondary)
                    }
                }
                Section("Composites") {
                    va("Daily", snap.composites?.daily?.c0)
                    va("Weekly", snap.composites?.weekly?.c0)
                }
                Section("Calendar VWAP") {
                    vwap("Week", snap.calendar?.week, r)
                    vwap("Month", snap.calendar?.month, r)
                    vwap("Quarter", snap.calendar?.quarter, r)
                    vwap("Year", snap.calendar?.year, r)
                }
                Section("Rolling VWAP") {
                    row("7D", Fmt.full(snap.rolling?.d7), detail: Fmt.signedPct(r.pct(from: snap.rolling?.d7)))
                    row("30D", Fmt.full(snap.rolling?.d30), detail: Fmt.signedPct(r.pct(from: snap.rolling?.d30)))
                    row("365D", Fmt.full(snap.rolling?.d365), detail: Fmt.signedPct(r.pct(from: snap.rolling?.d365)))
                }
                Section("Offside") {
                    trap("Failed breakdown", snap.traps?.failedBreakdown, r)
                    trap("Failed breakout", snap.traps?.failedBreakout, r)
                    row("Support", Fmt.full(snap.traps?.support))
                    row("Resistance", Fmt.full(snap.traps?.resistance))
                }
                Section {
                    row("Forming Δ", Fmt.coins(snap.flow?.formingDelta))
                    row("Last bar Δ", Fmt.coins(snap.flow?.delta))
                    row("dOI", Fmt.coins(snap.flow?.dOi))
                    row("+L / +S", "\(Fmt.coins(snap.flow?.plusL)) / \(Fmt.coins(snap.flow?.plusS))")
                } header: {
                    Text("30m flow")
                } footer: {
                    Text("Binance only. +L and +S are flow proxies, not positions.")
                }
            }
            if let error {
                Text(error).font(.caption2).foregroundStyle(.orange)
            }
            Section {
                Button(loading ? "Refreshing…" : "Refresh") { Task { await refresh() } }
                    .disabled(loading)
                NavigationLink("Feed settings") { SettingsView() }
            }
        }
        .navigationTitle("Swordfish")
        .task { await refresh() }
    }

    private func refresh() async {
        loading = true
        defer { loading = false }
        do {
            snap = try await FeedStore.fetch()
            error = nil
            WidgetCenter.shared.reloadAllTimelines()
        } catch FeedStore.FeedError.noURL {
            error = "Set the feed URL in Feed settings."
        } catch {
            self.error = "Feed unavailable: \(error.localizedDescription)"
        }
    }

    private func row(_ title: String, _ value: String, detail: String? = nil) -> some View {
        HStack {
            Text(title)
            Spacer()
            VStack(alignment: .trailing) {
                Text(value).monospacedDigit()
                if let detail { Text(detail).font(.caption2).foregroundStyle(.secondary) }
            }
        }
    }

    private func va(_ title: String, _ va: Snapshot.ValueArea?) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title + (va.map { $0.members > 1 ? " (\($0.members) merged)" : "" } ?? "")).font(.caption)
            if let va {
                Text("VAH \(Fmt.full(va.vah))").monospacedDigit()
                Text("POC \(Fmt.full(va.poc))").monospacedDigit()
                Text("VAL \(Fmt.full(va.val))").monospacedDigit()
            } else {
                Text("n/a").foregroundStyle(.secondary)
            }
        }
    }

    private func vwap(_ title: String, _ stat: Snapshot.VWAP?, _ r: Readout) -> some View {
        row(title, Fmt.full(stat?.vwap), detail: stat.map { "±\(Fmt.full($0.sd)) · \(Fmt.sigma(r.sigma($0)))" })
    }

    private func trap(_ title: String, _ trap: Snapshot.Trap?, _ r: Readout) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.caption)
            if let trap {
                Text("\(Fmt.full(trap.level)) · \(trap.isHolding ? "holding" : trap.ended ?? "ended")")
                Text("stop \(Fmt.full(trap.stop)) · \(r.age(of: trap.time)) ago").font(.caption2).foregroundStyle(.secondary)
            } else {
                Text("none in 5 days").foregroundStyle(.secondary)
            }
        }
    }
}

struct SettingsView: View {
    @State private var url = FeedStore.feedURL
    @State private var token = FeedStore.token

    var body: some View {
        Form {
            Section("Feed URL") {
                TextField("https://…/v1/snapshot", text: $url)
                    .textContentType(.URL)
            }
            Section("Token (optional)") {
                SecureField("FEED_TOKEN", text: $token)
            }
            Button("Save") {
                FeedStore.feedURL = url
                FeedStore.token = token
                WidgetCenter.shared.reloadAllTimelines()
            }
        }
        .navigationTitle("Feed")
    }
}
