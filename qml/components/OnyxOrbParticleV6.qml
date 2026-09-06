import QtQuick
import QtQuick.Effects

Item {
    id: root
    objectName: "onyxOrbParticleV6Root"

    required property var projection
    readonly property int boundedNodeCount: Math.min(32, projection.particleBudget)
    readonly property bool simulationRunning: projection.animationRunning
    readonly property int configuredFps: projection.targetFps
    property real phase: 0.0
    property real lastFrameAt: 0.0
    property var motes: []

    function rebuildMotes() {
        var next = []
        var golden = Math.PI * (3.0 - Math.sqrt(5.0))
        for (var i = 0; i < boundedNodeCount; ++i) {
            var y = 1.0 - (i / Math.max(1, boundedNodeCount - 1)) * 2.0
            var radial = Math.sqrt(Math.max(0.0, 1.0 - y * y))
            var angle = golden * i
            next.push({
                x: Math.cos(angle) * radial,
                y: y,
                z: Math.sin(angle) * radial,
                active: i % 11 === 0
            })
        }
        motes = next
        presenceField.requestPaint()
    }

    Component.onCompleted: rebuildMotes()
    onBoundedNodeCountChanged: rebuildMotes()

    Image {
        id: particlePresence
        objectName: "onyxParticlePresenceTextureV6"
        anchors.centerIn: parent
        width: Math.min(parent.width, parent.height * 1.16)
        height: width
        source: "../assets/onyx-orb-particle-v6.png"
        sourceSize.width: 1024
        sourceSize.height: 1024
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: true
        cache: true
        visible: false
        opacity: projection.muted || projection.state === "OFFLINE" ? 0.54 : 0.98
    }

    Item {
        id: orbMask
        anchors.fill: particlePresence
        visible: false
        layer.enabled: true
        Rectangle {
            anchors.centerIn: parent
            width: parent.width * 0.78
            height: width
            radius: width / 2
            color: "white"
        }
    }

    MultiEffect {
        objectName: "onyxParticlePresenceMaskV6"
        anchors.fill: particlePresence
        source: particlePresence
        maskEnabled: true
        maskSource: orbMask
        maskThresholdMin: 0.12
        maskSpreadAtMin: 0.08
        opacity: particlePresence.opacity
    }

    Timer {
        id: frameClock
        interval: Math.max(63, Math.round(1000 / Math.max(1, root.configuredFps)))
        repeat: true
        running: root.simulationRunning
        onRunningChanged: if (!running) root.lastFrameAt = 0
        onTriggered: {
            var now = Date.now()
            if (root.lastFrameAt > 0)
                projection.reportFrame(now - root.lastFrameAt)
            root.lastFrameAt = now
            root.phase = (root.phase + 0.012) % (Math.PI * 2)
            presenceField.requestPaint()
            projection.advance()
        }
    }

    Connections {
        target: projection
        function onStateChanged() { presenceField.requestPaint() }
        function onRenderPolicyChanged() { presenceField.requestPaint() }
        function onAudioLevelChanged() { presenceField.requestPaint() }
    }

    Canvas {
        id: presenceField
        objectName: "onyxParticlePresenceFieldV6"
        anchors.centerIn: particlePresence
        width: particlePresence.width
        height: particlePresence.height
        renderStrategy: Canvas.Threaded

        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            ctx.clearRect(0, 0, width, height)
            if (projection.muted || projection.state === "OFFLINE") return

            var cx = width * 0.5
            var cy = height * 0.5
            var radius = Math.min(width, height) * 0.305
            var sine = Math.sin(root.phase)
            var cosine = Math.cos(root.phase)
            var voice = projection.state === "SPEAKING"
                        ? Math.min(1.0, projection.audioLevel) : 0.0
            var projected = []

            for (var i = 0; i < root.motes.length; ++i) {
                var mote = root.motes[i]
                var rx = mote.x * cosine + mote.z * sine
                var rz = -mote.x * sine + mote.z * cosine
                projected.push({
                    x: cx + rx * radius,
                    y: cy + mote.y * radius,
                    z: rz,
                    active: mote.active
                })
            }

            ctx.lineWidth = 0.55
            for (var link = 0; link + 9 < projected.length; link += 10) {
                var a = projected[link]
                var b = projected[link + 9]
                ctx.strokeStyle = a.active
                    ? "rgba(25,199,192,0.10)"
                    : "rgba(199,201,204,0.035)"
                ctx.beginPath()
                ctx.moveTo(a.x, a.y)
                ctx.lineTo(b.x, b.y)
                ctx.stroke()
            }

            for (var point = 0; point < projected.length; ++point) {
                var item = projected[point]
                if (!item.active && point % 4 !== 0) continue
                var alpha = item.active
                    ? 0.20 + voice * 0.18
                    : 0.07 + Math.max(0.0, item.z) * 0.05
                ctx.fillStyle = item.active
                    ? "rgba(25,199,192," + alpha + ")"
                    : "rgba(199,201,204," + alpha + ")"
                ctx.beginPath()
                ctx.arc(item.x, item.y, item.active ? 1.15 : 0.62,
                        0, Math.PI * 2)
                ctx.fill()
            }
        }
    }

}
