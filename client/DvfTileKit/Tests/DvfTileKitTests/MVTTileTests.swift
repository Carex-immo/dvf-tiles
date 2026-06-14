import Foundation
import Testing
@testable import DvfTileKit

/// Construit une couche "mutations" synthétique à 1 feature point :
/// keys [id, date, vf, cx, ok], values ["2024-1", 20240315, -42 (sint), 4.83 (double), true]
/// tags [0,0, 1,1, 2,2, 3,3, 4,4], geometry MoveTo(2048, 2048).
func syntheticTile(layerName: String = "mutations", extent: UInt64 = 4096) -> Data {
    var layer: [UInt8] = []
    layer += PB.varintField(15, 2)                 // version
    layer += PB.str(1, layerName)                  // name
    layer += PB.varintField(5, extent)             // extent
    layer += PB.str(3, "id") + PB.str(3, "date") + PB.str(3, "vf") + PB.str(3, "cx") + PB.str(3, "ok")
    layer += PB.lenDelim(4, PB.str(1, "2024-1"))                       // value string
    layer += PB.lenDelim(4, PB.varintField(4, 20240315))               // value int64
    layer += PB.lenDelim(4, PB.varintField(6, UInt64(PB.zigzag(-42)))) // value sint64
    layer += PB.lenDelim(4, PB.tag(3, 1) + withUnsafeBytes(of: (4.83).bitPattern.littleEndian) { Array($0) }) // double
    layer += PB.lenDelim(4, PB.varintField(7, 1))                      // value bool
    var feature: [UInt8] = []
    feature += PB.varintField(3, 1)                                    // type POINT
    feature += PB.packed(2, [0, 0, 1, 1, 2, 2, 3, 3, 4, 4])            // tags
    feature += PB.packed(4, [9, PB.zigzag(2048), PB.zigzag(2048)])     // MoveTo(2048,2048)
    layer += PB.lenDelim(2, feature)
    return PB.data(PB.lenDelim(3, layer))
}

@Suite struct MVTTileTests {
    @Test func parseTuileSynthetique() throws {
        let tile = try MVTTile(syntheticTile())
        #expect(tile.layers.count == 1)
        let layer = try #require(tile.layer(named: "mutations"))
        #expect(layer.extent == 4096)
        #expect(layer.keys == ["id", "date", "vf", "cx", "ok"])
        #expect(layer.features.count == 1)
        let f = layer.features[0]
        #expect(f.type == .point)
        let props = layer.properties(of: f)
        #expect(props["id"] == .string("2024-1"))
        #expect(props["date"] == .int(20240315))
        #expect(props["vf"] == .int(-42))
        #expect(props["cx"] == .double(4.83))
        #expect(props["ok"] == .bool(true))
    }

    @Test func coucheAbsente() throws {
        let tile = try MVTTile(syntheticTile(layerName: "communes"))
        #expect(tile.layer(named: "mutations") == nil)
    }

    @Test func gardeGzip() {
        let gz = Data([0x1F, 0x8B, 0x08, 0x00])
        #expect(throws: MVTDecoderError.gzipNotDecompressed) { _ = try MVTTile(gz) }
    }

    @Test func champsInconnusIgnores() throws {
        // un champ inconnu (99, varint) avant la couche ne doit pas gêner
        var bytes = PB.varintField(99, 7)
        bytes += [UInt8](syntheticTile())
        let tile = try MVTTile(Data(bytes))
        #expect(tile.layers.count == 1)
    }
}
