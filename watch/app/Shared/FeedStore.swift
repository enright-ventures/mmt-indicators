import Foundation

/// Fetches the snapshot and keeps the last good one in the app group, so the app and every complication share one
/// copy and complications on the same face don't each spend a network request.
enum FeedStore {
    static let appGroup = "group.ventures.enright.swordfish"
    private static let cacheKey = "snapshot.json"
    private static let fetchedKey = "snapshot.fetchedAt"
    private static let urlKey = "feed.url"
    private static let tokenKey = "feed.token"

    static var defaults: UserDefaults { UserDefaults(suiteName: appGroup) ?? .standard }

    /// The feed URL: the one set in the app, else the build's SWORDFISH_FEED_URL.
    static var feedURL: String {
        get {
            if let saved = defaults.string(forKey: urlKey), !saved.isEmpty { return saved }
            return Bundle.main.object(forInfoDictionaryKey: "SwordfishFeedURL") as? String ?? ""
        }
        set { defaults.set(newValue.trimmingCharacters(in: .whitespacesAndNewlines), forKey: urlKey) }
    }

    static var token: String {
        get { defaults.string(forKey: tokenKey) ?? "" }
        set { defaults.set(newValue.trimmingCharacters(in: .whitespacesAndNewlines), forKey: tokenKey) }
    }

    static var cached: Snapshot? {
        guard let data = defaults.data(forKey: cacheKey) else { return nil }
        return try? Snapshot.decode(data)
    }

    static var fetchedAt: Date? {
        let t = defaults.double(forKey: fetchedKey)
        return t > 0 ? Date(timeIntervalSince1970: t) : nil
    }

    /// The cached snapshot when it was fetched within `maxAge`, else a fresh one; the cache when the network fails.
    static func snapshot(maxAge: TimeInterval = 240) async -> Snapshot? {
        if let at = fetchedAt, Date().timeIntervalSince(at) < maxAge, let snap = cached {
            return snap
        }
        do {
            return try await fetch()
        } catch {
            return cached
        }
    }

    enum FeedError: Error {
        case noURL
        case http(Int)
    }

    @discardableResult
    static func fetch() async throws -> Snapshot {
        guard let url = URL(string: feedURL), url.scheme != nil else { throw FeedError.noURL }
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 15)
        if !token.isEmpty {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        if let http = response as? HTTPURLResponse, http.statusCode != 200 {
            throw FeedError.http(http.statusCode)
        }
        let snap = try Snapshot.decode(data)
        defaults.set(data, forKey: cacheKey)
        defaults.set(Date().timeIntervalSince1970, forKey: fetchedKey)
        return snap
    }
}
