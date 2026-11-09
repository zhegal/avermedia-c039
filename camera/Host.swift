// SPDX-License-Identifier: GPL-2.0-or-later
import AppKit
import SystemExtensions

final class App: NSObject, NSApplicationDelegate, OSSystemExtensionRequestDelegate {
    var window: NSWindow!
    let status = NSTextField(wrappingLabelWithString: "Камера ещё не активирована этим приложением.")
    let identifier = "io.github.zhegal.C039.Camera"
    func applicationDidFinishLaunching(_ notification: Notification) {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 540, height: 250),
            styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "AVerMedia C039"
        let title = NSTextField(labelWithString: "Системная камера AVerMedia C039")
        title.font = .boldSystemFont(ofSize: 20)
        let detail = NSTextField(wrappingLabelWithString:
            "Composite · Auto PAL / SECAM / NTSC\nИсходные UYVY-кадры без масштабирования.\nЗакройте другие программы прямого USB-захвата перед проверкой камеры.")
        let activate = NSButton(title: "Активировать камеру", target: self, action: #selector(activateCamera))
        let remove = NSButton(title: "Деактивировать", target: self, action: #selector(removeCamera))
        let buttons = NSStackView(views: [activate, remove]); buttons.orientation = .horizontal
        let stack = NSStackView(views: [title, detail, buttons, status])
        stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 16
        stack.translatesAutoresizingMaskIntoConstraints = false
        window.contentView!.addSubview(stack)
        NSLayoutConstraint.activate([stack.leadingAnchor.constraint(equalTo: window.contentView!.leadingAnchor, constant: 24),
            stack.trailingAnchor.constraint(equalTo: window.contentView!.trailingAnchor, constant: -24),
            stack.topAnchor.constraint(equalTo: window.contentView!.topAnchor, constant: 24)])
        window.center(); window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
        if CommandLine.arguments.contains("--activate") { activateCamera() }
    }
    @objc func activateCamera() {
        let request = OSSystemExtensionRequest.activationRequest(forExtensionWithIdentifier: identifier, queue: .main)
        request.delegate = self; status.stringValue = "Проверка подписи и активация…"
        OSSystemExtensionManager.shared.submitRequest(request)
    }
    @objc func removeCamera() {
        let request = OSSystemExtensionRequest.deactivationRequest(forExtensionWithIdentifier: identifier, queue: .main)
        request.delegate = self; OSSystemExtensionManager.shared.submitRequest(request)
    }
    func requestNeedsUserApproval(_ request: OSSystemExtensionRequest) {
        status.stringValue = "Разрешите AVerMedia C039 в настройках macOS → Основные → Объекты входа и расширения → Расширения камеры."
        print("camera_activation=needs_user_approval")
    }
    func request(_ request: OSSystemExtensionRequest, didFinishWithResult result: OSSystemExtensionRequest.Result) {
        status.stringValue = result == .completed ? "Запрос выполнен. Проверьте список устройств захвата." : "Для завершения macOS требует перезагрузку."
        print("camera_activation=result_\(result.rawValue)")
    }
    func request(_ request: OSSystemExtensionRequest, didFailWithError error: Error) {
        status.stringValue = error.localizedDescription
        print("camera_activation=failed \(error as NSError)")
    }
    func request(_ request: OSSystemExtensionRequest, actionForReplacingExtension existing: OSSystemExtensionProperties,
                 withExtension replacement: OSSystemExtensionProperties) -> OSSystemExtensionRequest.ReplacementAction { .replace }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

@main enum HostMain {
    static func main() {
        let app = NSApplication.shared
        let delegate = App()
        app.delegate = delegate
        app.setActivationPolicy(.regular)
        withExtendedLifetime(delegate) { app.run() }
    }
}
