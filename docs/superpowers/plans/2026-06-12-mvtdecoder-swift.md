# MVTDecoder Swift — Plan d'implémentation (lot 0 spec aval iOS)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Livrer le décodeur MVT Swift zéro dépendance (`MVTDecoder`) attendu par `client/DvfTileClient.swift`, vérifié par parité avec `client/simulate_ios.py` sur des tuiles réelles de `build/dvf.pmtiles`.

**Architecture:** Package SwiftPM `client/DvfTileKit` (lib + tests Swift Testing). Trois couches : lecteur protobuf wire-format minimal → structures MVT (`vector_tile.proto` : Tile/Layer/Feature/Value, géométries commandes+zigzag) → API publique métier (`decodeMutations` au contrat 12 attributs, `decodeAggregates` code+propriétés+anneaux extérieurs). Fixtures = tuiles réelles extraites du PMTiles (décompressées) + goldens JSON produits par `mapbox_vector_tile` (coordonnées tuile brutes, `y_coord_down=True`).

**Tech Stack:** Swift 6.3 (SwiftPM, Swift Testing `@Test`/`#expect`), Foundation + CoreLocation uniquement (zéro dépendance — pas de SwiftProtobuf). Génération de fixtures : Python du venv (`pmtiles`, `mapbox_vector_tile` 2.2.0).

**Contexte spec :** `carex.immo/docs/specs/2026-06-12-consommation-ios-tuiles-dvf.md` (§2, §8 lot 0) + contrat `2026-06-11-tuiles-mvt-contrat-integration.md` (schéma 12 attributs). Tuiles témoins (Lyon Presqu'île, calculées le 2026-06-12 sur le build France) : `mutations` z14 (14/8411/5844, 3 061 features), z13 (13/4205/2922, 8 920), `communes` z8 (8/131/91, 1 063 + 8 055 mutations échantillonnées), `departements` z5 (5/16/11, 84 + 14 966 mutations).

**Commandes de travail :**
- Tests : `cd client/DvfTileKit && swift test` (toolchain vérifiée : Apple Swift 6.3.2, arm64-apple-macosx26.0)
- Fixtures : `source .venv/bin/activate && python3 client/DvfTileKit/generate_fixtures.py build/dvf.pmtiles`

---

## Vue des fichiers

| Fichier | Rôle |
|---|---|
| `client/DvfTileKit/Package.swift` | manifeste SwiftPM (lib `DvfTileKit` + tests, ressources Fixtures) |
| `client/DvfTileKit/Sources/DvfTileKit/ProtobufReader.swift` | wire format protobuf : varint, zigzag, tags, length-delimited, packed, fixed32/64 |
| `client/DvfTileKit/Sources/DvfTileKit/MVTTile.swift` | parsing `vector_tile.proto` : Tile → Layer (name/extent/keys/values/features) → propriétés |
| `client/DvfTileKit/Sources/DvfTileKit/MVTGeometry.swift` | commandes géométrie (MoveTo/LineTo/ClosePath), points, anneaux, aire signée |
| `client/DvfTileKit/Sources/DvfTileKit/TileCoord.swift` | coordonnée de tuile + transformation point tuile → WGS84 |
| `client/DvfTileKit/Sources/DvfTileKit/Mutation.swift` | struct `Mutation` du contrat (12 attributs, CoreLocation seulement) |
| `client/DvfTileKit/Sources/DvfTileKit/MVTDecoder.swift` | API publique : `decodeMutations`, `decodeAggregates`, erreurs |
| `client/DvfTileKit/Tests/DvfTileKitTests/*.swift` | tests unitaires + parité (un fichier par tâche) |
| `client/DvfTileKit/Tests/DvfTileKitTests/Fixtures/` | 4 tuiles `.mvt` décompressées + 4 goldens `.expected.json` (committées) |
| `client/DvfTileKit/generate_fixtures.py` | extraction des tuiles témoins + goldens depuis `build/dvf.pmtiles` |

Hors package, en fin de lot : `client/DvfTileClient.swift` (commentaire d'en-tête), `README.md`, `CLAUDE.md` (commande de test).

---

### Task 1: Squelette du package SwiftPM

**Files:**
- Create: `client/DvfTileKit/Package.swift`
- Create: `client/DvfTileKit/Sources/DvfTileKit/TileCoord.swift`
- Test: `client/DvfTileKit/Tests/DvfTileKitTests/TileCoordTests.swift`

- [ ] **Step 1: Créer le manifeste et un premier test (transformation tuile→WGS84) qui échoue**

`client/DvfTileKit/Package.swift` :

```swift
// swift-tools-version:6.0
import PackageDescription

let package = Package(
    name: "DvfTileKit",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [.library(name: "DvfTileKit", targets: ["DvfTileKit"])],
    targets: [
        .target(name: "DvfTileKit"),
        .testTarget(
            name: "DvfTileKitTests",
            dependencies: ["DvfTileKit"],
            resources: [.copy("Fixtures")]
        ),
    ]
)
```

`client/DvfTileKit/Tests/DvfTileKitTests/TileCoordTests.swift` — valeurs de référence calculées par la formule Web Mercator (mêmes constantes que `TileMath` du squelette et `bbox_to_tiles` de `simulate_ios.py`), tuile témoin z14 Lyon :

```swift
import Testing
@testable import DvfTileKit

@Suite struct TileCoordTests {
    let tile = TileCoord(z: 14, x: 8411, y: 5844)

    @Test func coinNordOuest() {
        let c = tile.coordinate(of: TilePoint(x: 0, y: 0), extent: 4096)
        #expect(abs(c.longitude - 4.812011718750) < 1e-9)
        #expect(abs(c.latitude - 45.767522962150) < 1e-9)
    }

    @Test func centre() {
        let c = tile.coordinate(of: TilePoint(x: 2048, y: 2048), extent: 4096)
        #expect(abs(c.longitude - 4.822998046875) < 1e-9)
        #expect(abs(c.latitude - 45.759858687856) < 1e-9)
    }

    @Test func coinSudEst() {
        let c = tile.coordinate(of: TilePoint(x: 4096, y: 4096), extent: 4096)
        #expect(abs(c.longitude - 4.833984375000) < 1e-9)
        #expect(abs(c.latitude - 45.752193360631) < 1e-9)
    }
}
```

Créer aussi le dossier de fixtures avec un placeholder pour que `resources:` compile : `mkdir -p client/DvfTileKit/Tests/DvfTileKitTests/Fixtures && touch client/DvfTileKit/Tests/DvfTileKitTests/Fixtures/.gitkeep`

- [ ] **Step 2: Vérifier l'échec de compilation**

Run: `cd client/DvfTileKit && swift test`
Expected: FAIL — `cannot find 'TileCoord' in scope`

- [ ] **Step 3: Implémenter `TileCoord` + `TilePoint` + transformation**

`client/DvfTileKit/Sources/DvfTileKit/TileCoord.swift` :

```swift
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
```

- [ ] **Step 4: Vérifier le passage**

Run: `cd client/DvfTileKit && swift test`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add client/DvfTileKit
git commit -m "feat(client): package SwiftPM DvfTileKit — TileCoord et transformation tuile→WGS84"
```

---

### Task 2: ProtobufReader (wire format)

**Files:**
- Create: `client/DvfTileKit/Sources/DvfTileKit/ProtobufReader.swift`
- Test: `client/DvfTileKit/Tests/DvfTileKitTests/ProtobufReaderTests.swift`
- Test (helper): `client/DvfTileKit/Tests/DvfTileKitTests/PB.swift`

- [ ] **Step 1: Écrire l'encodeur de test `PB` et les tests qui échouent**

`client/DvfTileKit/Tests/DvfTileKitTests/PB.swift` — mini-encodeur protobuf pour fabriquer des octets de test (uniquement côté tests, jamais en production) :

```swift
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
```

`client/DvfTileKit/Tests/DvfTileKitTests/ProtobufReaderTests.swift` :

```swift
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
        var sub = try { let t = try r.readTag(); #expect(t.field == 3); return try r.readMessage() }()
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
}
```

- [ ] **Step 2: Vérifier l'échec**

Run: `cd client/DvfTileKit && swift test`
Expected: FAIL — `cannot find 'ProtobufReader' in scope`

- [ ] **Step 3: Implémenter `ProtobufReader`**

`client/DvfTileKit/Sources/DvfTileKit/ProtobufReader.swift` :

```swift
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
        let len = Int(try readVarint())
        guard len >= 0, pos + len <= end else { throw ProtobufError.truncated }
        defer { pos += len }
        return ProtobufReader(sharing: bytes, from: pos, to: pos + len)
    }

    mutating func readString() throws -> String {
        let len = Int(try readVarint())
        guard len >= 0, pos + len <= end else { throw ProtobufError.truncated }
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
            let len = Int(try readVarint())
            guard len >= 0, pos + len <= end else { throw ProtobufError.truncated }
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
```

- [ ] **Step 4: Vérifier le passage**

Run: `cd client/DvfTileKit && swift test`
Expected: PASS (tous les tests, dont les 3 de TileCoord)

- [ ] **Step 5: Commit**

```bash
git add client/DvfTileKit
git commit -m "feat(client): ProtobufReader — wire format minimal (varint, zigzag, packed, fixed)"
```

---

### Task 3: Structures MVT (Tile / Layer / Feature / Value)

**Files:**
- Create: `client/DvfTileKit/Sources/DvfTileKit/MVTTile.swift`
- Test: `client/DvfTileKit/Tests/DvfTileKitTests/MVTTileTests.swift`

- [ ] **Step 1: Écrire le test (tuile synthétique fabriquée avec `PB`) qui échoue**

`client/DvfTileKit/Tests/DvfTileKitTests/MVTTileTests.swift` :

```swift
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
```

- [ ] **Step 2: Vérifier l'échec**

Run: `cd client/DvfTileKit && swift test`
Expected: FAIL — `cannot find 'MVTTile' in scope`

- [ ] **Step 3: Implémenter `MVTTile`**

`client/DvfTileKit/Sources/DvfTileKit/MVTTile.swift` :

```swift
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
            case (5, 0): layer.extent = Int(try sub.readVarint())
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
            case (3, 0): f.type = MVTGeomType(rawValue: Int(try sub.readVarint())) ?? .unknown
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
```

- [ ] **Step 4: Vérifier le passage**

Run: `cd client/DvfTileKit && swift test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add client/DvfTileKit
git commit -m "feat(client): parsing vector_tile.proto (Tile/Layer/Feature/Value, propriétés)"
```

---

### Task 4: Décodage des géométries (points, anneaux, aire signée)

**Files:**
- Create: `client/DvfTileKit/Sources/DvfTileKit/MVTGeometry.swift`
- Test: `client/DvfTileKit/Tests/DvfTileKitTests/MVTGeometryTests.swift`

- [ ] **Step 1: Écrire les tests (exemples officiels de la spec MVT 2.1 §4.3.5) qui échouent**

```swift
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
    }
}
```

- [ ] **Step 2: Vérifier l'échec**

Run: `cd client/DvfTileKit && swift test`
Expected: FAIL — `cannot find 'MVTGeometry' in scope`

- [ ] **Step 3: Implémenter `MVTGeometry`**

`client/DvfTileKit/Sources/DvfTileKit/MVTGeometry.swift` :

```swift
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
                guard i + 2 * count <= geometry.count else { throw MVTDecoderError.malformedGeometry }
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
```

- [ ] **Step 4: Vérifier le passage**

Run: `cd client/DvfTileKit && swift test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add client/DvfTileKit
git commit -m "feat(client): décodage géométries MVT (points, anneaux, aire signée spec 2.1)"
```

---

### Task 5: `Mutation` + `MVTDecoder.decodeMutations`

**Files:**
- Create: `client/DvfTileKit/Sources/DvfTileKit/Mutation.swift`
- Create: `client/DvfTileKit/Sources/DvfTileKit/MVTDecoder.swift`
- Test: `client/DvfTileKit/Tests/DvfTileKitTests/MVTDecoderTests.swift`

- [ ] **Step 1: Écrire le test (tuile mutations synthétique complète) qui échoue**

```swift
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
```

- [ ] **Step 2: Vérifier l'échec**

Run: `cd client/DvfTileKit && swift test`
Expected: FAIL — `cannot find 'MVTDecoder' in scope`

- [ ] **Step 3: Implémenter `Mutation` et `MVTDecoder.decodeMutations`**

`client/DvfTileKit/Sources/DvfTileKit/Mutation.swift` — miroir du contrat (mêmes commentaires que le squelette `DvfTileClient.swift`) :

```swift
import CoreLocation

/// Mutation DVF décodée d'une tuile — schéma contractuel
/// (carex.immo docs/specs/2026-06-11-tuiles-mvt-contrat-integration.md, amendé 2026-06-12).
public struct Mutation: Hashable, Sendable {
    public let id: String
    public let date: Int     // YYYYMMDD (annee = date / 10000)
    public let nat: Int      // 1 Vente, 2 VEFA, 3 Adjudication, 4 Échange, 5 Expropriation (jamais 0)
    public let type: Int     // 1 maison, 2 appartement, 3 immeuble, 4 local, 5 dépendance
    public let vf: Int?      // valeur foncière (EUR) — omise si absente ; pm2 = vf/sb si les deux > 0
    public let sb: Int       // surface bâtie (m², biens post-fusion hors dépendances)
    public let st: Int       // surface terrain (m²)
    public let np: Int       // pièces (somme des biens)
    public let nl: Int       // nb de biens post-fusion
    public let com: String   // code commune INSEE (COG courant) — nom via table COG côté app
    public let adr: String?  // adresse — PRÉSENTE À z>=13 UNIQUEMENT
    public let cp: String?   // code postal — PRÉSENT À z>=13 UNIQUEMENT
    public let coordinate: CLLocationCoordinate2D

    // égalité/hash par id : clé de déduplication inter-tuiles
    public static func == (lhs: Mutation, rhs: Mutation) -> Bool { lhs.id == rhs.id }
    public func hash(into hasher: inout Hasher) { hasher.combine(id) }
}
```

`client/DvfTileKit/Sources/DvfTileKit/MVTDecoder.swift` :

```swift
import Foundation

public enum MVTDecoder {
    /// Couche `mutations` -> [Mutation]. `data` doit être le MVT décompressé
    /// (URLSession décompresse Content-Encoding: gzip automatiquement ;
    /// une donnée encore gzippée lève .gzipNotDecompressed).
    /// Une feature hors contrat (champ requis manquant, géométrie non-point)
    /// est ignorée — la QA du pipeline garantit qu'il n'y en a pas.
    public static func decodeMutations(_ data: Data, tile: TileCoord) throws -> [Mutation] {
        guard let layer = try MVTTile(data).layer(named: "mutations") else { return [] }
        var out: [Mutation] = []
        out.reserveCapacity(layer.features.count)
        for f in layer.features where f.type == .point {
            let props = layer.properties(of: f)
            guard let pt = try MVTGeometry.decodePoints(f.geometry).first,
                  case .string(let id)? = props["id"],
                  let date = props["date"]?.intValue,
                  let nat = props["nat"]?.intValue,
                  let type = props["type"]?.intValue,
                  let sb = props["sb"]?.intValue,
                  let st = props["st"]?.intValue,
                  let np = props["np"]?.intValue,
                  let nl = props["nl"]?.intValue,
                  case .string(let com)? = props["com"]
            else { continue }
            out.append(Mutation(
                id: id,
                date: Int(date),
                nat: Int(nat),
                type: Int(type),
                vf: props["vf"]?.intValue.map(Int.init),
                sb: Int(sb),
                st: Int(st),
                np: Int(np),
                nl: Int(nl),
                com: com,
                adr: props["adr"]?.stringValue,
                cp: props["cp"]?.stringValue,
                coordinate: tile.coordinate(of: pt, extent: layer.extent)))
        }
        return out
    }
}
```

- [ ] **Step 4: Vérifier le passage**

Run: `cd client/DvfTileKit && swift test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add client/DvfTileKit
git commit -m "feat(client): MVTDecoder.decodeMutations — contrat 12 attributs, dédup par id"
```

---

### Task 6: `AggregateFeature` + `MVTDecoder.decodeAggregates`

**Files:**
- Modify: `client/DvfTileKit/Sources/DvfTileKit/MVTDecoder.swift`
- Test: `client/DvfTileKit/Tests/DvfTileKitTests/AggregateTests.swift`

- [ ] **Step 1: Écrire le test (couche communes synthétique, polygone avec trou) qui échoue**

```swift
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
```

- [ ] **Step 2: Vérifier l'échec**

Run: `cd client/DvfTileKit && swift test`
Expected: FAIL — `type 'MVTDecoder' has no member 'decodeAggregates'`

- [ ] **Step 3: Implémenter `decodeAggregates`**

Ajouter à `MVTDecoder.swift` :

```swift
import CoreLocation

/// Entité agrégée (commune ou département) : code INSEE, propriétés brutes
/// (clés n_{annee}_t{type} / p_{annee}_t{type} / n_tot / pm2_med / vf_med / cx / cy),
/// anneaux extérieurs en WGS84 (« polygones simples » du contrat — trous ignorés).
public struct AggregateFeature: Sendable {
    public let code: String
    public let properties: [String: MVTValue]
    public let exteriorRings: [[CLLocationCoordinate2D]]
}

extension MVTDecoder {
    public static func decodeAggregates(_ data: Data, layer name: String, tile: TileCoord) throws -> [AggregateFeature] {
        guard let layer = try MVTTile(data).layer(named: name) else { return [] }
        var out: [AggregateFeature] = []
        out.reserveCapacity(layer.features.count)
        for f in layer.features where f.type == .polygon {
            let props = layer.properties(of: f)
            guard case .string(let code)? = props["code"] else { continue }
            let rings = try MVTGeometry.decodeRings(f.geometry)
            let exteriors = rings
                .filter { MVTGeometry.signedArea($0) > 0 }
                .map { ring in ring.map { tile.coordinate(of: $0, extent: layer.extent) } }
            out.append(AggregateFeature(code: code, properties: props, exteriorRings: exteriors))
        }
        return out
    }
}
```

- [ ] **Step 4: Vérifier le passage**

Run: `cd client/DvfTileKit && swift test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add client/DvfTileKit
git commit -m "feat(client): MVTDecoder.decodeAggregates — code, agrégats, anneaux extérieurs"
```

---

### Task 7: Script de génération des fixtures + fixtures committées

**Files:**
- Create: `client/DvfTileKit/generate_fixtures.py`
- Create (générés): `client/DvfTileKit/Tests/DvfTileKitTests/Fixtures/{mutations_z14_lyon,mutations_z13_lyon,communes_z8_lyon,departements_z5}.mvt` + `.expected.json`

- [ ] **Step 1: Écrire le script**

`client/DvfTileKit/generate_fixtures.py` :

```python
#!/usr/bin/env python3
"""
Génère les fixtures de parité du décodeur Swift depuis l'archive PMTiles.

Pour chaque tuile témoin : {nom}.mvt (MVT décompressé, tel que reçu par l'app
après décompression URLSession) + {nom}.expected.json (golden produit par
mapbox_vector_tile, la référence de simulate_ios.py).

Golden, par couche, features triées par `id` (mutations) ou `code` (agrégats) :
- properties : dict brut
- type : "Point" / "Polygon" / "MultiPolygon"
- coords : [x, y] tuile (y vers le bas, y_coord_down=True) pour les points
- rings / vertices : nombre d'anneaux et de sommets (sans le sommet de
  fermeture GeoJSON) pour les polygones — invariants de décodage qui ne
  dépendent pas de l'assemblage extérieur/trous de la lib.

Usage : source .venv/bin/activate && python3 client/DvfTileKit/generate_fixtures.py build/dvf.pmtiles
"""
import gzip
import json
import sys
from pathlib import Path

import mapbox_vector_tile
from pmtiles.reader import Reader, MmapSource

TILES = [
    ("mutations_z14_lyon", 14, 8411, 5844),
    ("mutations_z13_lyon", 13, 4205, 2922),
    ("communes_z8_lyon", 8, 131, 91),
    ("departements_z5", 5, 16, 11),
]


def rings_of(geometry):
    if geometry["type"] == "Polygon":
        return geometry["coordinates"]
    if geometry["type"] == "MultiPolygon":
        return [ring for poly in geometry["coordinates"] for ring in poly]
    raise ValueError(f"géométrie inattendue : {geometry['type']}")


def main():
    pmtiles_path = sys.argv[1] if len(sys.argv) > 1 else "build/dvf.pmtiles"
    out_dir = Path(__file__).parent / "Tests" / "DvfTileKitTests" / "Fixtures"
    out_dir.mkdir(parents=True, exist_ok=True)
    reader = Reader(MmapSource(open(pmtiles_path, "rb")))

    for name, z, x, y in TILES:
        data = reader.get(z, x, y)
        assert data, f"tuile absente : {z}/{x}/{y}"
        raw = gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data
        (out_dir / f"{name}.mvt").write_bytes(raw)

        decoded = mapbox_vector_tile.decode(raw, default_options={"y_coord_down": True})
        golden = {}
        for lname, layer in decoded.items():
            feats = []
            for f in layer["features"]:
                g = f["geometry"]
                entry = {"properties": f["properties"], "type": g["type"]}
                if g["type"] == "Point":
                    entry["coords"] = list(g["coordinates"])
                else:
                    rings = rings_of(g)
                    entry["rings"] = len(rings)
                    entry["vertices"] = sum(len(r) - 1 for r in rings)
                feats.append(entry)
            key = "id" if lname == "mutations" else "code"
            feats.sort(key=lambda e: e["properties"][key])
            golden[lname] = feats
        (out_dir / f"{name}.expected.json").write_text(
            json.dumps(golden, ensure_ascii=False, sort_keys=True))
        print(f"{name}: {len(raw)} octets, couches "
              + ", ".join(f"{k}={len(v)}" for k, v in golden.items()))

    print("Fixtures écrites dans", out_dir)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Générer et vérifier**

Run: `source .venv/bin/activate && python3 client/DvfTileKit/generate_fixtures.py build/dvf.pmtiles`
Expected (comptages mesurés le 2026-06-12 sur le build France en production) :
```
mutations_z14_lyon: ... octets, couches mutations=3061
mutations_z13_lyon: ... octets, couches mutations=8920
communes_z8_lyon: ... octets, couches communes=1063, mutations=8055
departements_z5: ... octets, couches departements=84, mutations=14966
```
Supprimer le placeholder : `rm client/DvfTileKit/Tests/DvfTileKitTests/Fixtures/.gitkeep`

- [ ] **Step 3: Commit (script + fixtures — binaires committés sciemment, ~3-4 Mo)**

```bash
git add client/DvfTileKit/generate_fixtures.py client/DvfTileKit/Tests/DvfTileKitTests/Fixtures
git commit -m "test(client): fixtures de parité MVT (4 tuiles France + goldens mapbox_vector_tile)"
```

---

### Task 8: Tests de parité avec les goldens

**Files:**
- Test: `client/DvfTileKit/Tests/DvfTileKitTests/ParityTests.swift`

- [ ] **Step 1: Écrire les tests de parité (échouent tant que le comparateur n'existe pas)**

```swift
import Foundation
import Testing
@testable import DvfTileKit

/// Valeur JSON du golden (proprietés typées par mapbox_vector_tile).
enum GoldenValue: Decodable, Equatable {
    case string(String), int(Int64), double(Double), bool(Bool)

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let i = try? c.decode(Int64.self) { self = .int(i) }
        else if let d = try? c.decode(Double.self) { self = .double(d) }
        else { self = .string(try c.decode(String.self)) }
    }

    /// Égalité avec une MVTValue décodée par DvfTileKit (tolérance 1e-9 sur les doubles).
    func matches(_ v: MVTValue?) -> Bool {
        switch (self, v) {
        case (.string(let a), .string(let b)?): a == b
        case (.int(let a), .int(let b)?): a == b
        case (.double(let a), .double(let b)?): abs(a - b) < 1e-9
        case (.double(let a), .int(let b)?): a == Double(b)   // JSON 5.0 vs int MVT
        case (.bool(let a), .bool(let b)?): a == b
        default: false
        }
    }
}

struct GoldenFeature: Decodable {
    let properties: [String: GoldenValue]
    let type: String
    let coords: [Int]?
    let rings: Int?
    let vertices: Int?
}

func loadFixture(_ name: String) throws -> (mvt: Data, golden: [String: [GoldenFeature]]) {
    let mvtURL = try #require(Bundle.module.url(forResource: name, withExtension: "mvt",
                                                subdirectory: "Fixtures"))
    let jsonURL = try #require(Bundle.module.url(forResource: "\(name).expected", withExtension: "json",
                                                 subdirectory: "Fixtures"))
    return (try Data(contentsOf: mvtURL),
            try JSONDecoder().decode([String: [GoldenFeature]].self, from: Data(contentsOf: jsonURL)))
}

func expectPropertiesMatch(_ golden: [String: GoldenValue], _ actual: [String: MVTValue],
                           context: String) {
    #expect(Set(golden.keys) == Set(actual.keys), Comment(rawValue: context))
    for (k, gv) in golden {
        #expect(gv.matches(actual[k]), Comment(rawValue: "\(context) clé \(k)"))
    }
}

@Suite struct ParityTests {
    /// Parité brute couche mutations : comptes, propriétés, coordonnées tuile exactes.
    func checkMutationsParity(fixture: String, expectAdr: Bool) throws {
        let (mvt, golden) = try loadFixture(fixture)
        let layer = try #require(try MVTTile(mvt).layer(named: "mutations"))
        let goldenFeats = try #require(golden["mutations"])
        #expect(layer.features.count == goldenFeats.count)

        var decoded: [(id: String, props: [String: MVTValue], pt: TilePoint)] = []
        for f in layer.features {
            let props = layer.properties(of: f)
            let pt = try #require(try MVTGeometry.decodePoints(f.geometry).first)
            guard case .string(let id)? = props["id"] else { Issue.record("id manquant"); continue }
            decoded.append((id, props, pt))
        }
        decoded.sort { $0.id < $1.id }
        for (d, g) in zip(decoded, goldenFeats) {
            expectPropertiesMatch(g.properties, d.props, context: "\(fixture) id \(d.id)")
            let coords = try #require(g.coords)
            #expect(Int(d.pt.x) == coords[0] && Int(d.pt.y) == coords[1])
        }
        let withAdr = decoded.filter { $0.props["adr"] != nil }.count
        if expectAdr {
            #expect(withAdr > 0)              // adresse garantie z>=13
        } else {
            #expect(withAdr == 0)             // adr/cp exclus de la passe z4-12
        }
    }

    @Test func mutationsZ14() throws { try checkMutationsParity(fixture: "mutations_z14_lyon", expectAdr: true) }
    @Test func mutationsZ13() throws { try checkMutationsParity(fixture: "mutations_z13_lyon", expectAdr: true) }
    @Test func mutationsEchantillonneesZ8SansAdresse() throws {
        try checkMutationsParity(fixture: "communes_z8_lyon", expectAdr: false)
    }

    /// Parité agrégats : comptes, propriétés, invariants géométrie (anneaux, sommets).
    func checkAggregatesParity(fixture: String, layerName: String) throws {
        let (mvt, golden) = try loadFixture(fixture)
        let layer = try #require(try MVTTile(mvt).layer(named: layerName))
        let goldenFeats = try #require(golden[layerName])
        #expect(layer.features.count == goldenFeats.count)

        var decoded: [(code: String, props: [String: MVTValue], rings: [[TilePoint]])] = []
        for f in layer.features {
            let props = layer.properties(of: f)
            guard case .string(let code)? = props["code"] else { Issue.record("code manquant"); continue }
            decoded.append((code, props, try MVTGeometry.decodeRings(f.geometry)))
        }
        decoded.sort { $0.code < $1.code }
        for (d, g) in zip(decoded, goldenFeats) {
            expectPropertiesMatch(g.properties, d.props, context: "\(fixture) code \(d.code)")
            #expect(d.rings.count == g.rings, Comment(rawValue: "anneaux \(d.code)"))
            #expect(d.rings.reduce(0) { $0 + $1.count } == g.vertices, Comment(rawValue: "sommets \(d.code)"))
        }
    }

    @Test func communesZ8() throws { try checkAggregatesParity(fixture: "communes_z8_lyon", layerName: "communes") }
    @Test func departementsZ5() throws { try checkAggregatesParity(fixture: "departements_z5", layerName: "departements") }

    /// L'API publique de bout en bout sur une tuile réelle.
    @Test func apiPubliqueZ13() throws {
        let (mvt, golden) = try loadFixture("mutations_z13_lyon")
        let muts = try MVTDecoder.decodeMutations(mvt, tile: TileCoord(z: 13, x: 4205, y: 2922))
        #expect(muts.count == golden["mutations"]?.count)
        // tous les points retombent dans l'emprise de la tuile (lon 4.79-4.84, lat 45.73-45.77)
        for m in muts {
            #expect(m.coordinate.longitude > 4.74 && m.coordinate.longitude < 4.90)
            #expect(m.coordinate.latitude > 45.70 && m.coordinate.latitude < 45.81)
        }
    }
}
```

- [ ] **Step 2: Lancer et corriger jusqu'au vert**

Run: `cd client/DvfTileKit && swift test`
Expected: PASS. En cas d'écart : comparer feature par feature (l'assertion nomme l'id/le code et la clé fautive). Les causes plausibles d'écart sont : promotion float/double (`pm2_med` écrit en double par tippecanoe), `vertices` si la lib golden ne ferme pas les anneaux (ajuster `len(r) - 1` → `len(r)` dans le script et regénérer), uint vs int. **Ne pas affaiblir les tests pour passer** : ajuster le décodeur ou le format du golden, pas les assertions.

- [ ] **Step 3: Commit**

```bash
git add client/DvfTileKit
git commit -m "test(client): parité décodeur Swift ↔ mapbox_vector_tile sur tuiles France réelles"
```

---

### Task 9: Test de performance (budget décodage hors main thread)

**Files:**
- Test: `client/DvfTileKit/Tests/DvfTileKitTests/PerformanceTests.swift`

- [ ] **Step 1: Écrire le test**

```swift
import Foundation
import Testing
@testable import DvfTileKit

@Suite struct PerformanceTests {
    /// La tuile z13 Lyon (8 920 mutations, la plus dense des fixtures) doit se décoder
    /// en un temps compatible avec un viewport de 16 tuiles hors main thread.
    /// Borne volontairement large (debug, CI) — la mesure imprimée sert de suivi.
    @Test func decodeZ13SousLaSeconde() throws {
        let (mvt, _) = try loadFixture("mutations_z13_lyon")
        let tile = TileCoord(z: 13, x: 4205, y: 2922)
        let clock = ContinuousClock()
        var count = 0
        let elapsed = try clock.measure {
            count = try MVTDecoder.decodeMutations(mvt, tile: tile).count
        }
        print("decode z13 Lyon : \(count) mutations en \(elapsed)")
        #expect(count == 8920)
        #expect(elapsed < .seconds(1))
    }
}
```

- [ ] **Step 2: Lancer**

Run: `cd client/DvfTileKit && swift test`
Expected: PASS, mesure imprimée (ordre de grandeur attendu : < 100 ms en debug)

- [ ] **Step 3: Commit**

```bash
git add client/DvfTileKit
git commit -m "test(client): budget de décodage tuile z13 dense"
```

---

### Task 10: Documentation et raccordement du squelette

**Files:**
- Modify: `client/DvfTileClient.swift` (en-tête, lignes 1-3)
- Modify: `README.md` (section Client iOS)
- Modify: `CLAUDE.md` (section Commandes / validation)

- [ ] **Step 1: Mettre à jour l'en-tête du squelette**

Dans `client/DvfTileClient.swift`, remplacer les lignes 1-3 :

```swift
// CAREX - Client de tuiles DVF pour iOS (MapKit natif) - squelette de reference
// Le decodage MVT s'appuie sur SwiftProtobuf + le schema vector_tile.proto
// (https://github.com/mapbox/vector-tile-spec) ou un binding existant.
```

par :

```swift
// CAREX - Client de tuiles DVF pour iOS (MapKit natif) - squelette de reference
// Le decodage MVT est fourni par le package DvfTileKit (client/DvfTileKit/,
// zero dependance : ProtobufReader + MVTTile + MVTDecoder) - `swift test` pour la parite.
```

- [ ] **Step 2: Mettre à jour README.md et CLAUDE.md**

Dans `README.md`, section **Client iOS** (autour de la ligne 120), ajouter après la phrase existante :

```markdown
Le décodeur MVT est livré : package SwiftPM zéro dépendance `client/DvfTileKit/`
(`MVTDecoder.decodeMutations` / `decodeAggregates`), vérifié par parité avec
`client/simulate_ios.py` sur des tuiles réelles du build France
(`cd client/DvfTileKit && swift test` ; fixtures régénérables par
`python3 client/DvfTileKit/generate_fixtures.py build/dvf.pmtiles`).
```

Dans `CLAUDE.md`, section **Commandes**, remplacer :

```markdown
Validation (pas de linter ; les seuls tests automatisés sont ceux de `pipeline/parity/`) :
```

par :

```markdown
Validation (pas de linter ; tests automatisés : `pipeline/parity/` + le package Swift `client/DvfTileKit`) :
```

et ajouter au bloc de commandes de validation :

```bash
cd client/DvfTileKit && swift test            # décodeur MVT Swift : unitaires + parité goldens
```

- [ ] **Step 3: Vérification finale complète**

Run: `cd client/DvfTileKit && swift test && cd ../.. && source .venv/bin/activate && python3 -m pytest -q pipeline/parity`
Expected: tous les tests Swift PASS, parité pipeline inchangée (aucun fichier pipeline touché)

- [ ] **Step 4: Commit**

```bash
git add client/DvfTileClient.swift README.md CLAUDE.md
git commit -m "docs: décodeur MVT Swift livré (DvfTileKit) — lot 0 de la spec aval iOS"
```

---

## Auto-revue du plan (faite le 2026-06-12)

- **Couverture spec** : lot 0 = « MVTDecoder Swift zéro dépendance (points + polygones simples) » → Tasks 2-6 ; critère d'acceptation « parité avec simulate_ios.py sur la même tuile » → Tasks 7-8 (mêmes tuiles réelles, golden produit par la même lib) ; « décodage hors main thread » → types Sendable + budget Task 9 ; intégration documentaire → Task 10.
- **Hors périmètre assumé** : le réseau (`DvfTileClient.tile()`), le cache et `TileMath.tiles(for:)` restent dans le squelette — ils appartiennent au lot 1 (intégration app, session carex.immo). `decodeAggregates` ne reconstruit pas les MultiPolygons trous compris (« polygones simples » du contrat).
- **Cohérence de types** : `TilePoint(x:y: Int32)` partout ; `MVTValue` public (exposé par `AggregateFeature.properties`) ; `Mutation`/`TileCoord`/`AggregateFeature`/`MVTDecoder`/`MVTDecoderError` publics, le reste internal testé via `@testable`.
- **Point d'attention exécution** : Task 6 step 1 — les deltas zigzag du trou sont recalculés dans la note ; Task 8 step 2 liste les écarts plausibles et interdit d'affaiblir les assertions.
