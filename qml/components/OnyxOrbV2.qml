import QtQuick

Item {
    id: root
    objectName: "onyxOrbV2Root"

    required property var projection
    readonly property int boundedNodeCount: Math.min(160, projection.particleBudget)
    readonly property bool simulationRunning: projection.animationRunning
    readonly property int configuredFps: projection.targetFps

    property real phase: 0.0
    property var nodes: []

    function stateEnergy() {
        if (projection.muted || projection.state === "OFFLINE") return 0.10
        if (projection.state === "INITIALISING") return 0.24
        if (projection.state === "LISTENING") return 0.34
        if (projection.state === "THINKING") return 0.62
        if (projection.state === "PROCESSING") return 0.74
        if (projection.state === "SPEAKING") return 0.86 + projection.audioLevel * 0.14
        return 0.18
    }

    function rebuildNodes() {
        var points = []
        var count = boundedNodeCount
        var golden = Math.PI * (3.0 - Math.sqrt(5.0))
        for (var i = 0; i < count; ++i) {
            var y = 1.0 - (i / Math.max(1, count - 1)) * 2.0
            var radius = Math.sqrt(Math.max(0.0, 1.0 - y * y))
            var angle = golden * i
            var shell = (i % 7 === 0) ? 0.68 : (0.88 + (i % 9) * 0.012)
            points.push({
                x: Math.cos(angle) * radius * shell,
                y: y * shell,
                z: Math.sin(angle) * radius * shell,
                seed: (i * 37) % 101,
                energy: i % 13 === 0
            })
        }
        nodes = points
        entity.requestPaint()
    }

    Component.onCompleted: rebuildNodes()
    onBoundedNodeCountChanged: rebuildNodes()

    Timer {
        id: frameClock
        interval: Math.max(33, Math.round(1000 / Math.max(1, root.configuredFps)))
        repeat: true
        running: root.simulationRunning
        onTriggered: {
            var speed = projection.state === "SPEAKING" ? 0.036
                       : projection.state === "THINKING" ? 0.022
                       : projection.state === "PROCESSING" ? 0.026 : 0.012
            root.phase = (root.phase + speed) % (Math.PI * 2)
            entity.requestPaint()
            projection.advance()
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
        anchors.fill: parent
        renderStrategy: Canvas.Threaded

        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            var w = width
            var h = height
            var cx = w * 0.5
            var cy = h * 0.49
            var radius = Math.min(w, h) * 0.31
            var speaking = projection.state === "SPEAKING"
            var thinking = projection.state === "THINKING" || projection.state === "PROCESSING"
            var restrained = projection.muted || projection.state === "OFFLINE"
            var audio = speaking ? projection.audioLevel : 0.0
            var stateEnergy = root.stateEnergy()
            var pulse = 1.0 + audio * 0.055 + (thinking ? Math.sin(root.phase * 2) * 0.012 : 0)
            radius *= pulse

            ctx.clearRect(0, 0, w, h)

            var ambient = ctx.createRadialGradient(cx, cy, radius * 0.28, cx, cy, radius * 1.72)
            ambient.addColorStop(0.0, restrained
                                 ? "rgba(140,148,158,0.07)"
                                 : "rgba(15,107,104," + (0.04 + stateEnergy * 0.10) + ")")
            ambient.addColorStop(0.52, "rgba(17,22,26,0.18)")
            ambient.addColorStop(1.0, "rgba(5,6,7,0.0)")
            ctx.fillStyle = ambient
            ctx.beginPath()
            ctx.arc(cx, cy, radius * 1.72, 0, Math.PI * 2)
            ctx.fill()

            var body = ctx.createRadialGradient(
                cx - radius * 0.30, cy - radius * 0.34, radius * 0.06,
                cx, cy, radius
            )
            body.addColorStop(0.0, "rgba(140,148,158,0.42)")
            body.addColorStop(0.16, "#1B2227")
            body.addColorStop(0.52, "#0A0D0F")
            body.addColorStop(0.83, "#050607")
            body.addColorStop(0.96, "#11161A")
            body.addColorStop(1.0, "rgba(5,6,7,0.12)")
            ctx.fillStyle = body
            ctx.beginPath()
            ctx.arc(cx, cy, radius, 0, Math.PI * 2)
            ctx.fill()

            var caustic = ctx.createRadialGradient(
                cx + radius * 0.28, cy + radius * 0.18, 0,
                cx + radius * 0.28, cy + radius * 0.18, radius * 0.72
            )
            caustic.addColorStop(0.0, restrained
                                 ? "rgba(140,148,158,0.09)"
                                 : "rgba(25,199,192," + (0.05 + stateEnergy * 0.14) + ")")
            caustic.addColorStop(0.34, restrained
                                 ? "rgba(27,34,39,0.08)"
                                 : "rgba(15,107,104," + (0.03 + stateEnergy * 0.07) + ")")
            caustic.addColorStop(1.0, "rgba(5,6,7,0.0)")
            ctx.fillStyle = caustic
            ctx.beginPath()
            ctx.arc(cx, cy, radius * 0.99, 0, Math.PI * 2)
            ctx.fill()

            var rotation = root.phase
            var sine = Math.sin(rotation)
            var cosine = Math.cos(rotation)
            var projected = []
            for (var i = 0; i < root.nodes.length; ++i) {
                var node = root.nodes[i]
                var rx = node.x * cosine + node.z * sine
                var rz = -node.x * sine + node.z * cosine
                var drift = thinking ? Math.sin(rotation * 1.7 + node.seed) * 0.018 : 0
                var perspective = 0.88 + (rz + 1) * 0.07
                projected.push({
                    x: cx + (rx + drift) * radius * perspective,
                    y: cy + node.y * radius * perspective,
                    z: rz,
                    energy: node.energy,
                    seed: node.seed
                })
            }
            projected.sort(function(a, b) { return a.z - b.z })

            ctx.lineWidth = Math.max(0.55, radius / 430)
            for (var f = 0; f < projected.length - 17; f += 19) {
                var a = projected[f]
                var b = projected[f + 17]
                var alpha = restrained ? 0.035 : (a.energy ? 0.16 : 0.055)
                ctx.strokeStyle = a.energy
                    ? "rgba(25,199,192," + alpha + ")"
                    : "rgba(140,148,158," + alpha + ")"
                ctx.beginPath()
                ctx.moveTo(a.x, a.y)
                ctx.quadraticCurveTo(cx, cy, b.x, b.y)
                ctx.stroke()
            }

            for (var p = 0; p < projected.length; ++p) {
                var point = projected[p]
                var depth = Math.max(0.15, (point.z + 1) * 0.5)
                var edge = Math.min(1, Math.hypot(point.x - cx, point.y - cy) / radius)
                var size = 0.62 + depth * 1.18 + (point.energy ? audio * 1.4 : 0)
                var alphaValue = 0.20 + depth * 0.53 + edge * 0.13
                if (restrained)
                    ctx.fillStyle = "rgba(140,148,158," + (alphaValue * 0.56) + ")"
                else if (point.energy)
                    ctx.fillStyle = "rgba(25,199,192," + Math.min(0.92, alphaValue) + ")"
                else if (point.z > 0.32)
                    ctx.fillStyle = "rgba(199,201,204," + Math.min(0.88, alphaValue) + ")"
                else
                    ctx.fillStyle = "rgba(140,148,158," + Math.min(0.74, alphaValue) + ")"
                ctx.beginPath()
                ctx.arc(point.x, point.y, size, 0, Math.PI * 2)
                ctx.fill()
            }

            var rim = ctx.createLinearGradient(cx - radius, cy - radius, cx + radius, cy + radius)
            rim.addColorStop(0.0, "rgba(199,201,204,0.56)")
            rim.addColorStop(0.38, "rgba(140,148,158,0.14)")
            rim.addColorStop(0.72, restrained ? "rgba(27,34,39,0.12)" : "rgba(15,107,104,0.34)")
            rim.addColorStop(1.0, "rgba(5,6,7,0.0)")
            ctx.strokeStyle = rim
            ctx.lineWidth = Math.max(1.0, radius * 0.008)
            ctx.beginPath()
            ctx.arc(cx, cy, radius * 0.985, 0, Math.PI * 2)
            ctx.stroke()
        }
    }
}
