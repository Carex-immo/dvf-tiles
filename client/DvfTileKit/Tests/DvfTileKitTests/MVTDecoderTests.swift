import Foundation
import Testing
@testable import DvfTileKit

/// Couche "mutations" à 2 features :
/// - complète (12 attributs) au centre de la tuile,
/// - minimale (sans vf/adr/cp — propriétés omises, jamais de sentinelle).
func syntheticMutationsTile() -> Data {
    var layer: [UInt8] = []
    layer += PB.varintField(15, 2) + PB.str(1, "mutations") + PB.varintField(5, 4096)
    for k in ["id", "date", "nat", "type", "vf", "sb", "st", "np", "nl", "com", "adr", "cp"] {
        layer += PB.str(3, k)
    }
    func intVal(_ v: UInt64) -> [UInt8] { PB.lenDelim(4, PB.varintField(4, v)) }
    layer += PB.lenDelim(4, PB.str(1, "2024-100000"))   // 0 id
    layer += intVal(20240315)                           // 1 date
    layer += intVal(1)                                  // 2 nat
    layer += intVal(2)                                  // 3 type
    layer += intVal(250000)                             // 4 vf
    layer += intVal(65)                                 // 5 sb
    layer += intVal(0)                                  // 6 st
    layer += intVal(3)                                  // 7 np
    layer += intVal(1)                                  // 8 nl
    layer += PB.lenDelim(4, PB.str(1, "69381"))         // 9 com
    layer += PB.lenDelim(4, PB.str(1, "12 RUE DE LA RÉPUBLIQUE"))  // 10 adr
    layer += PB.lenDelim(4, PB.str(1, "69001"))         // 11 cp
    layer += PB.lenDelim(4, PB.str(1, "2024-100001"))   // 12 id 2

    var f1: [UInt8] = []
    f1 += PB.varintField(3, 1)
    f1 += PB.packed(2, [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11])
    f1 += PB.packed(4, [9, PB.zigzag(2048), PB.zigzag(2048)])
    layer += PB.lenDelim(2, f1)

    var f2: [UInt8] = []   // sans vf/adr/cp, id différent (value 12)
    f2 += PB.varintField(3, 1)
    f2 += PB.packed(2, [0, 12, 1, 1, 2, 2, 3, 3, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9])
    f2 += PB.packed(4, [9, PB.zigzag(0), PB.zigzag(0)])
    layer += PB.lenDelim(2, f2)
    return PB.data(PB.lenDelim(3, layer))
}

@Suite struct MVTDecoderTests {
    let tile = TileCoord(z: 14, x: 8411, y: 5844)

    @Test func decodeDeuxMutations() throws {
        let muts = try MVTDecoder.decodeMutations(syntheticMutationsTile(), tile: tile)
        #expect(muts.count == 2)
        let m = try #require(muts.first { $0.id == "2024-100000" })
        #expect(m.date == 20240315)
        #expect(m.nat == 1)
        #expect(m.type == 2)
        #expect(m.vf == 250000)
        #expect(m.sb == 65)
        #expect(m.st == 0)
        #expect(m.np == 3)
        #expect(m.nl == 1)
        #expect(m.com == "69381")
        #expect(m.adr == "12 RUE DE LA RÉPUBLIQUE")
        #expect(m.cp == "69001")
        // centre de la tuile témoin (valeurs Task 1)
        #expect(abs(m.coordinate.longitude - 4.822998046875) < 1e-9)
        #expect(abs(m.coordinate.latitude - 45.759858687856) < 1e-9)
    }

    @Test func proprietesOmises() throws {
        let muts = try MVTDecoder.decodeMutations(syntheticMutationsTile(), tile: tile)
        let m = try #require(muts.first { $0.id == "2024-100001" })
        #expect(m.vf == nil)
        #expect(m.adr == nil)
        #expect(m.cp == nil)
    }

    @Test func coucheMutationsAbsente() throws {
        let muts = try MVTDecoder.decodeMutations(syntheticTile(layerName: "communes"), tile: tile)
        #expect(muts.isEmpty)
    }

    @Test func dedupParId() throws {
        let muts = try MVTDecoder.decodeMutations(syntheticMutationsTile(), tile: tile)
        // égalité/hash par id (clé de dédup inter-tuiles du client)
        #expect(Set(muts).count == 2)
        #expect(Set(muts + muts).count == 2)
    }
}
