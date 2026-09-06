import QtQuick

Item {
    id: root
    objectName: "onyxOrbCinematicV4Root"

    required property var projection
    readonly property int boundedNodeCount: Math.min(64, projection.particleBudget)
    readonly property bool simulationRunning: projection.animationRunning
    readonly property int configuredFps: projection.targetFps
    property real phase: 0.0
    property real lastFrameAt: 0.0
    property var nodes: []

    function rebuildNodes() {
        var result = []
        var golden = Math.PI * (3.0 - Math.sqrt(5.0))
        for (var i = 0; i < boundedNodeCount; ++i) {
            var y = 1.0 - (i / Math.max(1, boundedNodeCount - 1)) * 2.0
            var ring = Math.sqrt(Math.max(0.0, 1.0 - y * y))
            var angle = golden * i
            result.push({
                x: Math.cos(angle) * ring * 0.91,
                y: y * 0.91,
                z: Math.sin(angle) * ring * 0.91,
                hot: i % 13 === 0
            })
        }
        nodes = result
        energyLayer.requestPaint()
    }

    Component.onCompleted: rebuildNodes()
    onBoundedNodeCountChanged: rebuildNodes()

    Image {
        id: orbTexture
        objectName: "cinematicOrbTextureV4"
        anchors.fill: parent
        source: "../assets/onyx-orb-cinematic-v3.png"
        sourceSize.width: 1024
        sourceSize.height: 1024
        fillMode: Image.PreserveAspectCrop
        smooth: true
        mipmap: true
        cache: true
        opacity: projection.muted || projection.state === "OFFLINE" ? 0.56 : 0.96
    }

    // Edge fades blend the photographic plate into the official Onyx surface.
    Rectangle {
        anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom
        width: Math.max(72, parent.width * 0.16)
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "#050607" }
            GradientStop { position: 1.0; color: "transparent" }
        }
    }
    Rectangle {
        anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom
        width: Math.max(72, parent.width * 0.16)
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "transparent" }
            GradientStop { position: 1.0; color: "#050607" }
        }
    }
    Rectangle {
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        height: Math.max(48, parent.height * 0.12)
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#050607" }
            GradientStop { position: 1.0; color: "transparent" }
        }
    }
    Rectangle {
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        height: Math.max(48, parent.height * 0.12)
        gradient: Gradient {
            GradientStop { position: 0.0; color: "transparent" }
            GradientStop { position: 1.0; color: "#050607" }
        }
    }

    Timer {
        id: frameClock
        interval: Math.max(63, Math.round(1000 / Math.max(1, root.configuredFps)))
        repeat: true
        running: root.simulationRunning
        onRunningChanged: if (!running) root.lastFrameAt = 0
        onTriggered: {
            var now = Date.now()
            if (root.lastFrameAt > 0) projection.reportFrame(now - root.lastFrameAt)
            root.lastFrameAt = now
            root.phase = (root.phase + 0.018) % (Math.PI * 2)
            energyLayer.requestPaint()
            projection.advance()
        }
    }

    Connections {
        target: projection
        function onStateChanged() { energyLayer.requestPaint() }
        function onRenderPolicyChanged() { energyLayer.requestPaint() }
        function onAudioLevelChanged() { energyLayer.requestPaint() }
    }

    // Transparent additive overlay only: the photographic Orb remains authoritative.
    Canvas {
        id: energyLayer
        objectName: "cinematicOrbEnergyLayerV4"
        anchors.fill: parent
        renderStrategy: Canvas.Threaded

        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            ctx.clearRect(0, 0, width, height)
            if (projection.muted || projection.state === "OFFLINE") return

            var cx = width * 0.5
            var cy = height * 0.48
            var radius = Math.min(width, height) * 0.275
            var sine = Math.sin(root.phase)
            var cosine = Math.cos(root.phase)
            var audio = projection.state === "SPEAKING" ? projection.audioLevel : 0.0
            var projected = []
            for (var i = 0; i < root.nodes.length; ++i) {
                var node = root.nodes[i]
                var rx = node.x * cosine + node.z * sine
                var rz = -node.x * sine + node.z * cosine
                var perspective = 0.90 + (rz + 1.0) * 0.05
                projected.push({
                    x: cx + rx * radius * perspective,
                    y: cy + node.y * radius * perspective,
                    z: rz,
                    hot: node.hot
                })
            }
            projected.sort(function(a, b) { return a.z - b.z })

            ctx.lineWidth = 0.55
            for (var line = 0; line < projected.length - 17; line += 19) {
                var a = projected[line]
                var b = projected[line + 17]
                ctx.strokeStyle = a.hot
                    ? "rgba(25,199,192,0.10)" : "rgba(199,201,204,0.025)"
                ctx.beginPath()
                ctx.moveTo(a.x, a.y)
                ctx.quadraticCurveTo(cx, cy, b.x, b.y)
                ctx.stroke()
            }

            for (var pointIndex = 0; pointIndex < projected.length; ++pointIndex) {
                var point = projected[pointIndex]
                if (!point.hot && pointIndex % 3 !== 0) continue
                var depth = Math.max(0.12, (point.z + 1.0) * 0.5)
                var alpha = point.hot ? 0.18 + audio * 0.18 : 0.08 + depth * 0.06
                ctx.fillStyle = point.hot
                    ? "rgba(25,199,192," + alpha + ")"
                    : "rgba(199,201,204," + alpha + ")"
                ctx.beginPath()
                ctx.arc(point.x, point.y, point.hot ? 1.15 : 0.62, 0, Math.PI * 2)
                ctx.fill()
            }
        }
    }
}
