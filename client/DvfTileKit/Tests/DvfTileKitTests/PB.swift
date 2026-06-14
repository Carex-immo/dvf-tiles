import Foundation

/// Mini-encodeur protobuf pour fabriquer des payloads de test.
enum PB {
    static func varint(_ v: UInt64) -> [UInt8] {
        var v = v
        var out: [UInt8] = []
        repeat {
            var b = UInt8(v & 0x7F)
            v >>= 7
            if v != 0 { b |= 0x80 }
            out.append(b)
        } while v != 0
        return out
    }

    static func tag(_ field: Int, _ wire: Int) -> [UInt8] { varint(UInt64(field << 3 | wire)) }
    static func varintField(_ field: Int, _ v: UInt64) -> [UInt8] { tag(field, 0) + varint(v) }
    static func lenDelim(_ field: Int, _ payload: [UInt8]) -> [UInt8] {
        tag(field, 2) + varint(UInt64(payload.count)) + payload
    }
    static func str(_ field: Int, _ s: String) -> [UInt8] { lenDelim(field, Array(s.utf8)) }
    static func packed(_ field: Int, _ vs: [UInt32]) -> [UInt8] {
        lenDelim(field, vs.flatMap { varint(UInt64($0)) })
    }
    static func zigzag(_ v: Int32) -> UInt32 { UInt32(bitPattern: (v << 1) ^ (v >> 31)) }
    static func data(_ parts: [UInt8]...) -> Data { Data(parts.flatMap(\.self)) }
}
