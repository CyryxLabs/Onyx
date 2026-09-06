import QtQuick
import QtWebEngine

Item {
    id: entity
    objectName: "onyxHumanoidPresenceV13Root"
    required property var projection
    readonly property bool animated: projection && projection.animationRunning
    readonly property bool reduced: !projection || projection.reducedMotion
    readonly property string operationalState: projection ? projection.state : "OFFLINE"
    readonly property real audio: operationalState === "SPEAKING" ? Math.max(0, Math.min(1, projection.audioLevel)) : 0
    property bool webglReady: false
    property bool webglFailed: false
    property int readinessAttempts: 0
    property int continuitySlot: 0
    property int pendingContinuitySlot: -1
    property real pendingAttentionX: 0
    property real pendingAttentionY: 0
    property string pendingAttentionSource: "pointer"
    property real deliveredAttentionX: 2
    property real deliveredAttentionY: 2
    property string deliveredAttentionSource: ""

    function syncRenderer() {
        if (!webglReady) return
        threeView.runJavaScript("window.OnyxEntity&&window.OnyxEntity.setState("+
            JSON.stringify(operationalState)+","+audio+","+reduced+","+animated+")")
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
        if (!attentionFlush.running) attentionFlush.start()
    }

    function flushAttention() {
        if (!webglReady) return
        var x = pendingAttentionX
        var y = pendingAttentionY
        var source = pendingAttentionSource
        deliveredAttentionX = x
        deliveredAttentionY = y
        deliveredAttentionSource = source
        threeView.runJavaScript("window.OnyxEntity&&window.OnyxEntity.setAttention("+
            x+","+y+","+JSON.stringify(source)+")")
        if (Math.abs(pendingAttentionX - deliveredAttentionX) >= 0.012 ||
                Math.abs(pendingAttentionY - deliveredAttentionY) >= 0.012 ||
                pendingAttentionSource !== deliveredAttentionSource)
            attentionFlush.restart()
    }

    function probeRenderer() {
        threeView.runJavaScript("Boolean(window.__ONYX_THREE_READY__)", function(ready) {
            if (ready === true) {
                entity.webglReady = true
                entity.webglFailed = false
                readinessProbe.stop()
                entity.syncRenderer()
                entity.flushAttention()
                continuityCapture.restart()
            } else if (++entity.readinessAttempts >= 100) {
                entity.webglReady = false
                entity.webglFailed = true
                readinessProbe.stop()
            }
        })
    }

    function captureContinuityFrame() {
        if (!webglReady) return
        threeView.runJavaScript("window.OnyxEntity&&window.OnyxEntity.captureFrame()", function(frame) {
            if (typeof frame !== "string" || frame.indexOf("data:image/png;base64,") !== 0) return
            if (entity.continuitySlot === 0) {
                entity.pendingContinuitySlot = 1
                continuityB.source = frame
            } else {
                entity.pendingContinuitySlot = 0
                continuityA.source = frame
            }
        })
    }

    Timer { id: attentionFlush; interval: 66; repeat: false; onTriggered: entity.flushAttention() }
    Timer { id: readinessProbe; interval: 100; repeat: true; onTriggered: entity.probeRenderer() }
    Timer { id: continuityCapture; interval: 750; repeat: true; onTriggered: entity.captureContinuityFrame() }

    Image {
        id: continuityA
        objectName: "onyxHumanoidContinuityA"
        anchors.fill: parent
        visible: !entity.webglReady && entity.continuitySlot === 0
        source: ""
        sourceSize.width: 640
        sourceSize.height: 359
        fillMode: Image.PreserveAspectFit
        smooth: true
        asynchronous: true
        cache: false
        onStatusChanged: if (status === Image.Ready && entity.pendingContinuitySlot === 0) {
            entity.continuitySlot = 0
            entity.pendingContinuitySlot = -1
        }
    }

    Image {
        id: continuityB
        objectName: "onyxHumanoidContinuityB"
        anchors.fill: parent
        visible: !entity.webglReady && entity.continuitySlot === 1
        sourceSize.width: 640
        sourceSize.height: 359
        fillMode: Image.PreserveAspectFit
        smooth: true
        asynchronous: true
        cache: false
        onStatusChanged: if (status === Image.Ready && entity.pendingContinuitySlot === 1) {
            entity.continuitySlot = 1
            entity.pendingContinuitySlot = -1
        }
    }

    WebEngineView {
        id: threeView
        objectName: "onyxHumanoidThreeWebGLV5"
        anchors.fill: parent
        backgroundColor: "transparent"
        url: Qt.resolvedUrl("../web/onyx-humanoid-three-v5.html")
        settings.localContentCanAccessFileUrls: true
        settings.localContentCanAccessRemoteUrls: false
        visible: !entity.webglFailed
        onLoadingChanged: function(request) {
            if (request.status === WebEngineLoadingInfo.LoadSucceededStatus) {
                entity.readinessAttempts = 0
                readinessProbe.restart()
                entity.probeRenderer()
            } else if (request.status === WebEngineLoadingInfo.LoadFailedStatus) {
                entity.webglReady = false
                entity.webglFailed = true
                readinessProbe.stop()
                continuityCapture.stop()
            }
        }
    }

    onOperationalStateChanged: syncRenderer()
    onAudioChanged: syncRenderer()
    onReducedChanged: syncRenderer()
    onAnimatedChanged: syncRenderer()
}
