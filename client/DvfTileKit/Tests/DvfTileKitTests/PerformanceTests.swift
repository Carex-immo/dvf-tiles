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
