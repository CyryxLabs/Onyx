import QtQuick
import "components"

Item {
    id: root
    objectName: "onyxLiveShellGuardedV2Root"
    width: 1440
    height: 900
    property var uiProjection: typeof onyxUIProjectionV3 === "undefined" ? null : onyxUIProjectionV3
    readonly property bool projectionAvailable: uiProjection !== null && uiProjection !== undefined
    readonly property bool compact: width < 1100 || height < 720
    readonly property real scaleUnit: Math.max(0.74, Math.min(1.18, width / 1440))
    readonly property color signal: projectionAvailable && uiProjection.animationRunning ? "#19C7C0" : "#8C949E"

    function request(name) {
        if (!projectionAvailable || typeof uiProjection[name] !== "function")
            return false
        return uiProjection[name]()
    }

    function requestWithValue(name, value) {
        if (!projectionAvailable || typeof uiProjection[name] !== "function")
            return false
        return uiProjection[name](value)
    }

    Rectangle { anchors.fill: parent; color: "#050607" }
    Canvas {
        anchors.fill: parent
        renderTarget: Canvas.Image
        onPaint: {
            var c = getContext("2d"); c.reset(); c.clearRect(0, 0, width, height)
            var glow = c.createRadialGradient(width * .54, height * .43, 0,
                                               width * .54, height * .43, height * .64)
            glow.addColorStop(0, "rgba(15,107,104,.095)")
            glow.addColorStop(.42, "rgba(10,13,15,.52)")
            glow.addColorStop(1, "rgba(5,6,7,1)")
            c.fillStyle = glow; c.fillRect(0, 0, width, height)
        }
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
    }

    OnyxOrbEntityV9 {
        id: orb
        projection: root.uiProjection
        x: root.compact ? -width * .04 : root.width * .18
        y: root.height * .04
        width: root.compact ? root.width * 1.08 : root.width * .70
        height: root.height * .72
    }

    Column {
        x: 42 * root.scaleUnit; y: 34 * root.scaleUnit; spacing: 3
        Text {
            text: "ONYX"; color: "#C7C9CC"
            font.family: "Space Grotesk"; font.pixelSize: 22 * root.scaleUnit
            font.weight: Font.DemiBold; font.letterSpacing: 7
        }
        Text {
            text: "CYRYX LABS  /  COGNITIVE ENTITY"
            color: "#8C949E"; opacity: .72
            font.family: "IBM Plex Mono"; font.pixelSize: 8 * root.scaleUnit
            font.letterSpacing: 1.6
        }
    }

    Column {
        visible: !root.compact
        x: root.width * .075; y: root.height * .29; width: root.width * .18; spacing: 11
        Text {
            text: "GOOD " + (new Date().getHours() < 12 ? "MORNING" : new Date().getHours() < 18 ? "AFTERNOON" : "EVENING") + ","
            color: "#8C949E"; opacity: .62; font.family: "IBM Plex Mono"
            font.pixelSize: 8; font.letterSpacing: 2
        }
        Text {
            text: root.projectionAvailable ? root.uiProjection.ownerName : ""
            color: "#C7C9CC"; font.family: "Space Grotesk"; font.pixelSize: 25
            font.weight: Font.Medium
        }
        Text {
            width: parent.width; text: root.projectionAvailable ? root.uiProjection.stateDetail : ""
            color: "#8C949E"; opacity: .80; wrapMode: Text.WordWrap
            font.family: "Inter"; font.pixelSize: 11; lineHeight: 1.45
        }
        Text {
            width: parent.width; text: root.projectionAvailable ? root.uiProjection.metricsSummary : ""
            color: root.signal; opacity: .68; wrapMode: Text.WordWrap
            font.family: "IBM Plex Mono"; font.pixelSize: 8; lineHeight: 1.55
        }
    }

    Column {
        anchors.right: parent.right; anchors.rightMargin: 42 * root.scaleUnit
        y: 36 * root.scaleUnit; spacing: 4
        Text {
            anchors.right: parent.right; text: root.projectionAvailable ? root.uiProjection.stateLabel : "OFFLINE"
            color: root.signal; font.family: "IBM Plex Mono"; font.pixelSize: 9
            font.letterSpacing: 2.2
        }
        Text {
            anchors.right: parent.right
            text: root.projectionAvailable
                  ? (root.uiProjection.muted ? "VOICE SILENT" : "VOICE READY") +
                    "   ·   " + (root.uiProjection.targetFps > 0 ? root.uiProjection.targetFps + " FPS" : "STATIC")
                  : "VOICE OFFLINE   ·   STATIC"
            color: "#8C949E"; opacity: .58; font.family: "IBM Plex Mono"; font.pixelSize: 8
        }
    }

    Column {
        visible: !root.compact
        anchors.right: parent.right; anchors.rightMargin: root.width * .055
        y: root.height * .25; width: root.width * .205; spacing: 10
        Text {
            text: root.projectionAvailable
                  ? (root.uiProjection.contentVisible ? root.uiProjection.contentTitle : root.uiProjection.transcriptTitle)
                  : ""
            width: parent.width; color: "#C7C9CC"; wrapMode: Text.WordWrap
            font.family: "Space Grotesk"; font.pixelSize: 15; font.weight: Font.Medium
        }
        Text {
            text: root.projectionAvailable
                  ? (root.uiProjection.contentVisible ? root.uiProjection.contentText : root.uiProjection.transcriptText)
                  : ""
            width: parent.width; color: "#8C949E"; opacity: .88; wrapMode: Text.WordWrap
            maximumLineCount: 9; elide: Text.ElideRight
            font.family: "Inter"; font.pixelSize: 10; lineHeight: 1.46
        }
        Text {
            text: "ACTIVITY  /  LIVE TRACE"; color: "#8C949E"; opacity: .48
            font.family: "IBM Plex Mono"; font.pixelSize: 8; font.letterSpacing: 1.6
        }
        Text {
            text: root.projectionAvailable ? root.uiProjection.logText : ""; width: parent.width
            color: "#8C949E"; opacity: .70; wrapMode: Text.Wrap
            maximumLineCount: 6; elide: Text.ElideRight
            font.family: "IBM Plex Mono"; font.pixelSize: 8; lineHeight: 1.45
        }
        Row {
            spacing: 8
            OrbAction { label: "HISTORY"; accessibleName: "Show Onyx activity history"; onTriggered: root.request("requestHistory") }
            OrbAction { label: "ACCESS"; accessibleName: "Show Onyx permission controls"; onTriggered: root.request("requestPermissions") }
        }
    }

    Text {
        anchors.horizontalCenter: orb.horizontalCenter
        y: root.height * .63
        text: root.projectionAvailable
              ? (root.uiProjection.actionStatus === "READY" ? root.uiProjection.stateLabel : root.uiProjection.actionStatus)
              : "OFFLINE"
        color: root.signal; opacity: .76
        font.family: "IBM Plex Mono"; font.pixelSize: 9; font.letterSpacing: 3.4
    }

    Item {
        id: keel
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        anchors.leftMargin: root.compact ? 18 : root.width * .09
        anchors.rightMargin: root.compact ? 18 : root.width * .09
        anchors.bottomMargin: root.compact ? 14 : 22
        height: root.compact ? 128 : 142

        Canvas {
            anchors.fill: parent
            onPaint: {
                var c = getContext("2d"); c.reset(); c.clearRect(0, 0, width, height)
                c.lineWidth = 1; c.strokeStyle = commandInput.activeFocus ? "rgba(25,199,192,.72)" : "rgba(140,148,158,.42)"
                c.beginPath(); c.moveTo(0, 39); c.quadraticCurveTo(width * .18, 7, width * .5, 13)
                c.quadraticCurveTo(width * .82, 7, width, 39); c.stroke()
                c.strokeStyle = "rgba(15,107,104,.28)"; c.beginPath()
                c.moveTo(width * .14, 58); c.quadraticCurveTo(width * .5, 78, width * .86, 58); c.stroke()
            }
        }
        DropArea {
            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; height: 70
            onDropped: function(drop) {
                if (drop.hasUrls && drop.urls.length > 0)
                    root.requestWithValue("acceptDroppedFile", drop.urls[0].toString())
            }
        }
        TextInput {
            id: commandInput; objectName: "liveCommandInputV7"
            anchors.left: parent.left; anchors.right: runAction.left
            anchors.leftMargin: root.compact ? 26 : width * .08
            anchors.rightMargin: 20; y: 20; height: 36
            color: "#C7C9CC"; selectionColor: "#0F6B68"; clip: true
            font.family: "Inter"; font.pixelSize: 14; activeFocusOnTab: true
            Accessible.role: Accessible.EditableText; Accessible.name: "Direct Onyx"
            Text {
                anchors.fill: parent; verticalAlignment: Text.AlignVCenter
                visible: !commandInput.text && !commandInput.activeFocus
                text: "Direct Onyx  ·  or release a file into the field"
                color: "#C7C9CC"; opacity: .66; font: commandInput.font
            }
            onAccepted: if (root.requestWithValue("submitCommand", text)) text = ""
        }
        OrbAction {
            id: runAction; anchors.right: parent.right; anchors.rightMargin: 12
            y: 16; label: "EXECUTE"; emphasized: true
            accessibleName: "Submit command to Onyx"
            onTriggered: if (root.requestWithValue("submitCommand", commandInput.text)) commandInput.text = ""
        }
        Flow {
            anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
            spacing: root.compact ? 5 : 8
            layoutDirection: Qt.LeftToRight
            OrbAction { label: "FILE"; accessibleName: "Attach a file"; onTriggered: root.request("requestFile") }
            OrbAction { label: "INTERRUPT"; accessibleName: "Interrupt Onyx"; onTriggered: root.request("requestInterrupt") }
            OrbAction { label: root.projectionAvailable && root.uiProjection.muted ? "UNMUTE" : "MUTE"; accessibleName: "Toggle microphone"; onTriggered: root.request("requestMuteToggle") }
            OrbAction { label: root.projectionAvailable && root.uiProjection.autonomyEnabled ? "AUTONOMY ON" : "AUTONOMY"; emphasized: root.projectionAvailable && root.uiProjection.autonomyEnabled; accessibleName: "Toggle owner autonomy"; onTriggered: root.request("requestAutonomy") }
            OrbAction { label: "REMOTE"; accessibleName: "Open remote access"; onTriggered: root.request("requestRemote") }
            OrbAction { label: root.projectionAvailable && root.uiProjection.cameraActive ? "STOP CAM" : "CAMERA"; accessibleName: "Toggle camera feed"; onTriggered: root.request("requestCamera") }
            OrbAction { label: "SETUP"; accessibleName: "Configure Onyx"; onTriggered: root.request("requestSetup") }
            OrbAction { label: "FULLSCREEN"; accessibleName: "Toggle fullscreen"; onTriggered: root.request("requestFullscreen") }
            OrbAction { label: "CLOSE"; accessibleName: "Close Onyx"; onTriggered: root.request("requestClose") }
        }
    }

    component OrbAction: Item {
        id: action
        property string label
        property string accessibleName
        property bool emphasized: false
        signal triggered()
        implicitWidth: Math.max(58, textNode.implicitWidth + 22)
        implicitHeight: 27
        Accessible.role: Accessible.Button; Accessible.name: accessibleName
        Rectangle {
            anchors.fill: parent; radius: height / 2
            color: mouse.containsMouse ? "#11161A" : "#0A0D0F"
            opacity: .88; border.width: 1
            border.color: action.emphasized ? "#0F6B68" : "#1B2227"
        }
        Text {
            id: textNode; anchors.centerIn: parent; text: action.label
            color: action.emphasized ? "#19C7C0" : "#8C949E"
            font.family: "IBM Plex Mono"; font.pixelSize: 8; font.letterSpacing: .9
        }
        MouseArea { id: mouse; anchors.fill: parent; hoverEnabled: true; onClicked: action.triggered() }
    }
}

