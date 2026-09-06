import QtQuick
import QtQuick.Layouts
import "components"

Item {
    id: root
    objectName: "onyxShellRoot"
    width: 1440
    height: 900

    // QQuickView/QQuickWidget hosts provide this public context property before
    // loading the shell. Tests may still override uiProjection at creation.
    property var uiProjection: typeof onyxUIProjection === "undefined"
                               ? null : onyxUIProjection

    Rectangle {
        anchors.fill: parent
        color: "#050607"

        gradient: Gradient {
            GradientStop { position: 0.0; color: "#0A0D0F" }
            GradientStop { position: 0.52; color: "#050607" }
            GradientStop { position: 1.0; color: "#0A0D0F" }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Math.max(22, Math.min(root.width, root.height) * 0.034)
        spacing: 18

        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 48

            Column {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                spacing: 3

                Text {
                    text: "ONYX"
                    color: "#C7C9CC"
                    font.family: Qt.platform.os === "windows" ? "Segoe UI" : "Sans Serif"
                    font.pixelSize: 22
                    font.weight: Font.DemiBold
                    font.letterSpacing: 4.6
                }
                Text {
                    text: "CYRYX LABS  /  COGNITIVE OPERATING PRESENCE"
                    color: "#8C949E"
                    font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
                    font.pixelSize: 9
                    font.letterSpacing: 1.5
                }
            }

            Row {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: 10

                StatusPill { label: uiProjection.stateLabel; active: true }
                StatusPill {
                    label: uiProjection.muted ? "VOICE MUTED" : "VOICE READY"
                    active: !uiProjection.muted
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 18

            HoloPanel {
                Layout.preferredWidth: Math.max(210, root.width * 0.17)
                Layout.fillHeight: true
                edgeColor: "#1B2227"

                Column {
                    anchors.fill: parent
                    anchors.margins: 22
                    spacing: 22

                    Text {
                        text: "PRESENCE"
                        color: "#8C949E"
                        font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
                        font.pixelSize: 9
                        font.letterSpacing: 1.8
                    }
                    Text {
                        width: parent.width
                        text: "Good day, " + uiProjection.ownerName + "."
                        color: "#C7C9CC"
                        wrapMode: Text.WordWrap
                        font.family: Qt.platform.os === "windows" ? "Segoe UI" : "Sans Serif"
                        font.pixelSize: 19
                        font.weight: Font.Medium
                    }
                    Text {
                        width: parent.width
                        text: uiProjection.stateDetail
                        color: "#8C949E"
                        wrapMode: Text.WordWrap
                        font.family: Qt.platform.os === "windows" ? "Segoe UI" : "Sans Serif"
                        font.pixelSize: 12
                        lineHeight: 1.35
                    }

                    Item { width: 1; height: 8 }
                    TelemetryBar {
                        width: parent.width
                        label: "VOICE ENERGY"
                        value: uiProjection.audioLevel
                    }
                    TelemetryBar {
                        width: parent.width
                        label: "RENDER BUDGET"
                        value: uiProjection.targetFps / 30.0
                    }

                    Item { width: 1; height: 4 }
                    Repeater {
                        model: [
                            ["MEMORY", "LOCAL"],
                            ["AUTHORITY", "GOVERNED"],
                            ["RENDER", uiProjection.targetFps > 0 ? uiProjection.targetFps + " FPS" : "STATIC"]
                        ]
                        delegate: Item {
                            required property var modelData
                            width: parent.width
                            height: 34
                            Text {
                                anchors.left: parent.left
                                anchors.verticalCenter: parent.verticalCenter
                                text: modelData[0]
                                color: "#8C949E"
                                font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
                                font.pixelSize: 9
                                font.letterSpacing: 1.0
                            }
                            Text {
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                text: modelData[1]
                                color: "#C7C9CC"
                                font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
                                font.pixelSize: 9
                            }
                        }
                    }
                }
            }

            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: 420

                OnyxOrbV2 {
                    id: orb
                    anchors.fill: parent
                    anchors.margins: 8
                    projection: uiProjection
                }

                Column {
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 18
                    spacing: 7

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: uiProjection.stateLabel
                        color: "#C7C9CC"
                        font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
                        font.pixelSize: 11
                        font.letterSpacing: 3.0
                    }
                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 46
                        height: 2
                        radius: 1
                        color: uiProjection.muted ? "#8C949E" : "#19C7C0"
                        opacity: 0.72
                    }
                }
            }

            HoloPanel {
                Layout.preferredWidth: Math.max(235, root.width * 0.19)
                Layout.fillHeight: true
                edgeColor: "#1B2227"

                Column {
                    anchors.fill: parent
                    anchors.margins: 22
                    spacing: 18

                    Text {
                        text: "ACTIVE CONTEXT"
                        color: "#8C949E"
                        font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
                        font.pixelSize: 9
                        font.letterSpacing: 1.8
                    }
                    Text {
                        width: parent.width
                        text: uiProjection.transcriptTitle
                        color: "#C7C9CC"
                        wrapMode: Text.WordWrap
                        font.family: Qt.platform.os === "windows" ? "Segoe UI" : "Sans Serif"
                        font.pixelSize: 17
                        font.weight: Font.Medium
                    }
                    Text {
                        width: parent.width
                        text: uiProjection.transcriptText
                        color: "#8C949E"
                        wrapMode: Text.WordWrap
                        elide: Text.ElideRight
                        maximumLineCount: 14
                        font.family: Qt.platform.os === "windows" ? "Segoe UI" : "Sans Serif"
                        font.pixelSize: 12
                        lineHeight: 1.42
                    }

                    Item { width: 1; height: 8 }
                    Repeater {
                        model: [
                            ["HISTORY", "Recall prior work", "history"],
                            ["ACCESS", "Review permissions", "permissions"],
                            ["SYSTEM", "Configure Onyx", "settings"]
                        ]
                        delegate: Rectangle {
                            required property var modelData
                            width: parent.width
                            height: 52
                            radius: 14
                            color: actionArea.containsMouse ? "#11161A" : "#0A0D0F"
                            border.width: 1
                            border.color: actionArea.containsMouse ? "#0F6B68" : "#1B2227"

                            Column {
                                anchors.left: parent.left
                                anchors.leftMargin: 15
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 2
                                Text {
                                    text: modelData[0]
                                    color: "#C7C9CC"
                                    font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
                                    font.pixelSize: 9
                                    font.letterSpacing: 1.0
                                }
                                Text {
                                    text: modelData[1]
                                    color: "#8C949E"
                                    font.family: Qt.platform.os === "windows" ? "Segoe UI" : "Sans Serif"
                                    font.pixelSize: 10
                                }
                            }
                            MouseArea {
                                id: actionArea
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    if (modelData[2] === "history") uiProjection.requestHistory()
                                    else if (modelData[2] === "permissions") uiProjection.requestPermissions()
                                    else uiProjection.requestSettings()
                                }
                            }
                        }
                    }
                }
            }
        }

        HoloPanel {
            Layout.fillWidth: true
            Layout.preferredHeight: 76
            radius: 25
            edgeColor: commandInput.activeFocus ? "#0F6B68" : "#1B2227"
            glowStrength: commandInput.activeFocus ? 0.16 : 0.0

            TextInput {
                id: commandInput
                anchors.left: parent.left
                anchors.right: sendButton.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 24
                anchors.rightMargin: 18
                color: "#C7C9CC"
                selectionColor: "#0F6B68"
                selectedTextColor: "#C7C9CC"
                font.family: Qt.platform.os === "windows" ? "Segoe UI" : "Sans Serif"
                font.pixelSize: 14
                clip: true

                Text {
                    anchors.fill: parent
                    verticalAlignment: Text.AlignVCenter
                    text: "Direct Onyx..."
                    color: "#8C949E"
                    opacity: 0.52
                    font: commandInput.font
                    visible: !commandInput.text && !commandInput.activeFocus
                }
                onAccepted: {
                    if (uiProjection.submitCommand(text)) text = ""
                }
            }

            Rectangle {
                id: sendButton
                anchors.right: parent.right
                anchors.rightMargin: 14
                anchors.verticalCenter: parent.verticalCenter
                width: 48
                height: 48
                radius: 24
                color: sendArea.containsMouse ? "#0F6B68" : "#11161A"
                border.width: 1
                border.color: "#0F6B68"

                Text {
                    anchors.centerIn: parent
                    text: "RUN"
                    color: "#C7C9CC"
                    font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
                    font.pixelSize: 9
                    font.weight: Font.DemiBold
                }
                MouseArea {
                    id: sendArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        if (uiProjection.submitCommand(commandInput.text)) commandInput.text = ""
                    }
                }
            }
        }
    }
}
