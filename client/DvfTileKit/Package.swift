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
