import Foundation
import Network

/// Where encoded records go. Stdout is the default so the Python side can just
/// read the subprocess pipe; UDP exists for running the reader on another box.
protocol RecordSink {
    func emit(_ line: Data)
}

final class StdoutSink: RecordSink {
    func emit(_ line: Data) {
        FileHandle.standardOutput.write(line)
    }
}

final class UDPSink: RecordSink {
    private let connection: NWConnection

    init(host: String, port: UInt16) {
        connection = NWConnection(
            host: NWEndpoint.Host(host),
            port: NWEndpoint.Port(rawValue: port)!,
            using: .udp
        )
        connection.start(queue: .global(qos: .userInitiated))
    }

    func emit(_ line: Data) {
        connection.send(content: line, completion: .idempotent)
    }
}

final class FanoutSink: RecordSink {
    private let sinks: [RecordSink]
    init(_ sinks: [RecordSink]) { self.sinks = sinks }
    func emit(_ line: Data) { sinks.forEach { $0.emit(line) } }
}
