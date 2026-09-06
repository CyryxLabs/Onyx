import QtQuick

OnyxLiveShellV8 {
    id: root
    objectName: "onyxLiveShellV9Root"

    function findObject(node, targetName) {
        if (!node)
            return null
        if (node.objectName === targetName)
            return node
        var descendants = node.children
        if (!descendants)
            return null
        for (var index = 0; index < descendants.length; ++index) {
            var match = findObject(descendants[index], targetName)
            if (match)
                return match
        }
        return null
    }

    function removeDecorativeKeelArcs() {
        var commandInput = findObject(root, "liveCommandInputV7")
        if (!commandInput || !commandInput.parent)
            throw new Error("Onyx command surface contract is unavailable")
        var siblings = commandInput.parent.children
        var removed = 0
        for (var index = 0; index < siblings.length; ++index) {
            var candidate = siblings[index]
            if (candidate && typeof candidate.requestPaint === "function") {
                candidate.visible = false
                removed += 1
            }
        }
        if (removed !== 1)
            throw new Error("Onyx decorative arc contract drifted")
    }

    // The V7 action-status line ("COMMAND ACCEPTED", state label) sits at
    // y = height*.63 — over the lower orb. Lift it out of the orb into the band
    // below the sphere so it never overlays the entity.
    function moveStatusBelowOrb() {
        for (var i = 0; i < root.children.length; ++i) {
            var ch = root.children[i]
            if (ch && typeof ch.text === "string"
                    && Math.abs(ch.y - root.height * .63) < root.height * .03) {
                ch.y = root.height * .80
                return
            }
        }
    }

    Component.onCompleted: {
        removeDecorativeKeelArcs()
        moveStatusBelowOrb()
    }

    // Read-only, owner-invoked projection of goals, attention and automation.
    // This pill performs no polling and owns no execution authority.
    Item {
        id: operationsPill
        objectName: "onyxAdvancedOperationsPillV9"
        visible: !root.compact && root.uiProjection !== null
        anchors.right: parent.right
        anchors.rightMargin: 42 * root.scaleUnit
        y: root.height * .17
        width: operationsText.implicitWidth + 26
        height: 28
        z: 8
        Accessible.role: Accessible.Button
        Accessible.name: "Show Onyx advanced operations"

        Rectangle {
            anchors.fill: parent
            radius: height / 2
            color: operationsMouse.containsMouse ? "#11161A" : "#0A0D0F"
            opacity: .90
            border.width: 1
            border.color: operationsMouse.containsMouse ? "#19C7C0" : "#1B2227"
        }
        Text {
            id: operationsText
            anchors.centerIn: parent
            text: "OPERATIONS"
            color: operationsMouse.containsMouse ? "#19C7C0" : "#8C949E"
            font.family: "IBM Plex Mono"
            font.pixelSize: 8
            font.letterSpacing: 1.1
        }
        MouseArea {
            id: operationsMouse
            anchors.fill: parent
            hoverEnabled: true
            onClicked: root.uiProjection.requestAdvancedOperations()
        }
    }

    // A horizontal voice equalizer BELOW the orb that activates while speaking.
    // Same palette as the orb; positioned in the band under the sphere.
    Item {
        id: speakingEqualizer
        objectName: "onyxSpeakingEqualizerV9"
        readonly property var proj: root.uiProjection
        readonly property bool speaking: proj && proj.state === "SPEAKING"
        readonly property real level: proj && proj.audioLevel !== undefined
                                       ? proj.audioLevel : 0
        readonly property int gfps: speaking && proj.animationRunning
                                     ? Math.min(12, Math.max(1, proj.targetFps)) : 0
        property real phase: 0
        property real amp: 0.4
        x: root.compact ? -root.width * .04 : root.width * .18
        width: root.compact ? root.width * 1.08 : root.width * .70
        y: root.height * .70
        height: root.height * .055
        z: 3
        enabled: false
        opacity: speaking ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }

        Canvas {
            id: eqCanvas
            anchors.fill: parent
            renderTarget: Canvas.Image
            onPaint: {
                var c = getContext("2d")
                c.reset()
                c.clearRect(0, 0, width, height)
                if (!speakingEqualizer.speaking)
                    return
                var bars = 48
                var step = width / bars
                var mid = height * .5
                var amp = speakingEqualizer.amp
                c.lineCap = "round"
                for (var i = 0; i < bars; ++i) {
                    var spec = .16
                        + .52 * Math.abs(Math.sin(speakingEqualizer.phase * 1.5 + i * .5))
                        + .32 * Math.abs(Math.sin(speakingEqualizer.phase * 2.9 + i * .19))
                    var h = height * (.12 + amp * .82 * spec)
                    var x = i * step + step * .5
                    c.strokeStyle = i % 3 === 0
                        ? "rgba(199,201,204," + (.34 + amp * .46 * spec) + ")"
                        : "rgba(25,199,192," + (.26 + amp * .50 * spec) + ")"
                    c.lineWidth = Math.max(1.4, step * .42)
                    c.beginPath()
                    c.moveTo(x, mid - h * .5)
                    c.lineTo(x, mid + h * .5)
                    c.stroke()
                }
            }
            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()
        }

        Timer {
            interval: speakingEqualizer.gfps > 0
                      ? Math.max(83, 1000 / speakingEqualizer.gfps) : 1000
            running: speakingEqualizer.gfps > 0 && speakingEqualizer.visible
            repeat: true
            onTriggered: {
                speakingEqualizer.phase =
                    (speakingEqualizer.phase + .09) % 6.283185307
                var breath = .5 + .5 * Math.sin(speakingEqualizer.phase * 1.4)
                var target = .40 + .18 * breath
                             + .55 * Math.max(0, Math.min(1, speakingEqualizer.level))
                if (target > 1)
                    target = 1
                speakingEqualizer.amp += (target - speakingEqualizer.amp) * .30
                eqCanvas.requestPaint()
            }
        }

        onSpeakingChanged: {
            if (!speaking) {
                phase = 0
                amp = 0.40
                eqCanvas.requestPaint()
            }
        }
    }
}
