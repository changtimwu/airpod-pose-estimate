// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "airpod-motion",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "airpod-motion",
            path: "Sources/airpod-motion",
            exclude: ["Info.plist"],
            linkerSettings: [
                // CMHeadphoneMotionManager requires NSMotionUsageDescription. A bare
                // SwiftPM binary has no bundle, so the plist is embedded in __TEXT.
                .unsafeFlags([
                    "-Xlinker", "-sectcreate",
                    "-Xlinker", "__TEXT",
                    "-Xlinker", "__info_plist",
                    "-Xlinker", "Sources/airpod-motion/Info.plist",
                ])
            ]
        )
    ]
)
