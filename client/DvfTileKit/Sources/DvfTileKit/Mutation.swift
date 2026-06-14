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

    public init(
        id: String,
        date: Int,
        nat: Int,
        type: Int,
        vf: Int?,
        sb: Int,
        st: Int,
        np: Int,
        nl: Int,
        com: String,
        adr: String?,
        cp: String?,
        coordinate: CLLocationCoordinate2D
    ) {
        self.id = id
        self.date = date
        self.nat = nat
        self.type = type
        self.vf = vf
        self.sb = sb
        self.st = st
        self.np = np
        self.nl = nl
        self.com = com
        self.adr = adr
        self.cp = cp
        self.coordinate = coordinate
    }

    // égalité/hash par id : clé de déduplication inter-tuiles
    public static func == (lhs: Mutation, rhs: Mutation) -> Bool { lhs.id == rhs.id }
    public func hash(into hasher: inout Hasher) { hasher.combine(id) }
}
