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
