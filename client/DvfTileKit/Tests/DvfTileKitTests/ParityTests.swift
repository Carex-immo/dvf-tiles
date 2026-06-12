import Foundation
import Testing
@testable import DvfTileKit

/// Valeur JSON du golden (propriétés typées par mapbox_vector_tile).
enum GoldenValue: Decodable, Equatable {
    case string(String), int(Int64), double(Double), bool(Bool)

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let i = try? c.decode(Int64.self) { self = .int(i) }
        else if let d = try? c.decode(Double.self) { self = .double(d) }
        else { self = .string(try c.decode(String.self)) }
    }

    /// Égalité avec une MVTValue décodée par DvfTileKit (tolérance 1e-9 sur les doubles).
    func matches(_ v: MVTValue?) -> Bool {
        switch (self, v) {
        case (.string(let a), .string(let b)?): a == b
        case (.int(let a), .int(let b)?): a == b
        case (.double(let a), .double(let b)?): abs(a - b) < 1e-9
        case (.double(let a), .int(let b)?): a == Double(b)   // JSON 5.0 vs int MVT
        case (.bool(let a), .bool(let b)?): a == b
        default: false
        }
    }
}

struct GoldenFeature: Decodable {
    let properties: [String: GoldenValue]
    let type: String
    let coords: [Int]?
    let rings: Int?
    let vertices: Int?
}

func loadFixture(_ name: String) throws -> (mvt: Data, golden: [String: [GoldenFeature]]) {
    let mvtURL = try #require(Bundle.module.url(forResource: name, withExtension: "mvt",
                                                subdirectory: "Fixtures"))
    let jsonURL = try #require(Bundle.module.url(forResource: "\(name).expected", withExtension: "json",
                                                 subdirectory: "Fixtures"))
    return (try Data(contentsOf: mvtURL),
            try JSONDecoder().decode([String: [GoldenFeature]].self, from: Data(contentsOf: jsonURL)))
}

/// Comparaison exhaustive mais agrégée : des milliers de #expect par tuile rendraient
/// la sortie illisible — on compte les écarts et on n'affirme qu'une fois par aspect.
func mismatchedKeys(_ golden: [String: GoldenValue], _ actual: [String: MVTValue]) -> [String] {
    var bad: [String] = []
    if Set(golden.keys) != Set(actual.keys) {
        bad.append(contentsOf: Set(golden.keys).symmetricDifference(actual.keys))
    }
    for (k, gv) in golden where !gv.matches(actual[k]) { bad.append(k) }
    return bad
}

@Suite struct ParityTests {
    /// Parité brute couche mutations : comptes, propriétés, coordonnées tuile exactes.
    func checkMutationsParity(fixture: String, expectAdr: Bool) throws {
        let (mvt, golden) = try loadFixture(fixture)
        let layer = try #require(try MVTTile(mvt).layer(named: "mutations"))
        let goldenFeats = try #require(golden["mutations"])
        #expect(layer.features.count == goldenFeats.count)

        var decoded: [(id: String, props: [String: MVTValue], pt: TilePoint)] = []
        for f in layer.features {
            let props = layer.properties(of: f)
            let pt = try #require(try MVTGeometry.decodePoints(f.geometry).first)
            guard let id = props["id"]?.stringValue else { Issue.record("id manquant"); continue }
            decoded.append((id, props, pt))
        }
        decoded.sort { $0.id < $1.id }

        var propMismatches: [String] = []
        var coordMismatches: [String] = []
        for (d, g) in zip(decoded, goldenFeats) {
            let bad = mismatchedKeys(g.properties, d.props)
            if !bad.isEmpty { propMismatches.append("\(d.id): \(bad.joined(separator: ","))") }
            let coords = try #require(g.coords)
            if Int(d.pt.x) != coords[0] || Int(d.pt.y) != coords[1] { coordMismatches.append(d.id) }
        }
        #expect(propMismatches.isEmpty,
                Comment(rawValue: "\(fixture) propriétés divergentes : \(propMismatches.prefix(5))"))
        #expect(coordMismatches.isEmpty,
                Comment(rawValue: "\(fixture) coordonnées divergentes : \(coordMismatches.prefix(5))"))

        let withAdr = decoded.filter { $0.props["adr"] != nil }.count
        if expectAdr {
            #expect(withAdr > 0)              // adresse garantie z>=13
        } else {
            #expect(withAdr == 0)             // adr/cp exclus de la passe z4-12
        }
    }

    @Test func mutationsZ14() throws { try checkMutationsParity(fixture: "mutations_z14_lyon", expectAdr: true) }
    @Test func mutationsZ13() throws { try checkMutationsParity(fixture: "mutations_z13_lyon", expectAdr: true) }
    @Test func mutationsEchantillonneesZ8SansAdresse() throws {
        try checkMutationsParity(fixture: "communes_z8_lyon", expectAdr: false)
    }

    /// Parité agrégats : comptes, propriétés, invariants géométrie (anneaux, sommets).
    func checkAggregatesParity(fixture: String, layerName: String) throws {
        let (mvt, golden) = try loadFixture(fixture)
        let layer = try #require(try MVTTile(mvt).layer(named: layerName))
        let goldenFeats = try #require(golden[layerName])
        #expect(layer.features.count == goldenFeats.count)

        var decoded: [(code: String, props: [String: MVTValue], rings: [[TilePoint]])] = []
        for f in layer.features {
            let props = layer.properties(of: f)
            guard let code = props["code"]?.stringValue else { Issue.record("code manquant"); continue }
            decoded.append((code, props, try MVTGeometry.decodeRings(f.geometry)))
        }
        decoded.sort { $0.code < $1.code }

        var mismatches: [String] = []
        for (d, g) in zip(decoded, goldenFeats) {
            let bad = mismatchedKeys(g.properties, d.props)
            if !bad.isEmpty { mismatches.append("\(d.code) propriétés: \(bad.joined(separator: ","))") }
            if d.rings.count != g.rings { mismatches.append("\(d.code) anneaux: \(d.rings.count) vs \(g.rings ?? -1)") }
            let vertices = d.rings.reduce(0) { $0 + $1.count }
            if vertices != g.vertices { mismatches.append("\(d.code) sommets: \(vertices) vs \(g.vertices ?? -1)") }
        }
        #expect(mismatches.isEmpty,
                Comment(rawValue: "\(fixture)/\(layerName) écarts : \(mismatches.prefix(5))"))
    }

    @Test func communesZ8() throws { try checkAggregatesParity(fixture: "communes_z8_lyon", layerName: "communes") }
    @Test func departementsZ5() throws { try checkAggregatesParity(fixture: "departements_z5", layerName: "departements") }

    /// L'API publique de bout en bout sur une tuile réelle.
    @Test func apiPubliqueZ13() throws {
        let (mvt, golden) = try loadFixture("mutations_z13_lyon")
        let muts = try MVTDecoder.decodeMutations(mvt, tile: TileCoord(z: 13, x: 4205, y: 2922))
        #expect(muts.count == golden["mutations"]?.count)
        // tous les points retombent dans l'emprise élargie de la tuile (buffer tippecanoe inclus)
        let outOfBounds = muts.filter {
            !($0.coordinate.longitude > 4.74 && $0.coordinate.longitude < 4.90
              && $0.coordinate.latitude > 45.70 && $0.coordinate.latitude < 45.81)
        }
        #expect(outOfBounds.isEmpty, Comment(rawValue: "hors emprise : \(outOfBounds.prefix(3).map(\.id))"))
    }
}
