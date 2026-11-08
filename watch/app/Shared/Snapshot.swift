import Foundation

/// The feed's JSON (watch/server, GET /v1/snapshot). Every number can be null when the feed withheld it.
struct Snapshot: Codable, Equatable {
    var v: Int
    var asof: TimeInterval?
    var symbol: String?
    var price: Double?
    var change24hPct: Double?
    var rolling: Rolling?
    var calendar: Calendar?
    var composites: Composites?
    var flow: Flow?
    var traps: Traps?

    struct Rolling: Codable, Equatable {
        var d7: Double?
        var d30: Double?
        var d365: Double?
    }

    struct VWAP: Codable, Equatable {
        var vwap: Double
        var sd: Double
        var start: TimeInterval
    }

    struct Calendar: Codable, Equatable {
        var week: VWAP?
        var month: VWAP?
        var quarter: VWAP?
        var year: VWAP?

        enum CodingKeys: String, CodingKey {
            case week = "W", month = "M", quarter = "Q", year = "Y"
        }
    }

    struct ValueArea: Codable, Equatable {
        var vah: Double
        var poc: Double
        var val: Double
        var start: TimeInterval
        var end: TimeInterval
        var members: Int
    }

    struct Composite: Codable, Equatable {
        var c0: ValueArea?
        var c1: ValueArea?
    }

    struct Composites: Codable, Equatable {
        var daily: Composite?
        var weekly: Composite?
    }

    struct Flow: Codable, Equatable {
        var barTime: TimeInterval?
        var delta: Double?
        var volume: Double?
        var oi: Double?
        var dOi: Double?
        var plusL: Double?
        var plusS: Double?
        var formingDelta: Double?
        var formingVolume: Double?
    }

    struct Trap: Codable, Equatable {
        var level: Double
        var stop: Double
        var time: TimeInterval
        var status: String
        var ended: String?
        var breakVwap: Double?

        var isHolding: Bool { status == "holding" }
    }

    struct Traps: Codable, Equatable {
        var failedBreakdown: Trap?
        var failedBreakout: Trap?
        var support: Double?
        var resistance: Double?
    }

    static func decode(_ data: Data) throws -> Snapshot {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(Snapshot.self, from: data)
    }
}
