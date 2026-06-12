import Foundation
import Testing
@testable import DvfTileKit

/// Couche "communes" à 1 feature polygone (extérieur + trou),
/// propriétés : code, n_tot, n_2025_t2, pm2_med (double), cx, cy.
func syntheticCommunesTile() -> Data {
    var layer: [UInt8] = []
    layer += PB.varintField(15, 2) + PB.str(1, "communes") + PB.varintField(5, 4096)
    for k in ["code", "n_tot", "n_2025_t2", "pm2_med", "cx", "cy"] { layer += PB.str(3, k) }
    func dbl(_ v: Double) -> [UInt8] {
        PB.lenDelim(4, PB.tag(3, 1) + withUnsafeBytes(of: v.bitPattern.littleEndian) { Array($0) })
    }
    layer += PB.lenDelim(4, PB.str(1, "69381"))
    layer += PB.lenDelim(4, PB.varintField(4, 1200))
    layer += PB.lenDelim(4, PB.varintField(4, 85))
    layer += dbl(4850.0) + dbl(4.83) + dbl(45.76)
    var f: [UInt8] = []
    f += PB.varintField(3, 3)   // POLYGON
    f += PB.packed(2, [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5])
    // extérieur (0,0)(10,0)(10,10)(0,10) + trou (13,13)(13,17)(17,17)(17,13).
    // Après le ClosePath de l'extérieur le curseur reste à (0,10) :
    // le MoveTo du trou est en deltas (13, 3).
    f += PB.packed(4, [9, 0, 0, 26, 20, 0, 0, 20, 19, 0, 15,
                       9, PB.zigzag(13), PB.zigzag(3), 26, 0, 8, 8, 0, 0, 7, 15])
    layer += PB.lenDelim(2, f)
    return PB.data(PB.lenDelim(3, layer))
}

@Suite struct AggregateTests {
    let tile = TileCoord(z: 8, x: 131, y: 91)

    @Test func decodeCommune() throws {
        let aggs = try MVTDecoder.decodeAggregates(syntheticCommunesTile(), layer: "communes", tile: tile)
        #expect(aggs.count == 1)
        let a = aggs[0]
        #expect(a.code == "69381")
        #expect(a.properties["n_tot"] == .int(1200))
        #expect(a.properties["n_2025_t2"] == .int(85))
        #expect(a.properties["pm2_med"] == .double(4850.0))
        #expect(a.properties["cx"] == .double(4.83))
        #expect(a.properties["cy"] == .double(45.76))
        // « polygones simples » : seuls les anneaux extérieurs sont conservés
        #expect(a.exteriorRings.count == 1)
        #expect(a.exteriorRings[0].count == 4)
    }

    @Test func coucheAbsente() throws {
        let aggs = try MVTDecoder.decodeAggregates(syntheticCommunesTile(), layer: "departements", tile: tile)
        #expect(aggs.isEmpty)
    }
}
