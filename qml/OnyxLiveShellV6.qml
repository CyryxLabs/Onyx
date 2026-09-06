import QtQuick
import "components"

Item {
    id: root
    objectName: "onyxLiveShellV6Root"
    width: 1440
    height: 900

    property var uiProjection: typeof onyxUIProjectionV3 === "undefined"
                               ? null : onyxUIProjectionV3
    readonly property bool compact: width < 980 || height < 650
    readonly property int edge: compact ? 18 : Math.max(28, Math.min(width, height) * 0.038)
    readonly property string activeSignal: uiProjection.animationRunning
                                           ? "#19C7C0" : "#8C949E"

    Rectangle {
        anchors.fill: parent
        color: "#050607"
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#0A0D0F" }
            GradientStop { position: 0.48; color: "#050607" }
            GradientStop { position: 1.0; color: "#050607" }
        }
    }

    Canvas {
        id: environment
        anchors.fill: parent
        opacity: 0.84
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            ctx.clearRect(0, 0, width, height)
            var cx = width * 0.5
            var cy = height * 0.45
            var voidField = ctx.createRadialGradient(
                cx, cy, 0, cx, cy, Math.max(width, height) * 0.48)
            voidField.addColorStop(0.0, "rgba(0,0,0,1)")
            voidField.addColorStop(0.84, "rgba(0,0,0,1)")
            voidField.addColorStop(1.0, "rgba(5,6,7,0)")
            ctx.fillStyle = voidField
            ctx.fillRect(0, 0, width, height)
            var bloom = ctx.createRadialGradient(cx, cy, 0, cx, cy,
                                                 Math.min(width, height) * 0.68)
            bloom.addColorStop(0.0, "rgba(15,107,104,0.115)")
            bloom.addColorStop(0.34, "rgba(17,22,26,0.05)")
            bloom.addColorStop(1.0, "rgba(5,6,7,0)")
            ctx.fillStyle = bloom
            ctx.fillRect(0, 0, width, height)

            ctx.lineWidth = 0.55
            ctx.strokeStyle = "rgba(140,148,158,0.085)"
            ctx.beginPath()
            ctx.moveTo(width * 0.16, cy)
            ctx.lineTo(width * 0.31, cy)
            ctx.moveTo(width * 0.69, cy)
            ctx.lineTo(width * 0.84, cy)
            ctx.stroke()

            ctx.strokeStyle = "rgba(25,199,192,0.075)"
            ctx.beginPath()
            ctx.arc(cx, cy, Math.min(width, height) * 0.354,
                    Math.PI * 0.72, Math.PI * 0.92)
            ctx.arc(cx, cy, Math.min(width, height) * 0.354,
                    Math.PI * 0.08, Math.PI * 0.28)
            ctx.stroke()
        }
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
    }

    Item {
        id: header
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: root.edge
        anchors.rightMargin: root.edge
        anchors.topMargin: root.compact ? 14 : 22
        height: 54

        Column {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            spacing: 3
            Text {
                text: "ONYX"
                color: "#C7C9CC"
                font.family: Qt.platform.os === "windows" ? "Segoe UI" : "Sans Serif"
                font.pixelSize: root.compact ? 17 : 22
                font.weight: Font.DemiBold
                font.letterSpacing: 6.2
            }
            Text {
                text: "CYRYX LABS  /  COGNITIVE PRESENCE"
                color: "#8C949E"
                opacity: 0.62
                font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
                font.pixelSize: 8
                font.letterSpacing: 1.55
            }
        }

        Row {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: 18
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: root.uiProjection.stateLabel
                color: root.activeSignal
                font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
                font.pixelSize: 9
                font.weight: Font.DemiBold
                font.letterSpacing: 2.0
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: root.uiProjection.muted ? "VOICE / SILENT" : "VOICE / READY"
                color: "#8C949E"
                opacity: 0.78
                font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
                font.pixelSize: 8
                font.letterSpacing: 1.25
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: root.uiProjection.targetFps > 0
                      ? "RENDER / " + root.uiProjection.targetFps
                      : "RENDER / STATIC"
                color: "#8C949E"
                opacity: 0.58
                font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
                font.pixelSize: 8
                font.letterSpacing: 1.15
            }
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: "#1B2227"
            opacity: 0.72
        }
    }

    Item {
        id: stage
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: header.bottom
        anchors.bottom: commandDeck.top
        anchors.leftMargin: root.edge
        anchors.rightMargin: root.edge

        Item {
            id: presenceRail
            visible: !root.compact
            width: Math.max(215, root.width * 0.175)
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom

            Rectangle {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                width: 1
                height: Math.min(330, parent.height * 0.62)
                color: "#8C949E"
                opacity: 0.18
            }

            Column {
                anchors.left: parent.left
                anchors.leftMargin: 18
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - 18
                spacing: 15
                Text {
                    text: "GOOD DAY,\n" + root.uiProjection.ownerName.toUpperCase() + "."
                    width: parent.width
                    wrapMode: Text.WordWrap
                    color: "#C7C9CC"
                    font.family: Qt.platform.os === "windows" ? "Segoe UI" : "Sans Serif"
                    font.pixelSize: 18
                    font.weight: Font.Medium
                    lineHeight: 1.12
                }
                Text {
                    text: root.uiProjection.stateDetail
                    width: parent.width
                    wrapMode: Text.WordWrap
                    color: "#8C949E"
                    opacity: 0.84
                    font.pixelSize: 11
                    lineHeight: 1.42
                }
                Rectangle {
                    width: 38
                    height: 1
                    color: root.activeSignal
                    opacity: 0.62
                }
                Text {
                    text: root.uiProjection.metricsSummary
                    width: parent.width
                    wrapMode: Text.WordWrap
                    color: "#8C949E"
                    opacity: 0.68
                    font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
                    font.pixelSize: 8
                    lineHeight: 1.5
                }
                Text {
                    text: "MEMORY  /  LOCAL\nAUTHORITY  /  GOVERNED\nHOST  /  AVAILABLE"
                    color: "#8C949E"
                    opacity: 0.46
                    font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
                    font.pixelSize: 8
                    lineHeight: 1.72
                }
            }
        }

        Item {
            id: orbStage
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.left: root.compact ? parent.left : presenceRail.right
            anchors.right: root.compact ? parent.right : contextRail.left

            OnyxOrbParticleV6 {
                id: orb
                anchors.fill: parent
                projection: root.uiProjection
            }

            Column {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 2
                spacing: 4
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: root.uiProjection.stateLabel
                    color: "#C7C9CC"
                    font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
                    font.pixelSize: 9
                    font.letterSpacing: 3.8
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: root.uiProjection.actionStatus
                    visible: text !== "READY"
                    color: "#19C7C0"
                    opacity: 0.72
                    font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
                    font.pixelSize: 8
                    font.letterSpacing: 1.2
                }
            }
        }

        Item {
            id: contextRail
            visible: !root.compact
            width: Math.max(225, root.width * 0.18)
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom

            Rectangle {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                width: 1
                height: Math.min(350, parent.height * 0.66)
                color: "#8C949E"
                opacity: 0.18
            }

            Column {
                anchors.right: parent.right
                anchors.rightMargin: 18
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - 18
                spacing: 12
                Text {
                    text: root.uiProjection.contentVisible
                          ? root.uiProjection.contentTitle
                          : root.uiProjection.transcriptTitle
                    width: parent.width
                    wrapMode: Text.WordWrap
                    color: "#C7C9CC"
                    font.pixelSize: 14
                    font.weight: Font.Medium
                }
                Text {
                    text: root.uiProjection.contentVisible
                          ? root.uiProjection.contentText
                          : root.uiProjection.transcriptText
                    width: parent.width
                    wrapMode: Text.WordWrap
                    elide: Text.ElideRight
                    maximumLineCount: 8
                    color: "#8C949E"
                    opacity: 0.82
                    font.pixelSize: 10
                    lineHeight: 1.42
                }
                Rectangle {
                    width: parent.width
                    height: 1
                    color: "#1B2227"
                    opacity: 0.68
                }
                Text {
                    text: "ACTIVITY STREAM"
                    color: "#8C949E"
                    opacity: 0.64
                    font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
                    font.pixelSize: 8
                    font.letterSpacing: 1.7
                }
                Text {
                    text: root.uiProjection.logText
                    width: parent.width
                    color: "#8C949E"
                    opacity: 0.60
                    elide: Text.ElideRight
                    maximumLineCount: 7
                    wrapMode: Text.Wrap
                    font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
                    font.pixelSize: 8
                    lineHeight: 1.45
                }
                Row {
                    spacing: 8
                    ActionButtonV3 {
                        label: "HISTORY"
                        accessibleName: "Show Onyx activity history"
                        onTriggered: root.uiProjection.requestHistory()
                    }
                    ActionButtonV3 {
                        label: "ACCESS"
                        accessibleName: "Show Onyx permission controls"
                        onTriggered: root.uiProjection.requestPermissions()
                    }
                }
            }
        }
    }

    Item {
        id: commandDeck
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: root.edge
        anchors.rightMargin: root.edge
        anchors.bottomMargin: root.compact ? 14 : 22
        height: 116

        Rectangle {
            id: commandSurface
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 58
            radius: 29
            color: commandInput.activeFocus ? "#11161A" : "#0A0D0F"
            opacity: 0.95
            border.width: 1
            border.color: commandInput.activeFocus ? "#0F6B68" : "#1B2227"

            DropArea {
                anchors.fill: parent
                onDropped: function(drop) {
                    if (drop.hasUrls && drop.urls.length > 0)
                        root.uiProjection.acceptDroppedFile(drop.urls[0].toString())
                }
            }

            TextInput {
                id: commandInput
                objectName: "liveCommandInputV6"
                anchors.left: parent.left
                anchors.right: runAction.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 24
                anchors.rightMargin: 16
                color: "#C7C9CC"
                selectionColor: "#0F6B68"
                selectedTextColor: "#C7C9CC"
                font.family: Qt.platform.os === "windows" ? "Segoe UI" : "Sans Serif"
                font.pixelSize: 14
                clip: true
                activeFocusOnTab: true
                Accessible.role: Accessible.EditableText
                Accessible.name: "Direct Onyx"
                Accessible.description: "Type a command for Onyx and press Enter"
                Text {
                    anchors.fill: parent
                    verticalAlignment: Text.AlignVCenter
                    visible: !commandInput.text && !commandInput.activeFocus
                    text: "Direct Onyx...  or drop a file"
                    color: "#8C949E"
                    opacity: 0.46
                    font: commandInput.font
                }
                onAccepted: {
                    if (root.uiProjection.submitCommand(text)) text = ""
                }
            }

            ActionButtonV3 {
                id: runAction
                anchors.right: parent.right
                anchors.rightMargin: 7
                anchors.verticalCenter: parent.verticalCenter
                implicitWidth: 64
                implicitHeight: 44
                label: "RUN"
                emphasized: true
                accessibleName: "Submit command to Onyx"
                onTriggered: {
                    if (root.uiProjection.submitCommand(commandInput.text))
                        commandInput.text = ""
                }
            }
        }

        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            spacing: root.compact ? 5 : 8
            ActionButtonV3 { label: "FILE"; accessibleName: "Attach a file"; onTriggered: root.uiProjection.requestFile() }
            ActionButtonV3 { label: "INTERRUPT"; accessibleName: "Interrupt Onyx"; onTriggered: root.uiProjection.requestInterrupt() }
            ActionButtonV3 { label: root.uiProjection.muted ? "UNMUTE" : "MUTE"; accessibleName: "Toggle microphone"; onTriggered: root.uiProjection.requestMuteToggle() }
            ActionButtonV3 { label: root.uiProjection.autonomyEnabled ? "AUTONOMY ON" : "AUTONOMY"; accessibleName: "Toggle owner autonomy"; emphasized: root.uiProjection.autonomyEnabled; onTriggered: root.uiProjection.requestAutonomy() }
            ActionButtonV3 { label: "REMOTE"; accessibleName: "Open remote access"; onTriggered: root.uiProjection.requestRemote() }
            ActionButtonV3 { label: root.uiProjection.cameraActive ? "STOP CAM" : "CAMERA"; accessibleName: "Toggle camera feed"; onTriggered: root.uiProjection.requestCamera() }
            ActionButtonV3 { label: "SETUP"; accessibleName: "Configure Onyx"; onTriggered: root.uiProjection.requestSetup() }
            ActionButtonV3 { label: "FULLSCREEN"; accessibleName: "Toggle fullscreen"; onTriggered: root.uiProjection.requestFullscreen() }
            ActionButtonV3 { label: "CLOSE"; accessibleName: "Close Onyx"; onTriggered: root.uiProjection.requestClose() }
        }
    }
}
