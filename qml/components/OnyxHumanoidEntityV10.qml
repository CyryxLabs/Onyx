import QtQuick
import QtWebEngine

Item {
    id: entity
    objectName: "onyxHumanoidPresenceV10Root"
    required property var projection
    readonly property bool animated: projection && projection.animationRunning
    readonly property bool reduced: !projection || projection.reducedMotion
    readonly property string operationalState: projection ? projection.state : "OFFLINE"
    readonly property real audio: operationalState === "SPEAKING" ? Math.max(0, Math.min(1, projection.audioLevel)) : 0
    property bool webglReady: false
    property bool webglFailed: false
    property real pendingAttentionX: 0
    property real pendingAttentionY: 0
    property string pendingAttentionSource: "pointer"
    property real deliveredAttentionX: 2
    property real deliveredAttentionY: 2
    property string deliveredAttentionSource: ""

    function syncRenderer() {
        if (!webglReady) return
        var script = "window.OnyxEntity&&window.OnyxEntity.setState("+
            JSON.stringify(operationalState)+","+audio+","+reduced+","+animated+")"
        threeView.runJavaScript(script)
    }

    function setAttention(x, y, source) {
        var boundedX = Math.max(-1, Math.min(1, Number(x) || 0))
        var boundedY = Math.max(-1, Math.min(1, Number(y) || 0))
        var attentionSource = String(source || "pointer")
        pendingAttentionX = boundedX
        pendingAttentionY = boundedY
        pendingAttentionSource = attentionSource
        if (!webglReady) return
        if (Math.abs(boundedX - deliveredAttentionX) < 0.012 &&
                Math.abs(boundedY - deliveredAttentionY) < 0.012 &&
                attentionSource === deliveredAttentionSource)
            return
        if (!attentionFlush.running)
            attentionFlush.start()
    }

    function flushAttention() {
        if (!webglReady) return
        var boundedX = pendingAttentionX
        var boundedY = pendingAttentionY
        var attentionSource = pendingAttentionSource
        deliveredAttentionX = boundedX
        deliveredAttentionY = boundedY
        deliveredAttentionSource = attentionSource
        var script = "window.OnyxEntity&&window.OnyxEntity.setAttention("+
            boundedX+","+boundedY+","+JSON.stringify(attentionSource)+")"
        threeView.runJavaScript(script)
        if (Math.abs(pendingAttentionX - deliveredAttentionX) >= 0.012 ||
                Math.abs(pendingAttentionY - deliveredAttentionY) >= 0.012 ||
                pendingAttentionSource !== deliveredAttentionSource)
            attentionFlush.restart()
    }

    Timer {
        id: attentionFlush
        interval: 66
        repeat: false
        onTriggered: entity.flushAttention()
    }

    WebEngineView {
        id: threeView
        objectName: "onyxHumanoidThreeWebGLV1"
        anchors.fill: parent
        backgroundColor: "transparent"
        url: Qt.resolvedUrl("../web/onyx-humanoid-three-v1.html")
        settings.localContentCanAccessFileUrls: true
        settings.localContentCanAccessRemoteUrls: false
        visible: !entity.webglFailed
        onLoadingChanged: function(request) {
            if (request.status === WebEngineLoadingInfo.LoadSucceededStatus) {
                runJavaScript("Boolean(window.__ONYX_THREE_READY__)", function(ready) {
                    entity.webglReady = ready === true
                    entity.webglFailed = !entity.webglReady
                    entity.syncRenderer()
                    entity.flushAttention()
                })
            } else if (request.status === WebEngineLoadingInfo.LoadFailedStatus) {
                entity.webglReady = false
                entity.webglFailed = true
            }
        }
    }

    // Explicit degraded-mode fallback only. It is never shown when the local
    // Three.js/WebGL renderer has initialized successfully.
    Image {
        id: fallbackPlate
        objectName: "onyxHumanoidWebGLFallbackV1"
        anchors.fill: parent
        visible: entity.webglFailed
        source: "../assets/onyx-humanoid-cyryx-v11.png"
        sourceSize.width: 1680
        sourceSize.height: 941
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: true
    }

    onOperationalStateChanged: syncRenderer()
    onAudioChanged: syncRenderer()
    onReducedChanged: syncRenderer()
    onAnimatedChanged: syncRenderer()
}
