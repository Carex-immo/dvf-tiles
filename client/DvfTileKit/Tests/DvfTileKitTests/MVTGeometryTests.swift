import Testing
@testable import DvfTileKit

@Suite struct MVTGeometryTests {
    @Test func pointSimple() throws {
        // Exemple spec MVT : MoveTo(25, 17) -> [9, 50, 34]
        let pts = try MVTGeometry.decodePoints([9, 50, 34])
        #expect(pts == [TilePoint(x: 25, y: 17)])
    }

    @Test func multipoint() throws {
        // Exemple spec : MoveTo(5,7), MoveTo(3,2) -> [17, 10, 14, 3, 9]
        let pts = try MVTGeometry.decodePoints([17, 10, 14, 3, 9])
        #expect(pts == [TilePoint(x: 5, y: 7), TilePoint(x: 3, y: 2)])
    }

    @Test func pointMalforme() {
        #expect(throws: MVTDecoderError.malformedGeometry) {
            _ = try MVTGeometry.decodePoints([10, 4, 4])  // LineTo dans un POINT
        }
        #expect(throws: MVTDecoderError.malformedGeometry) {
            _ = try MVTGeometry.decodePoints([9, 50])     // paramètre manquant
        }
    }

    @Test func polygoneSimple() throws {
        // Exemple spec : (3,6)(8,12)(20,34) fermé -> [9, 6, 12, 18, 10, 12, 24, 44, 15]
        let rings = try MVTGeometry.decodeRings([9, 6, 12, 18, 10, 12, 24, 44, 15])
        #expect(rings == [[TilePoint(x: 3, y: 6), TilePoint(x: 8, y: 12), TilePoint(x: 20, y: 34)]])
    }

    @Test func multipolygoneAvecTrou() throws {
        // Exemple spec 4.3.5.7 : 2 polygones, le 2e avec un trou
        let g: [UInt32] = [9, 0, 0, 26, 20, 0, 0, 20, 19, 0, 15,
                           9, 22, 2, 26, 18, 0, 0, 18, 17, 0, 15,
                           9, 4, 13, 26, 0, 8, 8, 0, 0, 7, 15]
        let rings = try MVTGeometry.decodeRings(g)
        #expect(rings.count == 3)
        #expect(rings[0] == [TilePoint(x: 0, y: 0), TilePoint(x: 10, y: 0),
                             TilePoint(x: 10, y: 10), TilePoint(x: 0, y: 10)])
        // classification spec : aire signée (lacet, coordonnées tuile y vers le bas)
        #expect(MVTGeometry.signedArea(rings[0]) > 0)   // extérieur
        #expect(MVTGeometry.signedArea(rings[1]) > 0)   // extérieur (2e polygone)
        #expect(MVTGeometry.signedArea(rings[2]) < 0)   // trou
        // le curseur est cumulatif sur tous les anneaux — invariant subtil
        #expect(rings[1] == [TilePoint(x: 11, y: 11), TilePoint(x: 20, y: 11),
                             TilePoint(x: 20, y: 20), TilePoint(x: 11, y: 20)])
        #expect(rings[2] == [TilePoint(x: 13, y: 13), TilePoint(x: 13, y: 17),
                             TilePoint(x: 17, y: 17), TilePoint(x: 17, y: 13)])
    }

    @Test func commandeCountZero() {
        // count = 0 interdit par la spec §4.3.2 : (0 << 3) | 1 = 1
        #expect(throws: MVTDecoderError.malformedGeometry) {
            _ = try MVTGeometry.decodeRings([1])
        }
    }
}
