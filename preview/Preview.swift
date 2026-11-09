// SPDX-License-Identifier: GPL-2.0-or-later
// Persistent local preview. Playback and source recovery do not recreate its window.
import AppKit
import AVFoundation
import CoreImage
import CoreVideo
import Darwin

struct Options {
    var standard = "auto"
    var seconds = 0.0
    var attenuation: UInt32 = 6
    var controlInput = false
    init() {
        var arguments = Array(CommandLine.arguments.dropFirst())
        while !arguments.isEmpty {
            let key = arguments.removeFirst()
            if key == "--control-stdin" { controlInput = true; continue }
            guard !arguments.isEmpty else { fatalError("Missing value for \(key)") }
            let value = arguments.removeFirst()
            switch key {
            case "--standard": standard = value
            case "--seconds": seconds = Double(value) ?? -1
            case "--audio-attenuation-db": attenuation = UInt32(value) ?? 99
            default: fatalError("Unknown option \(key)")
            }
        }
        precondition(standard.withCString { c039_standard_parse($0) } != 0 &&
                     seconds >= 0 && seconds <= 3600 && attenuation <= 48, "Invalid preview options")
    }
}

final class VideoView: NSView {
    var pixel: CVPixelBuffer?
    var waiting = true
    let imageContext = CIContext(options: [.cacheIntermediates: false])
    override var isOpaque: Bool { true }
    override func draw(_ dirtyRect: NSRect) {
        NSColor.black.setFill(); bounds.fill()
        if let pixel {
            let input = CIImage(cvPixelBuffer: pixel)
            if let cg = imageContext.createCGImage(input, from: input.extent) {
                let scale = min(bounds.width / input.extent.width, bounds.height / input.extent.height)
                let size = NSSize(width: input.extent.width * scale, height: input.extent.height * scale)
                let rect = NSRect(x: (bounds.width-size.width)/2, y: (bounds.height-size.height)/2,
                                  width: size.width, height: size.height)
                NSImage(cgImage: cg, size: size).draw(in: rect)
            }
        }
        if waiting {
            let text = "Ожидание устойчивого видеосигнала…"
            let style: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 16),
                .foregroundColor: NSColor.white, .backgroundColor: NSColor.black.withAlphaComponent(0.8)]
            let size = (text as NSString).size(withAttributes: style)
            (text as NSString).draw(at: NSPoint(x: max(8, (bounds.width-size.width)/2), y: 16), withAttributes: style)
        }
    }
}

final class Preview: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let options: Options
    let captureQueue = DispatchQueue(label: "C039.preview.usb", qos: .userInteractive)
    let mailboxLock = NSLock()
    let audio = c039_preview_audio_create(12000, 1920)!
    let engine = AVAudioEngine()
    var audioNode: AVAudioSourceNode?
    var pools: [CVPixelBufferPool] = []
    var decoder: OpaquePointer!
    var session: OpaquePointer?
    var requestedStandard: UInt32
    var closing = false
    var fatalCleanup = false
    var sourceRuns = 0
    var decodedFrames: UInt64 = 0
    var presentedFrames: UInt64 = 0
    var suppressedUntil = 0.0
    var pendingPixel: CVPixelBuffer?
    var deliveryScheduled = false
    var lastFrame = 0.0
    var lastReport = 0.0
    var window: NSWindow!
    let video = VideoView()
    let status = NSTextField(labelWithString: "Запуск захвата…")
    let standardSelect = NSPopUpButton(frame: .zero, pullsDown: false)
    var formatName = "AUTO"
    var captureMessage = ""
    var audioMessage = ""
    var timer: Timer?
    var signals: [DispatchSourceSignal] = []

    init(options: Options) {
        self.options = options
        requestedStandard = options.standard.withCString { c039_standard_parse($0) }
        super.init()
        for height in [576, 480] {
            var pool: CVPixelBufferPool?
            let attributes: [CFString: Any] = [kCVPixelBufferWidthKey: 720, kCVPixelBufferHeightKey: height,
                kCVPixelBufferPixelFormatTypeKey: kCVPixelFormatType_422YpCbCr8,
                kCVPixelBufferIOSurfacePropertiesKey: [:]]
            precondition(CVPixelBufferPoolCreate(nil, nil, attributes as CFDictionary, &pool) == kCVReturnSuccess)
            pools.append(pool!)
        }
        decoder = c039_frame_decoder_create(576, { context, bytes, count, height in
            guard let context, let bytes else { return }
            Unmanaged<Preview>.fromOpaque(context).takeUnretainedValue().offer(bytes, count, height)
        }, Unmanaged.passUnretained(self).toOpaque())
        precondition(decoder != nil)
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 720, height: 610),
            styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "AVerMedia C039 — Composite + RCA"
        window.minSize = NSSize(width: 480, height: 360)
        window.delegate = self
        let content = window.contentView!
        video.translatesAutoresizingMaskIntoConstraints = false
        status.translatesAutoresizingMaskIntoConstraints = false
        standardSelect.translatesAutoresizingMaskIntoConstraints = false
        for index in 0..<Int(c039_standard_name_count) {
            if let entry = c039_standard_name_at(index) {
                standardSelect.addItem(withTitle: String(cString: entry.pointee.name).uppercased())
            }
        }
        standardSelect.selectItem(withTitle: options.standard.uppercased())
        standardSelect.target = self; standardSelect.action = #selector(chooseStandard)
        status.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
        status.lineBreakMode = .byTruncatingTail
        content.addSubview(video); content.addSubview(status); content.addSubview(standardSelect)
        NSLayoutConstraint.activate([
            video.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            video.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            video.topAnchor.constraint(equalTo: content.topAnchor),
            video.bottomAnchor.constraint(equalTo: status.topAnchor, constant: -6),
            standardSelect.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 8),
            standardSelect.bottomAnchor.constraint(equalTo: content.bottomAnchor, constant: -5),
            standardSelect.widthAnchor.constraint(equalToConstant: 125),
            status.leadingAnchor.constraint(equalTo: standardSelect.trailingAnchor, constant: 10),
            status.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -10),
            status.bottomAnchor.constraint(equalTo: content.bottomAnchor, constant: -8)])
        window.center(); window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
        startAudio()
        for sig in [SIGTERM, SIGINT] {
            signal(sig, SIG_IGN)
            let source = DispatchSource.makeSignalSource(signal: sig, queue: .main)
            source.setEventHandler { [weak self] in self?.stop() }; source.resume(); signals.append(source)
        }
        timer = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { [weak self] _ in self?.refreshStatus() }
        if options.seconds > 0 { DispatchQueue.main.asyncAfter(deadline: .now() + options.seconds) { self.stop() } }
        if options.controlInput {
            DispatchQueue.global(qos: .utility).async { [self] in
                while let line = readLine() { DispatchQueue.main.async { self.command(line) } }
                DispatchQueue.main.async { self.stop() }
            }
        }
        print("preview_window_created pid=\(getpid())")
        startSource()
    }

    func startAudio() {
        let pcm = audio
        let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 48000, channels: 2, interleaved: false)!
        let node = AVAudioSourceNode(format: format) { silence, _, frames, bufferList in
            let buffers = UnsafeMutableAudioBufferListPointer(bufferList)
            guard buffers.count >= 2, let left = buffers[0].mData, let right = buffers[1].mData else {
                for buffer in buffers { if let data = buffer.mData { memset(data, 0, Int(buffer.mDataByteSize)) } }
                silence.pointee = true; return noErr
            }
            let used = c039_preview_audio_render(pcm, left.assumingMemoryBound(to: Float.self),
                                                right.assumingMemoryBound(to: Float.self), frames)
            silence.pointee = ObjCBool(used == 0)
            return noErr
        }
        engine.attach(node); engine.connect(node, to: engine.mainMixerNode, format: format)
        audioNode = node
        do { try engine.start(); print("preview_audio_started rate=48000 channels=2") }
        catch { audioMessage = "Звук недоступен"; print("preview_audio_error=\(error)") }
    }

    // Capture thread copies only the newest frame. At most one main-queue delivery waits.
    func offer(_ bytes: UnsafePointer<UInt8>, _ count: Int, _ height: UInt32) {
        mailboxLock.lock(); decodedFrames += 1
        let suppress = ProcessInfo.processInfo.systemUptime < suppressedUntil
        mailboxLock.unlock()
        if suppress || count != 1440 * Int(height) { return }
        let index = height == 480 ? 1 : 0
        var pixel: CVPixelBuffer?
        let limits = [kCVPixelBufferPoolAllocationThresholdKey: 4] as CFDictionary
        guard CVPixelBufferPoolCreatePixelBufferWithAuxAttributes(nil, pools[index], limits, &pixel) == kCVReturnSuccess,
              let pixel else { return }
        CVPixelBufferLockBaseAddress(pixel, [])
        let target = CVPixelBufferGetBaseAddress(pixel)!
        let stride = CVPixelBufferGetBytesPerRow(pixel)
        for row in 0..<Int(height) { memcpy(target + row*stride, bytes + row*1440, 1440) }
        CVPixelBufferUnlockBaseAddress(pixel, [])
        mailboxLock.lock(); pendingPixel = pixel
        let schedule = !deliveryScheduled; deliveryScheduled = true
        mailboxLock.unlock()
        if schedule { DispatchQueue.main.async { self.deliver() } }
    }
    func deliver() {
        mailboxLock.lock(); let pixel = pendingPixel; pendingPixel = nil; deliveryScheduled = false
        mailboxLock.unlock()
        guard !closing, let pixel else { return }
        video.pixel = pixel; lastFrame = ProcessInfo.processInfo.systemUptime
        presentedFrames += 1; video.waiting = false; video.needsDisplay = true
    }

    func startSource() {
        guard !closing, !fatalCleanup, session == nil else { return }
        guard let capture = c039_session_create(requestedStandard, 0, 0) else { return }
        session = capture; sourceRuns += 1
        captureMessage = "Подключение USB…"
        c039_session_set_attenuation(capture, options.attenuation)
        c039_session_set_standard_callback(capture, { context, profile in
            guard let context, let profile else { return }
            let owner = Unmanaged<Preview>.fromOpaque(context).takeUnretainedValue()
            c039_frame_decoder_set_height(owner.decoder, profile.pointee.height)
            let name = String(cString: profile.pointee.name).uppercased()
            let height = profile.pointee.height
            DispatchQueue.main.async { owner.formatName = "\(name) · 720×\(height)"; owner.captureMessage = "" }
        })
        print("preview_source_start run=\(sourceRuns) standard=\(requestedStandard)")
        captureQueue.async { [self] in
            let result = c039_session_run(capture, { context, endpoint, bytes, count, _ in
                guard let context, let bytes else { return 0 }
                let owner = Unmanaged<Preview>.fromOpaque(context).takeUnretainedValue()
                if endpoint == 4 { c039_frame_decoder_feed(owner.decoder, bytes, count) }
                else if endpoint == 3 { c039_preview_audio_push(owner.audio, bytes, count) }
                return 0
            }, Unmanaged.passUnretained(self).toOpaque())
            DispatchQueue.main.async { [self] in
                session = nil
                c039_session_destroy(capture)
                print("preview_source_end result=\(result) closing=\(closing ? 1 : 0)")
                if closing { finish(); return }
                if result == 2 {
                    fatalCleanup = true; captureMessage = "Ошибка восстановления USB; захват остановлен"
                } else {
                    captureMessage = "Ожидание устройства…"
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1) { self.startSource() }
                }
            }
        }
    }

    func refreshStatus() {
        let now = ProcessInfo.processInfo.systemUptime
        let waiting = now-lastFrame > 0.75
        if waiting != video.waiting { video.waiting = waiting; video.needsDisplay = true }
        let condition = captureMessage.isEmpty ? (waiting ? "Нет устойчивых кадров" : "Сигнал есть") : captureMessage
        status.stringValue = "\(formatName) · \(condition) · RCA 48 кГц \(audioMessage)"
        if now-lastReport > 2 {
            lastReport = now
            let a = c039_preview_audio_get_stats(audio)
            mailboxLock.lock(); let decoded = decodedFrames; mailboxLock.unlock()
            print("preview_status runs=\(sourceRuns) decoded=\(decoded) presented=\(presentedFrames) waiting=\(waiting ? 1 : 0) audio_in=\(a.input_frames) audio_played=\(a.played_frames) audio_silent=\(a.silent_frames) audio_dropped=\(a.dropped_frames)")
        }
    }
    func command(_ line: String) {
        let words = line.split(separator: " ")
        guard let key = words.first else { return }
        if key == "standard", words.count == 2 {
            let id = String(words[1]).withCString { c039_standard_parse($0) }
            guard id != 0 else { return }
            requestedStandard = id
            standardSelect.selectItem(withTitle: String(words[1]).uppercased())
            captureMessage = "Переключение стандарта…"
            if let session { c039_session_stop(session) } else { startSource() }
        } else if key == "restart" {
            if let session { c039_session_stop(session) } else { startSource() }
        } else if key == "stop" { stop() }
        else if key == "test-video-gap", words.count == 2, let duration = Double(words[1]), (0...300).contains(duration) {
            // Deterministic dropout test: suppress displayed frames, retain USB/audio/window.
            mailboxLock.lock(); suppressedUntil = ProcessInfo.processInfo.systemUptime+duration; mailboxLock.unlock()
            print("preview_test_video_gap seconds=\(duration)")
        }
    }
    @objc func chooseStandard() {
        if let name = standardSelect.selectedItem?.title.lowercased() { command("standard \(name)") }
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool { stop(); return false }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if closing && session == nil { return .terminateNow }
        stop(); return .terminateCancel
    }
    func stop() {
        guard !closing else { return }
        closing = true; captureMessage = "Завершение захвата…"; refreshStatus()
        if let session { c039_session_stop(session) } else { finish() }
    }
    func finish() {
        timer?.invalidate(); engine.stop()
        let a = c039_preview_audio_get_stats(audio)
        print("preview_finished runs=\(sourceRuns) frames=\(presentedFrames) audio_played=\(a.played_frames) audio_dropped=\(a.dropped_frames)")
        NSApp.terminate(nil)
    }
}

@main enum PreviewMain {
    static func main() {
        setvbuf(stdout, nil, _IOLBF, 0)
        let application = NSApplication.shared
        let delegate = Preview(options: Options())
        application.delegate = delegate; application.setActivationPolicy(.regular)
        withExtendedLifetime(delegate) { application.run() }
    }
}
