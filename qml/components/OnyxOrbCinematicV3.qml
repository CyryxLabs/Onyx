import QtQuick

Item {
    id: root
    objectName: "onyxOrbCinematicV3Root"

    required property var projection
    readonly property int boundedNodeCount: Math.min(128, projection.particleBudget)
    readonly property bool simulationRunning: projection.animationRunning
    readonly property int configuredFps: projection.targetFps
    property real phase: 0.0
    property real lastFrameAt: 0.0
    property var nodes: []

    function energy() {
        if (projection.muted || projection.state === "OFFLINE") return 0.10
        if (projection.state === "SPEAKING") return 0.86 + projection.audioLevel * 0.14
        if (projection.state === "PROCESSING") return 0.72
        if (projection.state === "THINKING") return 0.62
        if (projection.state === "LISTENING") return 0.34
        return 0.20
    }

    function rebuildNodes() {
        var result = []
        var golden = Math.PI * (3.0 - Math.sqrt(5.0))
        for (var i = 0; i < boundedNodeCount; ++i) {
            var y = 1.0 - (i / Math.max(1, boundedNodeCount - 1)) * 2.0
            var ring = Math.sqrt(Math.max(0.0, 1.0 - y * y))
            var angle = golden * i
            var shell = i % 9 === 0 ? 0.63 : 0.90 + (i % 7) * 0.012
            result.push({
                x: Math.cos(angle) * ring * shell,
                y: y * shell,
                z: Math.sin(angle) * ring * shell,
                seed: (i * 47) % 127,
                hot: i % 11 === 0
            })
        }
        nodes = result
        entity.requestPaint()
    }

    Component.onCompleted: rebuildNodes()
    onBoundedNodeCountChanged: rebuildNodes()

    Timer {
        id: frameClock
        interval: Math.max(42, Math.round(1000 / Math.max(1, root.configuredFps)))
        repeat: true
        running: root.simulationRunning
        onRunningChanged: if (!running) root.lastFrameAt = 0
        onTriggered: {
            var now = Date.now()
            if (root.lastFrameAt > 0) projection.reportFrame(now - root.lastFrameAt)
            root.lastFrameAt = now
            var speed = projection.state === "SPEAKING" ? 0.030
                      : projection.state === "PROCESSING" ? 0.022
                      : projection.state === "THINKING" ? 0.018 : 0.010
            root.phase = (root.phase + speed) % (Math.PI * 2)
            entity.requestPaint()
            projection.advance()
        }
    }

    Item {
        id: staticPresence
        anchors.centerIn: parent
        width: Math.min(root.width, root.height) * 0.70
        height: width
        opacity: orbTexture.status === Image.Ready ? 0.10 : 1.0

        Rectangle {
            anchors.centerIn: parent
            width: parent.width * 1.38
            height: width
            radius: width / 2
            color: "transparent"
            border.width: 1
            border.color: projection.muted ? "#1B2227" : "#0F6B68"
            opacity: projection.muted ? 0.18 : 0.34
        }
        Rectangle {
            anchors.centerIn: parent
            width: parent.width
            height: width
            radius: width / 2
            border.width: Math.max(1, width * 0.007)
            border.color: projection.muted ? "#8C949E" : "#19C7C0"
            gradient: Gradient {
                GradientStop { position: 0.0; color: projection.muted ? "#8C949E" : "#C7C9CC" }
                GradientStop { position: 0.16; color: projection.muted ? "#1B2227" : "#0F6B68" }
                GradientStop { position: 0.48; color: "#0A0D0F" }
                GradientStop { position: 0.78; color: "#050607" }
                GradientStop { position: 1.0; color: projection.muted ? "#11161A" : "#0F6B68" }
            }
            opacity: 0.78
        }
        Rectangle {
            anchors.centerIn: parent
            anchors.horizontalCenterOffset: -parent.width * 0.13
            anchors.verticalCenterOffset: -parent.height * 0.16
            width: parent.width * 0.12
            height: width
            radius: width / 2
            color: projection.muted ? "#8C949E" : "#C7C9CC"
            opacity: projection.muted ? 0.20 : 0.48
        }
    }

    Image {
        id: orbTexture
        objectName: "cinematicOrbTextureV3"
        anchors.fill: parent
        source: "../assets/onyx-orb-cinematic-v3.png"
        sourceSize.width: 1024
        sourceSize.height: 1024
        fillMode: Image.PreserveAspectCrop
        smooth: true
        mipmap: true
        cache: true
        opacity: projection.muted || projection.state === "OFFLINE" ? 0.58 : 0.96
    }

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

    Connections {
        target: projection
        function onStateChanged() { entity.requestPaint() }
        function onRenderPolicyChanged() { entity.requestPaint() }
        function onAudioLevelChanged() { entity.requestPaint() }
    }

    Canvas {
        id: entity
        objectName: "cinematicOrbCanvasV3"
        anchors.fill: parent
        renderStrategy: Canvas.Threaded

        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            var w = width
            var h = height
            var cx = w * 0.50
            var cy = h * 0.48
            var radius = Math.min(w, h) * 0.335
            var active = !(projection.muted || projection.state === "OFFLINE")
            var speaking = projection.state === "SPEAKING"
            var working = projection.state === "THINKING" || projection.state === "PROCESSING"
            var audio = speaking ? projection.audioLevel : 0.0
            var intensity = root.energy()
            var breath = working ? Math.sin(root.phase * 2.1) * 0.010 : 0
            radius *= 1.0 + breath + audio * 0.045
            ctx.clearRect(0, 0, w, h)

            var atmosphere = ctx.createRadialGradient(cx, cy, radius * 0.18, cx, cy, radius * 1.82)
            atmosphere.addColorStop(0.0, active ? "rgba(25,199,192,0.30)" : "rgba(140,148,158,0.11)")
            atmosphere.addColorStop(0.30, active ? "rgba(15,107,104,0.15)" : "rgba(27,34,39,0.10)")
            atmosphere.addColorStop(0.70, "rgba(10,13,15,0.06)")
            atmosphere.addColorStop(1.0, "rgba(5,6,7,0)")
            ctx.fillStyle = atmosphere
            ctx.beginPath()
            ctx.arc(cx, cy, radius * 1.82, 0, Math.PI * 2)
            ctx.fill()

            var body = ctx.createRadialGradient(
                cx - radius * 0.28, cy - radius * 0.34, radius * 0.02,
                cx, cy, radius
            )
            body.addColorStop(0.0, "rgba(231,236,238,0.92)")
            body.addColorStop(0.08, active ? "rgba(25,199,192,0.52)" : "rgba(140,148,158,0.24)")
            body.addColorStop(0.29, "rgba(27,34,39,0.98)")
            body.addColorStop(0.63, "rgba(5,6,7,1.0)")
            body.addColorStop(0.86, active ? "rgba(15,107,104,0.54)" : "rgba(27,34,39,0.42)")
            body.addColorStop(1.0, "rgba(5,6,7,0.08)")
            ctx.fillStyle = body
            ctx.beginPath()
            ctx.arc(cx, cy, radius, 0, Math.PI * 2)
            ctx.fill()

            var inner = ctx.createRadialGradient(
                cx + radius * 0.24, cy + radius * 0.19, 0,
                cx + radius * 0.18, cy + radius * 0.16, radius * 0.68
            )
            inner.addColorStop(0.0, active
                ? "rgba(25,199,192," + (0.18 + intensity * 0.34) + ")"
                : "rgba(140,148,158,0.08)")
            inner.addColorStop(0.42, active ? "rgba(15,107,104,0.08)" : "rgba(27,34,39,0.05)")
            inner.addColorStop(1.0, "rgba(5,6,7,0)")
            ctx.fillStyle = inner
            ctx.beginPath()
            ctx.arc(cx, cy, radius * 0.99, 0, Math.PI * 2)
            ctx.fill()

            var core = ctx.createRadialGradient(cx - radius * 0.08, cy - radius * 0.11, 0,
                                                cx - radius * 0.04, cy - radius * 0.06, radius * 0.31)
            core.addColorStop(0.0, active ? "rgba(225,255,253,0.88)" : "rgba(199,201,204,0.34)")
            core.addColorStop(0.10, active ? "rgba(25,199,192,0.42)" : "rgba(140,148,158,0.16)")
            core.addColorStop(0.52, active ? "rgba(15,107,104,0.11)" : "rgba(27,34,39,0.07)")
            core.addColorStop(1.0, "rgba(5,6,7,0)")
            ctx.fillStyle = core
            ctx.beginPath()
            ctx.arc(cx - radius * 0.04, cy - radius * 0.06, radius * 0.31, 0, Math.PI * 2)
            ctx.fill()

            var sine = Math.sin(root.phase)
            var cosine = Math.cos(root.phase)
            var projected = []
            for (var i = 0; i < root.nodes.length; ++i) {
                var node = root.nodes[i]
                var rx = node.x * cosine + node.z * sine
                var rz = -node.x * sine + node.z * cosine
                var current = working ? Math.sin(root.phase * 1.8 + node.seed) * 0.014 : 0
                var perspective = 0.88 + (rz + 1) * 0.07
                projected.push({
                    x: cx + (rx + current) * radius * perspective,
                    y: cy + node.y * radius * perspective,
                    z: rz,
                    hot: node.hot
                })
            }
            projected.sort(function(a, b) { return a.z - b.z })

            for (var c = 0; c < projected.length - 23; c += 17) {
                var a = projected[c]
                var b = projected[c + 23]
                ctx.strokeStyle = active
                    ? "rgba(25,199,192," + (a.hot ? 0.16 : 0.045) + ")"
                    : "rgba(140,148,158,0.035)"
                ctx.lineWidth = Math.max(0.5, radius / 520)
                ctx.beginPath()
                ctx.moveTo(a.x, a.y)
                ctx.quadraticCurveTo(cx, cy, b.x, b.y)
                ctx.stroke()
            }

            for (var p = 0; p < projected.length; ++p) {
                var point = projected[p]
                var depth = Math.max(0.12, (point.z + 1) * 0.5)
                var size = 0.55 + depth * 1.20 + (point.hot ? audio * 1.2 : 0)
                var alpha = 0.28 + depth * 0.66
                ctx.fillStyle = !active
                    ? "rgba(140,148,158," + (alpha * 0.46) + ")"
                    : point.hot
                        ? "rgba(25,199,192," + Math.min(0.94, alpha) + ")"
                        : point.z > 0.28
                            ? "rgba(199,201,204," + Math.min(0.84, alpha) + ")"
                            : "rgba(140,148,158," + Math.min(0.70, alpha) + ")"
                ctx.beginPath()
                ctx.arc(point.x, point.y, size, 0, Math.PI * 2)
                ctx.fill()
            }

            var rim = ctx.createLinearGradient(cx - radius, cy - radius, cx + radius, cy + radius)
            rim.addColorStop(0.0, "rgba(225,231,234,0.92)")
            rim.addColorStop(0.28, "rgba(140,148,158,0.24)")
            rim.addColorStop(0.72, active ? "rgba(25,199,192,0.62)" : "rgba(27,34,39,0.22)")
            rim.addColorStop(1.0, "rgba(5,6,7,0)")
            ctx.strokeStyle = rim
            ctx.lineWidth = Math.max(1.0, radius * 0.008)
            ctx.beginPath()
            ctx.arc(cx, cy, radius * 0.992, 0, Math.PI * 2)
            ctx.stroke()

            ctx.strokeStyle = active ? "rgba(25,199,192,0.13)" : "rgba(140,148,158,0.06)"
            ctx.lineWidth = 1
            ctx.beginPath()
            ctx.ellipse(cx, cy, radius * 1.17, radius * 0.37, -0.24 + root.phase * 0.10, 0, Math.PI * 2)
            ctx.stroke()
            ctx.beginPath()
            ctx.ellipse(cx, cy, radius * 1.12, radius * 0.32, 1.12 - root.phase * 0.07, 0, Math.PI * 2)
            ctx.stroke()
        }
    }
}
