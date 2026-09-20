#!/usr/bin/env bash
# Wrap the SwiftPM binary in a minimal .app bundle.
#
# Why: on macOS, CoreMotion's headphone-motion permission is gated by TCC, and
# TCC will not raise its prompt for a bare unbundled executable -- the process
# just sits there receiving zero samples with authorization=notDetermined.
# Running the copy inside the bundle makes the prompt appear, and ad-hoc signing
# gives it a stable identity so the grant sticks across rebuilds.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="${CONFIG:-debug}"
BIN="$ROOT/swift-capture/.build/$CONFIG/airpod-motion"
APP="$ROOT/build/AirPodMotion.app"

if [[ ! -x "$BIN" ]]; then
  echo "error: $BIN not found -- run 'make build' first" >&2
  exit 1
fi

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cp "$BIN" "$APP/Contents/MacOS/airpod-motion"
cp "$ROOT/swift-capture/Sources/airpod-motion/Info.plist" "$APP/Contents/Info.plist"
codesign --force --sign - "$APP" >/dev/null 2>&1 || \
  echo "warning: ad-hoc codesign failed; the permission grant may not persist" >&2

echo "$APP/Contents/MacOS/airpod-motion"
