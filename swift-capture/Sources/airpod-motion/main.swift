import Foundation

// Hand-rolled arg parsing keeps the package dependency-free so `swift build`
// works offline on a hackathon wifi.
func usage() -> Never {
    FileHandle.standardError.write(Data("""
    airpod-motion - stream AirPods head-motion samples as newline-delimited JSON

    USAGE:
      airpod-motion [--udp HOST:PORT] [--no-stdout] [--max-samples N]

    OPTIONS:
      --udp HOST:PORT   also mirror each record to a UDP endpoint
      --no-stdout       suppress stdout (only useful together with --udp)
      --max-samples N   exit after N motion samples (handy for smoke tests)
      -h, --help        show this help

    OUTPUT: one JSON object per line, {"type":"sample",...} or {"type":"status",...}

    """.utf8))
    exit(2)
}

var sinks: [RecordSink] = []
var useStdout = true
var maxSamples: Int?

var args = Array(CommandLine.arguments.dropFirst())
while let arg = args.first {
    args.removeFirst()
    switch arg {
    case "-h", "--help":
        usage()
    case "--no-stdout":
        useStdout = false
    case "--udp":
        guard let value = args.first else { usage() }
        args.removeFirst()
        let parts = value.split(separator: ":")
        guard parts.count == 2, let port = UInt16(parts[1]) else { usage() }
        sinks.append(UDPSink(host: String(parts[0]), port: port))
    case "--max-samples":
        guard let value = args.first, let n = Int(value) else { usage() }
        args.removeFirst()
        maxSamples = n
    default:
        FileHandle.standardError.write(Data("unknown argument: \(arg)\n".utf8))
        usage()
    }
}

if useStdout { sinks.insert(StdoutSink(), at: 0) }
guard !sinks.isEmpty else {
    FileHandle.standardError.write(Data("nothing to do: --no-stdout without --udp\n".utf8))
    exit(2)
}

let streamer = MotionStreamer(sink: FanoutSink(sinks), maxSamples: maxSamples)

// Ctrl-C should still flush a "stopped" status line.
let sigintSource = DispatchSource.makeSignalSource(signal: SIGINT, queue: .main)
sigintSource.setEventHandler {
    streamer.stop()
    exit(0)
}
sigintSource.resume()
signal(SIGINT, SIG_IGN)

streamer.start()
RunLoop.main.run()
