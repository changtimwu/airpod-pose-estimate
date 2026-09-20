import CoreMotion
import Foundation

/// Pulls CMDeviceMotion out of the AirPods and pushes JSON lines into a sink.
///
/// Sample rate is fixed by the OS -- there is no API to change it -- so any
/// smoothing or resampling belongs downstream. 50 Hz measured on AirPods Pro 2 + macOS 26 (dead steady 20.0 ms gaps). Older devices/OS versions are widely reported at 25 Hz, and Apple guarantees nothing, so derive dt from the `t` field instead of hard-coding a rate.
final class MotionStreamer: NSObject, CMHeadphoneMotionManagerDelegate {
    private let manager = CMHeadphoneMotionManager()
    private let sink: RecordSink
    private let encoder = JSONEncoder()
    private let queue = OperationQueue()
    private var seq = 0
    private var maxSamples: Int?

    init(sink: RecordSink, maxSamples: Int? = nil) {
        self.sink = sink
        self.maxSamples = maxSamples
        super.init()
        queue.maxConcurrentOperationCount = 1
        queue.qualityOfService = .userInitiated
        encoder.outputFormatting = []
        manager.delegate = self
    }

    func start() {
        emit(.status(StatusEvent("starting", detail: "authorization=\(authorizationDescription())")))

        guard manager.isDeviceMotionAvailable else {
            emit(.status(StatusEvent("error", detail: "device motion unavailable: connect AirPods (Pro/3/Max or Beats Fit Pro) and make sure they are the active audio output")))
            exit(1)
        }

        manager.startDeviceMotionUpdates(to: queue) { [weak self] motion, error in
            guard let self else { return }
            if let error {
                self.emit(.status(StatusEvent("error", detail: error.localizedDescription)))
                return
            }
            guard let motion else { return }
            self.seq += 1
            self.emit(.sample(MotionSample(motion: motion, seq: self.seq)))
            if let limit = self.maxSamples, self.seq >= limit {
                self.stop()
                exit(0)
            }
        }
    }

    func stop() {
        manager.stopDeviceMotionUpdates()
        emit(.status(StatusEvent("stopped", detail: "samples=\(seq)")))
    }

    // MARK: - CMHeadphoneMotionManagerDelegate

    func headphoneMotionManagerDidConnect(_ manager: CMHeadphoneMotionManager) {
        emit(.status(StatusEvent("connected")))
    }

    func headphoneMotionManagerDidDisconnect(_ manager: CMHeadphoneMotionManager) {
        emit(.status(StatusEvent("disconnected")))
    }

    // MARK: - Private

    private func emit(_ record: Record) {
        guard var data = try? encoder.encode(record) else { return }
        data.append(0x0A)  // newline-delimited JSON
        sink.emit(data)
    }

    private func authorizationDescription() -> String {
        switch CMHeadphoneMotionManager.authorizationStatus() {
        case .notDetermined: return "notDetermined"
        case .restricted: return "restricted"
        case .denied: return "denied"
        case .authorized: return "authorized"
        @unknown default: return "unknown"
        }
    }
}
