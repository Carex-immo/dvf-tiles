/// Décodage des commandes géométrie MVT (spec 2.1 §4.3) :
/// command integer = (count << 3) | cmd, cmd ∈ {1 MoveTo, 2 LineTo, 7 ClosePath},
/// paramètres = deltas zigzag cumulés.
enum MVTGeometry {
    private static let moveTo: UInt32 = 1
    private static let lineTo: UInt32 = 2
    private static let closePath: UInt32 = 7

    /// POINT / MULTIPOINT : uniquement des MoveTo.
    static func decodePoints(_ geometry: [UInt32]) throws -> [TilePoint] {
        var out: [TilePoint] = []
        var i = 0
        var cx: Int32 = 0, cy: Int32 = 0
        while i < geometry.count {
            let cmd = geometry[i] & 0x7
            let count = Int(geometry[i] >> 3)
            i += 1
            guard cmd == Self.moveTo, count >= 1, i + 2 * count <= geometry.count else {
                throw MVTDecoderError.malformedGeometry
            }
            for _ in 0..<count {
                cx &+= ProtobufReader.zigzagDecode(geometry[i])
                cy &+= ProtobufReader.zigzagDecode(geometry[i + 1])
                i += 2
                out.append(TilePoint(x: cx, y: cy))
            }
        }
        return out
    }

    /// POLYGON / MULTIPOLYGON : anneaux bruts (MoveTo 1, LineTo n, ClosePath),
    /// sans répéter le sommet de fermeture.
    static func decodeRings(_ geometry: [UInt32]) throws -> [[TilePoint]] {
        var rings: [[TilePoint]] = []
        var current: [TilePoint] = []
        var i = 0
        var cx: Int32 = 0, cy: Int32 = 0
        while i < geometry.count {
            let cmd = geometry[i] & 0x7
            let count = Int(geometry[i] >> 3)
            i += 1
            switch cmd {
            case Self.moveTo, Self.lineTo:
                guard count >= 1, i + 2 * count <= geometry.count else { throw MVTDecoderError.malformedGeometry }
                if cmd == Self.moveTo { current = [] }
                for _ in 0..<count {
                    cx &+= ProtobufReader.zigzagDecode(geometry[i])
                    cy &+= ProtobufReader.zigzagDecode(geometry[i + 1])
                    i += 2
                    current.append(TilePoint(x: cx, y: cy))
                }
            case Self.closePath:
                guard !current.isEmpty else { throw MVTDecoderError.malformedGeometry }
                rings.append(current)
                current = []
            default:
                throw MVTDecoderError.malformedGeometry
            }
        }
        return rings
    }

    /// Aire signée (formule du lacet) calculée directement en coordonnées tuile,
    /// convention spec MVT 2.1 : > 0 = anneau extérieur, < 0 = trou.
    static func signedArea(_ ring: [TilePoint]) -> Double {
        guard ring.count >= 3 else { return 0 }
        var sum = 0.0
        for i in 0..<ring.count {
            let a = ring[i], b = ring[(i + 1) % ring.count]
            sum += Double(a.x) * Double(b.y) - Double(b.x) * Double(a.y)
        }
        return sum / 2
    }
}
