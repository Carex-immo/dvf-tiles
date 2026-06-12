import CoreLocation

/// Point en coordonnées tuile (origine NW, y vers le bas, échelle = extent de la couche).
struct TilePoint: Equatable, Sendable {
    var x: Int32
    var y: Int32
}

/// Coordonnée de tuile Web Mercator (z/x/y), identique au TileCoord du squelette DvfTileClient.
public struct TileCoord: Hashable, Sendable {
    public let z: Int
    public let x: Int
    public let y: Int

    public init(z: Int, x: Int, y: Int) {
        self.z = z
        self.x = x
        self.y = y
    }

    /// Point tuile -> WGS84 (inverse de la projection de bbox_to_tiles / TileMath.tiles).
    func coordinate(of p: TilePoint, extent: Int) -> CLLocationCoordinate2D {
        let n = pow(2.0, Double(z))
        let lon = (Double(x) + Double(p.x) / Double(extent)) / n * 360.0 - 180.0
        let m = Double.pi * (1.0 - 2.0 * (Double(y) + Double(p.y) / Double(extent)) / n)
        let lat = atan(sinh(m)) * 180.0 / .pi
        return CLLocationCoordinate2D(latitude: lat, longitude: lon)
    }
}
