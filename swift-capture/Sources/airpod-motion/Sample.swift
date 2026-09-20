import CoreMotion
import Foundation

/// One line of the wire protocol. Every record carries `type` so a reader can
/// demultiplex samples from status events without framing tricks.
enum Record: Encodable {
    case sample(MotionSample)
    case status(StatusEvent)

    func encode(to encoder: Encoder) throws {
        switch self {
        case .sample(let s): try s.encode(to: encoder)
        case .status(let s): try s.encode(to: encoder)
        }
    }
}

struct MotionSample: Encodable {
    let type = "sample"
    /// Monotonic device timestamp in seconds (CMDeviceMotion.timestamp).
    let t: Double
    /// Wall-clock unix seconds, for aligning with other recordings.
    let wall: Double
    let seq: Int
    /// Attitude quaternion as [w, x, y, z].
    let q: [Double]
    /// Convenience Euler angles in degrees, derived from `q`.
    let euler: Euler
    /// Rotation rate, rad/s, [x, y, z].
    let rot: [Double]
    /// User acceleration, g, [x, y, z].
    let acc: [Double]
    /// Gravity vector, g, [x, y, z].
    let grav: [Double]
    /// Which bud produced this sample: "left", "right", or "default".
    ///
    /// CoreMotion delivers ONE fused stream, not one per bud, and picks the
    /// source itself. This field is how you notice it switching mid-session --
    /// which it does, e.g. when a bud is removed -- since the orientation can
    /// jump at that moment with no other warning.
    let loc: String

    struct Euler: Encodable {
        let roll: Double
        let pitch: Double
        let yaw: Double
    }

    init(motion: CMDeviceMotion, seq: Int) {
        let quat = motion.attitude.quaternion
        self.t = motion.timestamp
        self.wall = Date().timeIntervalSince1970
        self.seq = seq
        self.q = [quat.w, quat.x, quat.y, quat.z]
        self.euler = Euler(
            roll: motion.attitude.roll * 180 / .pi,
            pitch: motion.attitude.pitch * 180 / .pi,
            yaw: motion.attitude.yaw * 180 / .pi
        )
        self.rot = [motion.rotationRate.x, motion.rotationRate.y, motion.rotationRate.z]
        self.acc = [motion.userAcceleration.x, motion.userAcceleration.y, motion.userAcceleration.z]
        self.grav = [motion.gravity.x, motion.gravity.y, motion.gravity.z]
        switch motion.sensorLocation {
        case .headphoneLeft: self.loc = "left"
        case .headphoneRight: self.loc = "right"
        case .default: self.loc = "default"
        @unknown default: self.loc = "unknown"
        }
    }
}

struct StatusEvent: Encodable {
    let type = "status"
    let wall: Double
    /// One of: starting, connected, disconnected, error, stopped.
    let event: String
    let detail: String?

    init(_ event: String, detail: String? = nil) {
        self.wall = Date().timeIntervalSince1970
        self.event = event
        self.detail = detail
    }
}
