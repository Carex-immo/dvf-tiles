import Foundation

public enum MVTDecoderError: Error, Equatable {
    /// La donnée commence par le magic gzip : l'appelant doit décompresser
    /// (URLSession le fait automatiquement pour Content-Encoding: gzip).
    case gzipNotDecompressed
    case malformedGeometry
}

/// Valeur de propriété MVT (vector_tile.proto Value), réduite aux types utiles :
/// float promu en double, uint/sint repliés sur int (valeurs DVF très en deçà de 2^63).
public enum MVTValue: Equatable, Sendable {
    case string(String)
    case int(Int64)
    case double(Double)
    case bool(Bool)

    public var intValue: Int64? { if case .int(let v) = self { v } else { nil } }
    public var stringValue: String? { if case .string(let v) = self { v } else { nil } }
    public var doubleValue: Double? {
        switch self {
        case .double(let v): v
        case .int(let v): Double(v)
        default: nil
        }
    }
}

enum MVTGeomType: Int, Sendable {
    case unknown = 0, point = 1, lineString = 2, polygon = 3
}

struct MVTFeature: Sendable {
    var id: UInt64?
    var tags: [UInt32] = []
    var type: MVTGeomType = .unknown
    var geometry: [UInt32] = []
}

struct MVTLayer: Sendable {
    var name = ""
    var extent = 4096
    var keys: [String] = []
    var values: [MVTValue] = []
    var features: [MVTFeature] = []

    /// tags = paires (index clé, index valeur).
    func properties(of feature: MVTFeature) -> [String: MVTValue] {
        var props: [String: MVTValue] = [:]
        props.reserveCapacity(feature.tags.count / 2)
        var i = 0
        while i + 1 < feature.tags.count {
            let k = Int(feature.tags[i]), v = Int(feature.tags[i + 1])
            if k < keys.count, v < values.count { props[keys[k]] = values[v] }
            i += 2
        }
        return props
    }
}

struct MVTTile: Sendable {
    var layers: [MVTLayer] = []

    init(_ data: Data) throws {
        if data.count >= 2, data[data.startIndex] == 0x1F, data[data.startIndex + 1] == 0x8B {
            throw MVTDecoderError.gzipNotDecompressed
        }
        var r = ProtobufReader(data)
        while !r.isAtEnd {
            let (field, wire) = try r.readTag()
            if field == 3, wire == 2 {
                layers.append(try Self.parseLayer(&r))
            } else {
                try r.skip(wire: wire)
            }
        }
    }

    func layer(named name: String) -> MVTLayer? { layers.first { $0.name == name } }

    private static func parseLayer(_ r: inout ProtobufReader) throws -> MVTLayer {
        var sub = try r.readMessage()
        var layer = MVTLayer()
        while !sub.isAtEnd {
            let (field, wire) = try sub.readTag()
            switch (field, wire) {
            case (1, 2): layer.name = try sub.readString()
            case (2, 2): layer.features.append(try parseFeature(&sub))
            case (3, 2): layer.keys.append(try sub.readString())
            case (4, 2): layer.values.append(try parseValue(&sub))
            case (5, 0):
                let raw = try sub.readVarint()
                layer.extent = raw <= UInt64(Int.max) ? Int(raw) : 4096
            default: try sub.skip(wire: wire)
            }
        }
        return layer
    }

    private static func parseFeature(_ r: inout ProtobufReader) throws -> MVTFeature {
        var sub = try r.readMessage()
        var f = MVTFeature()
        while !sub.isAtEnd {
            let (field, wire) = try sub.readTag()
            switch (field, wire) {
            case (1, 0): f.id = try sub.readVarint()
            case (2, 2): f.tags = try sub.readPackedVarints()
            case (3, 0):
                let raw = try sub.readVarint()
                f.type = raw <= 3 ? (MVTGeomType(rawValue: Int(raw)) ?? .unknown) : .unknown
            case (4, 2): f.geometry = try sub.readPackedVarints()
            default: try sub.skip(wire: wire)
            }
        }
        return f
    }

    private static func parseValue(_ r: inout ProtobufReader) throws -> MVTValue {
        var sub = try r.readMessage()
        var value = MVTValue.string("")
        while !sub.isAtEnd {
            let (field, wire) = try sub.readTag()
            switch (field, wire) {
            case (1, 2): value = .string(try sub.readString())
            case (2, 5): value = .double(Double(Float(bitPattern: try sub.readFixed32())))
            case (3, 1): value = .double(Double(bitPattern: try sub.readFixed64()))
            case (4, 0): value = .int(Int64(bitPattern: try sub.readVarint()))
            case (5, 0): value = .int(Int64(bitPattern: try sub.readVarint()))
            case (6, 0): value = .int(ProtobufReader.zigzagDecode64(try sub.readVarint()))
            case (7, 0): value = .bool(try sub.readVarint() != 0)
            default: try sub.skip(wire: wire)
            }
        }
        return value
    }
}
