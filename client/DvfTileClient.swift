// CAREX - Reference d'encodage des tuiles DVF cote Swift.
// Le struct Mutation ci-dessous est la declaration canonique de l'encodage
// (verrouillee par tests/test_tile_encoding_contract.py). L'app iOS rend les
// tuiles via MapLibreGL ; le TileMath/fetch MapKit plus bas reste un squelette
// illustratif. Le decodage MVT est fourni par DvfTileKit (`swift test`).

import Foundation
import MapKit

// Schema contractuel (spec 2026-06-12, parite goldens carex.immo) :
// codes de l'app, annee/pm2 derives, adresse garantie a z>=13 seulement.
struct Mutation: Hashable {
    let id: String
    let date: Int          // YYYYMMDD (annee = date / 10000)
    let nat: Int           // 1 Vente, 2 VEFA, 3 Adjudication, 4 Echange, 5 Expropriation (jamais 0)
    let type: Int          // 1 maison, 2 appartement, 3 immeuble, 4 local, 5 dependance
                           // (terrain nu : exclu de la couche points)
    let vf: Int?           // valeur fonciere (EUR) - omise si absente ; pm2 = vf/sb si les deux > 0
    let sb: Int            // surface batie (m2, biens post-fusion hors dependances)
    let st: Int            // surface terrain (m2, max par parcelle somme)
    let np: Int            // pieces (somme des biens)
    let nl: Int            // nb de biens post-fusion (detection multi-lots)
    let com: String        // code commune INSEE (COG courant) - nom/adresseComplete via table COG
    let adr: String?       // "numero suffixe voie", casse source - PRESENTE A z>=13 UNIQUEMENT
    let cp: String?        // code postal - PRESENT A z>=13 UNIQUEMENT
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
    // Placeholder POC, jamais deploye — cible reelle (contrat 2026-06-11) :
    // tuiles a plat Supabase Storage {version}/tiles/{z}/{x}/{y}.pbf
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

// Filtrage en memoire, instantane (~10 ms pour 50k objets) ; derives :
// annee = date / 10000 ; pm2 = (vf et sb > 0) ? vf / sb : nil
// let visibles = mutations.filter { $0.type == 2 && $0.date / 10000 >= 2024 }
// Affichage : MKAnnotation + clusteringIdentifier pour le clustering natif.
// Liste (z>=13) : adr + cp + nom de commune via table COG (cle com).
// Tap -> id -> API CAREX dvf_get_mutation (lots, biens, parcelles : le detail).
