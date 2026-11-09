// SPDX-License-Identifier: GPL-2.0-or-later
import Foundation
import CoreMediaIO
import CoreVideo
import IOKit.audio
import os

private let log = Logger(subsystem: "io.github.zhegal.C039.Camera", category: "capture")

final class CameraDevice: NSObject, CMIOExtensionDeviceSource {
    let queue = DispatchQueue(label: "C039.camera", qos: .userInteractive)
    let captureQueue = DispatchQueue(label: "C039.usb", qos: .userInteractive)
    var device: CMIOExtensionDevice!
    var source: CameraStream!
    var session: OpaquePointer?
    var decoder: OpaquePointer!
    var clients = 0
    var timer: DispatchSourceTimer?
    var formatIndex = 0
    let lock = NSLock()
    var latest: CVPixelBuffer?
    var pools: [CVPixelBufferPool] = []
    var descriptions: [CMVideoFormatDescription] = []

    override init() {
        super.init()
        device = CMIOExtensionDevice(localizedName: "AVerMedia C039", deviceID:
            UUID(uuidString: "9CA364F8-DB14-43BA-81CE-C03900000001")!, legacyDeviceID: nil, source: self)
        for height in [576, 480] {
            var description: CMVideoFormatDescription?
            let extensions: [CFString: Any] = [kCMFormatDescriptionExtension_FieldCount: 2,
                kCMFormatDescriptionExtension_YCbCrMatrix: kCMFormatDescriptionYCbCrMatrix_ITU_R_601_4]
            precondition(CMVideoFormatDescriptionCreate(allocator: nil, codecType: kCVPixelFormatType_422YpCbCr8,
                width: 720, height: Int32(height), extensions: extensions as CFDictionary,
                formatDescriptionOut: &description) == noErr)
            descriptions.append(description!)
            var pool: CVPixelBufferPool?
            let attributes: [CFString: Any] = [kCVPixelBufferWidthKey: 720, kCVPixelBufferHeightKey: height,
                kCVPixelBufferPixelFormatTypeKey: kCVPixelFormatType_422YpCbCr8,
                kCVPixelBufferIOSurfacePropertiesKey: [:]]
            precondition(CVPixelBufferPoolCreate(nil, nil, attributes as CFDictionary, &pool) == kCVReturnSuccess)
            pools.append(pool!)
        }
        decoder = c039_frame_decoder_create(576, { context, bytes, count, height in
            guard let context, let bytes else { return }
            Unmanaged<CameraDevice>.fromOpaque(context).takeUnretainedValue().frame(bytes, count, height)
        }, Unmanaged.passUnretained(self).toOpaque())
        precondition(decoder != nil)
        source = CameraStream(owner: self)
        try! device.addStream(source.stream)
    }

    var availableProperties: Set<CMIOExtensionProperty> { [.deviceTransportType, .deviceModel] }
    func deviceProperties(forProperties properties: Set<CMIOExtensionProperty>) throws -> CMIOExtensionDeviceProperties {
        let result = CMIOExtensionDeviceProperties(dictionary: [:])
        result.transportType = kIOAudioDeviceTransportTypeUSB
        result.model = "AVerMedia USB Polaris C039 / CX23102"
        return result
    }
    func setDeviceProperties(_ properties: CMIOExtensionDeviceProperties) throws {}

    func frame(_ bytes: UnsafePointer<UInt8>, _ count: Int, _ height: UInt32) {
        let index = height == 480 ? 1 : 0
        guard count == 720 * Int(height) * 2 else { return }
        var pixel: CVPixelBuffer?
        let limits = [kCVPixelBufferPoolAllocationThresholdKey: 5] as CFDictionary
        guard CVPixelBufferPoolCreatePixelBufferWithAuxAttributes(nil, pools[index], limits, &pixel) == kCVReturnSuccess,
              let pixel else { return }
        CVPixelBufferLockBaseAddress(pixel, [])
        let target = CVPixelBufferGetBaseAddress(pixel)!
        let stride = CVPixelBufferGetBytesPerRow(pixel)
        for row in 0..<Int(height) { memcpy(target + row * stride, bytes + row * 1440, 1440) }
        CVPixelBufferUnlockBaseAddress(pixel, [])
        lock.lock(); latest = pixel; lock.unlock()
    }

    func begin() {
        clients += 1
        guard clients == 1 else { return }
        scheduleTimer(index: formatIndex)
        startCapture()
    }
    func end() {
        clients = max(0, clients - 1)
        guard clients == 0 else { return }
        timer?.cancel(); timer = nil
        if let session { c039_session_stop(session) }
        lock.lock(); latest = nil; lock.unlock()
    }
    func startCapture() {
        guard clients > 0, session == nil else { return }
        guard let capture = c039_session_create(UInt32(C039_AUTO), 4, 0) else { return }
        session = capture
        c039_session_set_standard_callback(capture, { context, profile in
            guard let context, let profile else { return }
            let owner = Unmanaged<CameraDevice>.fromOpaque(context).takeUnretainedValue()
            c039_frame_decoder_set_height(owner.decoder, profile.pointee.height)
        })
        captureQueue.async { [self] in
            let code = c039_session_run(capture, { context, endpoint, bytes, count, _ in
                guard endpoint == 4, let context else { return 0 }
                let owner = Unmanaged<CameraDevice>.fromOpaque(context).takeUnretainedValue()
                c039_frame_decoder_feed(owner.decoder, bytes, count)
                return 0
            }, Unmanaged.passUnretained(self).toOpaque())
            c039_session_destroy(capture)
            queue.async { [self] in
                session = nil
                log.info("USB capture returned \(code)")
                // Retry only after the previous run has restored and closed USB.
                if clients > 0 && code != 2 {
                    queue.asyncAfter(deadline: .now() + 2) { self.startCapture() }
                }
            }
        }
    }
    func scheduleTimer(index: Int) {
        timer?.cancel()
        let next = DispatchSource.makeTimerSource(queue: queue)
        next.schedule(deadline: .now(), repeating: index == 0 ? 0.04 : 1001.0 / 30000.0)
        next.setEventHandler { [weak self] in self?.send() }
        timer = next; next.resume()
    }
    func send() {
        lock.lock(); let pixel = latest; lock.unlock()
        guard let pixel else { return }
        let index = CVPixelBufferGetHeight(pixel) == 480 ? 1 : 0
        if index != formatIndex {
            formatIndex = index
            source.stream.notifyPropertiesChanged([
                .streamActiveFormatIndex: CMIOExtensionPropertyState<AnyObject>(value: NSNumber(value: index)),
                .streamFrameDuration: CMIOExtensionPropertyState<AnyObject>(value:
                    CMTimeCopyAsDictionary(source.duration, allocator: nil)!)])
            scheduleTimer(index: index)
        }
        let now = CMClockGetTime(CMClockGetHostTimeClock())
        var timing = CMSampleTimingInfo(duration: source.duration, presentationTimeStamp: now, decodeTimeStamp: .invalid)
        var sample: CMSampleBuffer?
        if CMSampleBufferCreateForImageBuffer(allocator: nil, imageBuffer: pixel, dataReady: true,
            makeDataReadyCallback: nil, refcon: nil, formatDescription: descriptions[index],
            sampleTiming: &timing, sampleBufferOut: &sample) == noErr, let sample {
            source.stream.send(sample, discontinuity: [], hostTimeInNanoseconds: UInt64(now.seconds * 1e9))
        }
    }
}

final class CameraStream: NSObject, CMIOExtensionStreamSource {
    unowned let owner: CameraDevice
    var stream: CMIOExtensionStream!
    init(owner: CameraDevice) {
        self.owner = owner
        super.init()
        stream = CMIOExtensionStream(localizedName: "C039 Composite", streamID:
            UUID(uuidString: "9CA364F8-DB14-43BA-81CE-C03900000002")!, direction: .source, clockType: .hostTime, source: self)
    }
    var formats: [CMIOExtensionStreamFormat] {
        owner.descriptions.enumerated().map { index, description in
            let time = index == 0 ? CMTime(value: 1, timescale: 25) : CMTime(value: 1001, timescale: 30000)
            return CMIOExtensionStreamFormat(formatDescription: description, maxFrameDuration: time,
                minFrameDuration: time, validFrameDurations: nil)
        }
    }
    var duration: CMTime { owner.formatIndex == 0 ? CMTime(value: 1, timescale: 25) : CMTime(value: 1001, timescale: 30000) }
    var availableProperties: Set<CMIOExtensionProperty> { [.streamActiveFormatIndex, .streamFrameDuration] }
    func streamProperties(forProperties properties: Set<CMIOExtensionProperty>) throws -> CMIOExtensionStreamProperties {
        let result = CMIOExtensionStreamProperties(dictionary: [:])
        result.activeFormatIndex = owner.formatIndex; result.frameDuration = duration
        return result
    }
    func setStreamProperties(_ properties: CMIOExtensionStreamProperties) throws {
        // Geometry follows the analog input; publishing changes is owned by send().
        if let index = properties.activeFormatIndex, index != owner.formatIndex {
            throw NSError(domain: NSOSStatusErrorDomain, code: Int(kCMIOHardwareUnsupportedOperationError))
        }
    }
    func authorizedToStartStream(for client: CMIOExtensionClient) -> Bool { true }
    func startStream() throws { owner.begin() }
    func stopStream() throws { owner.end() }
}

final class CameraProvider: NSObject, CMIOExtensionProviderSource {
    var provider: CMIOExtensionProvider!
    let camera = CameraDevice()
    override init() {
        super.init()
        provider = CMIOExtensionProvider(source: self, clientQueue: camera.queue)
        try! provider.addDevice(camera.device)
    }
    var availableProperties: Set<CMIOExtensionProperty> { [.providerManufacturer] }
    func providerProperties(forProperties properties: Set<CMIOExtensionProperty>) throws -> CMIOExtensionProviderProperties {
        let result = CMIOExtensionProviderProperties(dictionary: [:]); result.manufacturer = "C039 macOS project"
        return result
    }
    func setProviderProperties(_ properties: CMIOExtensionProviderProperties) throws {}
    func connect(to client: CMIOExtensionClient) throws {}
    func disconnect(from client: CMIOExtensionClient) {}
}

@main enum CameraMain {
    static func main() {
        let service = CameraProvider()
        CMIOExtensionProvider.startService(provider: service.provider)
        withExtendedLifetime(service) { CFRunLoopRun() }
    }
}
