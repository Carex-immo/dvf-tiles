import Foundation

enum ProtobufError: Error, Equatable {
    case truncated              // fin des données au milieu d'un champ
    case malformedVarint        // varint > 10 octets
    case unsupportedWireType(Int)
}

/// Lecteur protobuf minimal (wire format seul), zéro dépendance.
/// Couvre les besoins de vector_tile.proto : varint (0), 64-bit (1),
/// length-delimited (2), 32-bit (5), champs packés.
struct ProtobufReader {
    private let bytes: [UInt8]   // CoW : les sous-lecteurs partagent le buffer
    private(set) var pos: Int
    private let end: Int

    init(_ data: Data) {
        bytes = [UInt8](data)
        pos = 0
        end = bytes.count
    }

    private init(sharing bytes: [UInt8], from start: Int, to end: Int) {
        self.bytes = bytes
        self.pos = start
        self.end = end
    }

    var isAtEnd: Bool { pos >= end }

    mutating func readVarint() throws -> UInt64 {
        var result: UInt64 = 0
        var shift: UInt64 = 0
        for _ in 0..<10 {
            guard pos < end else { throw ProtobufError.truncated }
            let b = bytes[pos]
            pos += 1
            result |= UInt64(b & 0x7F) &<< shift
            if b & 0x80 == 0 { return result }
            shift += 7
        }
        throw ProtobufError.malformedVarint
    }

    mutating func readTag() throws -> (field: Int, wire: Int) {
        let v = try readVarint()
        return (Int(v >> 3), Int(v & 0x7))
    }

    /// Sous-lecteur borné sur un champ length-delimited (message imbriqué).
    mutating func readMessage() throws -> ProtobufReader {
        let raw = try readVarint()
        guard raw <= UInt64(Int.max) else { throw ProtobufError.truncated }
        let len = Int(raw)
        guard pos + len <= end else { throw ProtobufError.truncated }
        defer { pos += len }
        return ProtobufReader(sharing: bytes, from: pos, to: pos + len)
    }

    mutating func readString() throws -> String {
        let raw = try readVarint()
        guard raw <= UInt64(Int.max) else { throw ProtobufError.truncated }
        let len = Int(raw)
        guard pos + len <= end else { throw ProtobufError.truncated }
        defer { pos += len }
        return String(decoding: bytes[pos..<(pos + len)], as: UTF8.self)
    }

    mutating func readFixed64() throws -> UInt64 {
        guard pos + 8 <= end else { throw ProtobufError.truncated }
        var v: UInt64 = 0
        for i in 0..<8 { v |= UInt64(bytes[pos + i]) &<< (8 * UInt64(i)) }
        pos += 8
        return v
    }

    mutating func readFixed32() throws -> UInt32 {
        guard pos + 4 <= end else { throw ProtobufError.truncated }
        var v: UInt32 = 0
        for i in 0..<4 { v |= UInt32(bytes[pos + i]) &<< (8 * UInt32(i)) }
        pos += 4
        return v
    }

    /// Varints packés (tags et geometry de vector_tile.proto), tronqués en UInt32.
    mutating func readPackedVarints() throws -> [UInt32] {
        var sub = try readMessage()
        var out: [UInt32] = []
        while !sub.isAtEnd { out.append(UInt32(truncatingIfNeeded: try sub.readVarint())) }
        return out
    }

    mutating func skip(wire: Int) throws {
        switch wire {
        case 0: _ = try readVarint()
        case 1:
            guard pos + 8 <= end else { throw ProtobufError.truncated }
            pos += 8
        case 2:
            let raw = try readVarint()
            guard raw <= UInt64(Int.max) else { throw ProtobufError.truncated }
            let len = Int(raw)
            guard pos + len <= end else { throw ProtobufError.truncated }
            pos += len
        case 5:
            guard pos + 4 <= end else { throw ProtobufError.truncated }
            pos += 4
        default: throw ProtobufError.unsupportedWireType(wire)
        }
    }

    static func zigzagDecode(_ v: UInt32) -> Int32 {
        Int32(bitPattern: v >> 1) ^ -Int32(bitPattern: v & 1)
    }

    static func zigzagDecode64(_ v: UInt64) -> Int64 {
        Int64(bitPattern: v >> 1) ^ -Int64(bitPattern: v & 1)
    }
}
