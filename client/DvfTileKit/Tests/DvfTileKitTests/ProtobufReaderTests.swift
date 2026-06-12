import Foundation
import Testing
@testable import DvfTileKit

@Suite struct ProtobufReaderTests {
    @Test func varints() throws {
        var r = ProtobufReader(PB.data(PB.varint(0), PB.varint(1), PB.varint(127),
                                       PB.varint(128), PB.varint(300), PB.varint(UInt64.max)))
        #expect(try r.readVarint() == 0)
        #expect(try r.readVarint() == 1)
        #expect(try r.readVarint() == 127)
        #expect(try r.readVarint() == 128)
        #expect(try r.readVarint() == 300)
        #expect(try r.readVarint() == UInt64.max)
        #expect(r.isAtEnd)
    }

    @Test func varintTronque() {
        var r = ProtobufReader(Data([0x80]))  // continuation sans suite
        #expect(throws: ProtobufError.truncated) { _ = try r.readVarint() }
    }

    @Test func varintTropLong() {
        var r = ProtobufReader(Data(repeating: 0x80, count: 11))
        #expect(throws: ProtobufError.malformedVarint) { _ = try r.readVarint() }
    }

    @Test func zigzag() {
        #expect(ProtobufReader.zigzagDecode(0) == 0)
        #expect(ProtobufReader.zigzagDecode(1) == -1)
        #expect(ProtobufReader.zigzagDecode(2) == 1)
        #expect(ProtobufReader.zigzagDecode(4096) == 2048)
        #expect(ProtobufReader.zigzagDecode64(3) == -2)
    }

    @Test func tagEtChamps() throws {
        var r = ProtobufReader(PB.data(PB.varintField(5, 4096), PB.str(1, "mutations")))
        let t1 = try r.readTag()
        #expect(t1.field == 5 && t1.wire == 0)
        #expect(try r.readVarint() == 4096)
        let t2 = try r.readTag()
        #expect(t2.field == 1 && t2.wire == 2)
        #expect(try r.readString() == "mutations")
    }

    @Test func messageImbriqueEtSkip() throws {
        // champ 3 (message) suivi d'un champ inconnu 9 (varint) puis d'un champ 1 (string)
        var r = ProtobufReader(PB.data(
            PB.lenDelim(3, PB.varintField(1, 42)),
            PB.varintField(9, 999),
            PB.str(1, "fin")))
        let t3 = try r.readTag()
        #expect(t3.field == 3)
        var sub = try r.readMessage()
        let ts = try sub.readTag()
        #expect(ts.field == 1)
        #expect(try sub.readVarint() == 42)
        #expect(sub.isAtEnd)
        let t9 = try r.readTag()
        #expect(t9.field == 9)
        try r.skip(wire: t9.wire)
        let t1 = try r.readTag()
        #expect(t1.field == 1)
        #expect(try r.readString() == "fin")
    }

    @Test func packedVarints() throws {
        var r = ProtobufReader(PB.data(PB.packed(4, [9, 4096, 4096])))
        _ = try r.readTag()
        #expect(try r.readPackedVarints() == [9, 4096, 4096])
    }

    @Test func fixed64Double() throws {
        var bytes = PB.tag(3, 1)
        bytes += withUnsafeBytes(of: (1.5).bitPattern.littleEndian) { Array($0) }
        var r = ProtobufReader(Data(bytes))
        _ = try r.readTag()
        #expect(Double(bitPattern: try r.readFixed64()) == 1.5)
    }

    @Test func fixed32Float() throws {
        var bytes = PB.tag(2, 5)
        bytes += withUnsafeBytes(of: Float(2.5).bitPattern.littleEndian) { Array($0) }
        var r = ProtobufReader(Data(bytes))
        _ = try r.readTag()
        #expect(Float(bitPattern: try r.readFixed32()) == 2.5)
    }

    @Test func wireTypeInconnu() {
        var r = ProtobufReader(Data([0x00]))
        #expect(throws: ProtobufError.unsupportedWireType(3)) { try r.skip(wire: 3) }
    }

    @Test func longueurDemesureeNeCrashePas() {
        // varint UInt64.max comme longueur length-delimited → .truncated, pas de trap
        var r = ProtobufReader(PB.data(PB.varint(UInt64.max)))
        #expect(throws: ProtobufError.truncated) { _ = try r.readString() }
    }
}
