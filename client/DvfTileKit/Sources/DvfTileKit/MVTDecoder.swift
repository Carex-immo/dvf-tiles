import CoreLocation
import Foundation

/// Entité agrégée (commune ou département) : code INSEE, propriétés brutes
/// (clés n_{annee}_t{type} / p_{annee}_t{type} / n_tot / pm2_med / vf_med / cx / cy),
/// anneaux extérieurs en WGS84 (« polygones simples » du contrat — trous ignorés).
public struct AggregateFeature: Sendable {
    public let code: String
    public let properties: [String: MVTValue]
    public let exteriorRings: [[CLLocationCoordinate2D]]

    public init(code: String, properties: [String: MVTValue], exteriorRings: [[CLLocationCoordinate2D]]) {
        self.code = code
        self.properties = properties
        self.exteriorRings = exteriorRings
    }
}

public enum MVTDecoder {
    /// Couche `mutations` -> [Mutation]. `data` doit être le MVT décompressé
    /// (URLSession décompresse Content-Encoding: gzip automatiquement ;
    /// une donnée encore gzippée lève .gzipNotDecompressed).
    /// Une feature hors contrat (champ requis manquant, géométrie non-point)
    /// est ignorée — la QA du pipeline garantit qu'il n'y en a pas.
    public static func decodeMutations(_ data: Data, tile: TileCoord) throws -> [Mutation] {
        guard let layer = try MVTTile(data).layer(named: "mutations") else { return [] }
        var out: [Mutation] = []
        out.reserveCapacity(layer.features.count)
        for f in layer.features where f.type == .point {
            let props = layer.properties(of: f)
            guard let pt = try MVTGeometry.decodePoints(f.geometry).first,
                  let id = props["id"]?.stringValue,
                  let date = props["date"]?.intValue,
                  let nat = props["nat"]?.intValue,
                  let type_ = props["type"]?.intValue,
                  let sb = props["sb"]?.intValue,
                  let st = props["st"]?.intValue,
                  let np = props["np"]?.intValue,
                  let nl = props["nl"]?.intValue,
                  let com = props["com"]?.stringValue
            else { continue }
            out.append(Mutation(
                id: id,
                date: Int(date),
                nat: Int(nat),
                type: Int(type_),
                vf: props["vf"]?.intValue.map(Int.init),
                sb: Int(sb),
                st: Int(st),
                np: Int(np),
                nl: Int(nl),
                com: com,
                adr: props["adr"]?.stringValue,
                cp: props["cp"]?.stringValue,
                coordinate: tile.coordinate(of: pt, extent: layer.extent)))
        }
        return out
    }
}

extension MVTDecoder {
    public static func decodeAggregates(_ data: Data, layer name: String, tile: TileCoord) throws -> [AggregateFeature] {
        guard let layer = try MVTTile(data).layer(named: name) else { return [] }
        var out: [AggregateFeature] = []
        out.reserveCapacity(layer.features.count)
        for f in layer.features where f.type == .polygon {
            let props = layer.properties(of: f)
            guard let code = props["code"]?.stringValue else { continue }
            let rings = try MVTGeometry.decodeRings(f.geometry)
            let exteriors = rings
                .filter { MVTGeometry.signedArea($0) > 0 }
                .map { ring in ring.map { tile.coordinate(of: $0, extent: layer.extent) } }
            out.append(AggregateFeature(code: code, properties: props, exteriorRings: exteriors))
        }
        return out
    }
}
