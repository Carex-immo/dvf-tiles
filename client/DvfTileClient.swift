// CAREX - Client de tuiles DVF pour iOS (MapKit natif) - squelette de reference
// Le decodage MVT s'appuie sur SwiftProtobuf + le schema vector_tile.proto
// (https://github.com/mapbox/vector-tile-spec) ou un binding existant.

import Foundation
import MapKit

struct Mutation: Hashable {
    let id: String
    let date: Int          // YYYYMMDD
    let annee: Int
    let nat: Int           // 1 Vente, 2 VEFA, 3 Adjudication, 4 Echange, 5 Expropriation, 6 Terrain a batir
    let type: Int          // 0 terrain, 1 maison, 2 appart, 3 dependance, 4 local
    let vf: Int            // valeur fonciere (EUR)
    let sb: Int            // surface batie (m2)
    let st: Int            // surface terrain (m2)
    let pm2: Int?          // EUR/m2 bati
    let np: Int            // pieces
    let nc: Int            // nature culture dominante
    let coordinate: CLLocationCoordinate2D

    // egalite/hash par id : cle de deduplication inter-tuiles
    // (CLLocationCoordinate2D n'est pas Hashable, pas de synthese possible)
    static func == (lhs: Mutation, rhs: Mutation) -> Bool { lhs.id == rhs.id }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }
}

struct TileCoord: Hashable { let z, x, y: Int }

enum TileMath {
    /// visibleMapRect -> tuiles couvrantes au zoom de donnees (cf. spec §4.4)
    static func tiles(for region: MKCoordinateRegion, dataZoom z: Int) -> [TileCoord] {
        func xy(_ lon: Double, _ lat: Double) -> (Int, Int) {
            let n = pow(2.0, Double(z))
            let x = Int((lon + 180) / 360 * n)
            let lr = lat * .pi / 180
            let y = Int((1 - log(tan(lr) + 1 / cos(lr)) / .pi) / 2 * n)
            return (x, y)
        }
        let (x0, y1) = xy(region.center.longitude - region.span.longitudeDelta / 2,
                          region.center.latitude  - region.span.latitudeDelta  / 2)
        let (x1, y0) = xy(region.center.longitude + region.span.longitudeDelta / 2,
                          region.center.latitude  + region.span.latitudeDelta  / 2)
        var out: [TileCoord] = []
        for x in x0...x1 { for y in y0...y1 { out.append(TileCoord(z: z, x: x, y: y)) } }
        return out
    }

    static func dataZoom(forMapZoom mapZoom: Double) -> Int { min(Int(mapZoom), 14) }
    static let maxTilesPerViewport = 16   // garde-fou (spec §4.4)
    static let exhaustiveDataZoom = 13    // tuiles mutations exhaustives des z13 (cf. build_tiles.sh -pk -pf)
}

final class DvfTileClient {
    static let baseURL = URL(string: "https://tiles.carex.immo/dvf/v1")!
    private let session: URLSession
    private var memoryCache: [TileCoord: [Mutation]] = [:]   // + cache disque conseille

    init() {
        let cfg = URLSessionConfiguration.default
        cfg.urlCache = URLCache(memoryCapacity: 32 << 20, diskCapacity: 256 << 20)
        cfg.requestCachePolicy = .useProtocolCachePolicy   // tuiles immutable -> cache HTTP efficace
        session = URLSession(configuration: cfg)
    }

    /// bbox ecran -> mutations decodees (le filtrage s'applique ensuite en memoire)
    func mutations(in region: MKCoordinateRegion, mapZoom: Double) async throws -> [Mutation] {
        guard mapZoom >= 11 else { return [] }   // sous z11 : consommer les couches agregees
        // z11-12 : points echantillonnes (affichage seul) ; comptes/medianes exacts
        // uniquement si dataZoom >= TileMath.exhaustiveDataZoom
        let z = TileMath.dataZoom(forMapZoom: mapZoom)
        let coords = Array(TileMath.tiles(for: region, dataZoom: z).prefix(TileMath.maxTilesPerViewport))
        return try await withThrowingTaskGroup(of: [Mutation].self) { group in
            for c in coords {
                group.addTask { try await self.tile(c) }
            }
            var all: [Mutation] = []
            for try await batch in group { all.append(contentsOf: batch) }
            return all
        }
    }

    private func tile(_ c: TileCoord) async throws -> [Mutation] {
        if let cached = memoryCache[c] { return cached }
        let url = Self.baseURL.appendingPathComponent("mutations/\(c.z)/\(c.x)/\(c.y).mvt")
        let (data, resp) = try await session.data(from: url)
        guard let http = resp as? HTTPURLResponse else { return [] }
        if http.statusCode == 204 { memoryCache[c] = []; return [] }   // tuile vide
        guard http.statusCode == 200 else { return [] }
        // Decoder hors main thread (spec §8) :
        let muts = try MVTDecoder.decodeMutations(data, tile: c)   // a implementer via SwiftProtobuf
        memoryCache[c] = muts
        return muts
    }
}

// Filtrage en memoire, instantane (~10 ms pour 50k objets) :
// let visibles = mutations.filter { $0.type == 2 && $0.annee >= 2024 && (2_000...8_000).contains($0.pm2 ?? 0) }
// Affichage : MKAnnotation + clusteringIdentifier pour le clustering natif.
// Tap -> id -> API CAREX dvf_get_mutation (adresse, lots, parcelles).
