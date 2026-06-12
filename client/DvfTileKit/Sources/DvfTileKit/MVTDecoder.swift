import Foundation

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
