import QtQuick
import "components"

Item {
    id: root
    objectName: "onyxLiveShellV5Root"
    width: 1440
    height: 900

    property var uiProjection: typeof onyxUIProjectionV3 === "undefined"
                               ? null : onyxUIProjectionV3
    readonly property bool compact: width < 980 || height < 650
    readonly property int edge: compact ? 18 : Math.max(26, Math.min(width, height) * 0.034)

    Rectangle {
        anchors.fill: parent
        color: "#050607"
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#0A0D0F" }
            GradientStop { position: 0.44; color: "#050607" }
            GradientStop { position: 1.0; color: "#080B0D" }
        }
    }

    Canvas {
        anchors.fill: parent
        opacity: 0.46
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            var glow = ctx.createRadialGradient(width * 0.51, height * 0.46, 0,
                                                width * 0.51, height * 0.46,
                                                Math.min(width, height) * 0.68)
            glow.addColorStop(0.0, "rgba(15,107,104,0.12)")
            glow.addColorStop(0.42, "rgba(10,13,15,0.04)")
            glow.addColorStop(1.0, "rgba(5,6,7,0)")
            ctx.fillStyle = glow
            ctx.fillRect(0, 0, width, height)
        }
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
    }

    Item {
        id: header
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: root.edge
        height: 62

        Column {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            spacing: 4
            Text {
                text: "ONYX"
                color: "#C7C9CC"
                font.family: Qt.platform.os === "windows" ? "Segoe UI" : "Sans Serif"
                font.pixelSize: root.compact ? 18 : 23
                font.weight: Font.DemiBold
                font.letterSpacing: 5.6
            }
            Text {
                text: "CYRYX LABS  /  COGNITIVE OPERATING PRESENCE"
                color: "#8C949E"
                opacity: 0.72
                font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
                font.pixelSize: 8
                font.letterSpacing: 1.4
            }
        }

        Row {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: 12
            StatusPill { label: root.uiProjection.stateLabel; active: true }
            StatusPill {
                label: root.uiProjection.muted ? "VOICE SILENT" : "VOICE READY"
                active: !root.uiProjection.muted
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: root.uiProjection.targetFps > 0
                      ? root.uiProjection.targetFps + " FPS" : "STATIC"
                color: "#8C949E"
                font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
                font.pixelSize: 9
                font.letterSpacing: 1.1
            }
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
        anchors.topMargin: 4
        anchors.bottomMargin: 12

        Column {
            id: presenceRail
            visible: !root.compact
            width: Math.max(210, root.width * 0.17)
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            spacing: 18

            Text {
                text: "GOOD DAY, " + root.uiProjection.ownerName.toUpperCase() + "."
                width: parent.width
                wrapMode: Text.WordWrap
                color: "#C7C9CC"
                font.family: Qt.platform.os === "windows" ? "Segoe UI" : "Sans Serif"
                font.pixelSize: 20
                font.weight: Font.Medium
            }
            Text {
                text: root.uiProjection.stateDetail
                width: parent.width
                wrapMode: Text.WordWrap
                color: "#8C949E"
                font.pixelSize: 12
                lineHeight: 1.35
            }
            Rectangle { width: 42; height: 2; radius: 1; color: "#19C7C0"; opacity: 0.68 }
            Text {
                text: root.uiProjection.metricsSummary
                width: parent.width
                wrapMode: Text.WordWrap
                color: "#8C949E"
                opacity: 0.78
                font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
                font.pixelSize: 9
                lineHeight: 1.5
            }
            Text {
                text: "MEMORY  /  LOCAL\nAUTHORITY  /  GOVERNED\nRENDER  /  ADAPTIVE"
                color: "#8C949E"
                opacity: 0.56
                font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
                font.pixelSize: 9
                lineHeight: 1.7
            }
        }

        Item {
            id: orbStage
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.left: root.compact ? parent.left : presenceRail.right
            anchors.right: root.compact ? parent.right : contextRail.left
            anchors.leftMargin: root.compact ? 0 : 10
            anchors.rightMargin: root.compact ? 0 : 10

            OnyxOrbCinematicV5 {
                id: orb
                anchors.fill: parent
                projection: root.uiProjection
            }

            Column {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 16
                spacing: 6
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: root.uiProjection.stateLabel
                    color: "#C7C9CC"
                    font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
                    font.pixelSize: 10
                    font.letterSpacing: 3.4
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: root.uiProjection.actionStatus
                    color: "#19C7C0"
                    opacity: text === "READY" ? 0.0 : 0.72
                    font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
                    font.pixelSize: 8
                    font.letterSpacing: 1.1
                }
            }
        }

        Column {
            id: contextRail
            visible: !root.compact
            width: Math.max(225, root.width * 0.18)
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: 14

            Text {
                text: root.uiProjection.contentVisible
                      ? root.uiProjection.contentTitle : root.uiProjection.transcriptTitle
                width: parent.width
                wrapMode: Text.WordWrap
                color: "#C7C9CC"
                font.pixelSize: 15
                font.weight: Font.Medium
            }
            Text {
                text: root.uiProjection.contentVisible
                      ? root.uiProjection.contentText : root.uiProjection.transcriptText
                width: parent.width
                wrapMode: Text.WordWrap
                elide: Text.ElideRight
                maximumLineCount: 9
                color: "#8C949E"
                font.pixelSize: 11
                lineHeight: 1.38
            }
            Rectangle { width: parent.width; height: 1; color: "#1B2227"; opacity: 0.84 }
            Text {
                text: "ACTIVITY"
                color: "#8C949E"
                font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
                font.pixelSize: 8
                font.letterSpacing: 1.8
            }
            Text {
                text: root.uiProjection.logText
                width: parent.width
                color: "#8C949E"
                opacity: 0.70
                elide: Text.ElideRight
                maximumLineCount: 8
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

    Item {
        id: commandDeck
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: root.edge
        anchors.rightMargin: root.edge
        anchors.bottomMargin: root.edge
        height: 126

        Rectangle {
            id: commandSurface
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 64
            radius: 32
            color: "#0A0D0F"
            opacity: 0.96
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
                objectName: "liveCommandInputV5"
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
                    opacity: 0.48
                    font: commandInput.font
                }
                onAccepted: {
                    if (root.uiProjection.submitCommand(text)) text = ""
                }
            }

            ActionButtonV3 {
                id: runAction
                anchors.right: parent.right
                anchors.rightMargin: 9
                anchors.verticalCenter: parent.verticalCenter
                implicitWidth: 62
                implicitHeight: 46
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
            id: actions
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
            ActionButtonV3 { label: "EXIT ONYX"; accessibleName: "Exit Onyx completely"; onTriggered: root.uiProjection.requestExit() }
        }
    }
}
