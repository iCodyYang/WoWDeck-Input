import QtQuick
import QtQuick.Window
import QtWebEngine

Window {
    id: root
    // Never map a real window if a system wrapper overrides the offscreen platform.
    visible: Qt.platform.pluginName === "offscreen"
    flags: Qt.Tool | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput
    width: 1180
    height: 760
    // Only the local controller supplies these file URLs, under its private runtime directory.
    property string inbox: Qt.resolvedUrl("command.json").toString()
    property int sequence: 0
    property bool pending: false
    property bool streaming: false
    property double pendingSince: 0
    Component.onCompleted: {
        if (Qt.platform.pluginName !== "offscreen") {
            publish("error", "登录组件未进入离屏模式，已停止以避免抢占游戏画面")
            Qt.quit()
        } else publish("stage", "browser_ready")
    }
    function publish(kind, data) {
        console.info("WDI:" + JSON.stringify({kind: kind, data: data}))
    }
    WebEngineProfile {
        id: account
        storageName: "WoWDeckVoice"
        offTheRecord: false
        persistentCookiesPolicy: WebEngineProfile.ForcePersistentCookies
        httpCacheType: WebEngineProfile.MemoryHttpCache
    }
    WebEngineView {
        id: browser
        anchors.fill: parent
        profile: account
        settings.localContentCanAccessFileUrls: false
        settings.localContentCanAccessRemoteUrls: false
        settings.javascriptCanOpenWindows: false
        onNewWindowRequested: function(request) {}
        onJavaScriptConsoleMessage: function(level, message, line, source) {}
        Connections {
            target: browser
            ignoreUnknownSignals: true
            function onPermissionRequested(permission) { permission.deny() }
            function onFeaturePermissionRequested(origin, feature) {
                browser.grantFeaturePermission(origin, feature, false)
            }
        }
        onNavigationRequested: function(request) {
            if (request.isMainFrame && !/^https:\/\/(www|accounts)\.doubao\.com(?=\/|$)/.test(String(request.url)))
                request.reject()
        }
        Component.onCompleted: {
            const bridge = WebEngine.script()
            bridge.name = "wowdeck-voice"
            bridge.sourceUrl = Qt.resolvedUrl("site.js")
            bridge.injectionPoint = WebEngineScript.DocumentCreation
            bridge.worldId = WebEngineScript.MainWorld
            bridge.runsOnSubFrames = false
            userScripts.insert(bridge)
            url = "https://www.doubao.com/chat/"
        }
        onLoadingChanged: function(info) {
            if (info.status === WebEngineView.LoadFailedStatus)
                root.publish("error", "豆包网页加载失败，请检查网络后重试")
            else if (info.status === WebEngineView.LoadSucceededStatus)
                root.publish("stage", "page_loaded")
        }
        onRenderProcessTerminated: function(status, code) {
            root.publish("error", "登录网页渲染进程退出，请检查 Qt WebEngine 组件")
            Qt.quit()
        }
    }
    Timer {
        interval: root.streaming ? 80 : 250; repeat: true; running: true
        onTriggered: {
            if (root.pending) {
                if (Date.now() - root.pendingSince > 10000) {
                    root.publish("error", "登录页面桥接超时，请点击重新连接")
                    Qt.quit()
                }
                return
            }
            root.pending = true
            root.pendingSince = Date.now()
            const req = new XMLHttpRequest()
            req.open("GET", root.inbox)
            req.onreadystatechange = function() {
                if (req.readyState !== XMLHttpRequest.DONE) return
                let cmd = null
                try { cmd = JSON.parse(req.responseText) } catch (_) {}
                if (cmd && cmd.action === "shutdown") { Qt.quit(); return }
                let input = null
                if (cmd && cmd.seq > root.sequence) {
                    input = cmd
                }
                const expression = "location.origin === 'https://www.doubao.com' && window.__wdi && window.__wdi(" + JSON.stringify(input) + ")"
                browser.runJavaScript(expression, function(result) {
                    root.pending = false
                    if (typeof result === "string" && result.length < 280000) {
                        if (input) root.sequence = input.seq
                        try { root.streaming = JSON.parse(result).streaming === true } catch (_) {}
                        root.publish("state", result)
                    }
                })
            }
            req.send()
        }
    }
}
