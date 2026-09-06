import QtQuick
import "components"

Item {
    id: root
    objectName: "onyxShellV3Root"
    width: 1440
    height: 900

    property var uiProjection: typeof onyxUIProjectionV3 === "undefined"
                               ? null : onyxUIProjectionV3

    Rectangle {
        anchors.fill: parent
        color: "#050607"
    }

    Item {
        anchors.fill: parent
        anchors.bottomMargin: 112
        clip: true

        OnyxShell {
            width: root.width
            height: root.height
            uiProjection: root.uiProjection
        }
    }

    Row {
        id: controlActions
        objectName: "controlActionsV3"
        z: 20
        anchors.top: parent.top
        anchors.topMargin: Math.max(22, Math.min(root.width, root.height) * 0.034) + 7
        anchors.right: parent.right
        anchors.rightMargin: Math.max(300, root.width * 0.22)
        spacing: 9

        ActionButtonV3 {
            id: muteAction
            objectName: "muteActionV3"
            label: root.uiProjection && root.uiProjection.muted ? "UNMUTE" : "MUTE"
            accessibleName: root.uiProjection && root.uiProjection.muted
                            ? "Unmute Onyx" : "Mute Onyx"
            accessibleDescription: "Toggle the Onyx voice microphone state"
            emphasized: root.uiProjection && root.uiProjection.muted
            onTriggered: root.uiProjection.requestMuteToggle()
            KeyNavigation.tab: closeAction
        }

        ActionButtonV3 {
            id: closeAction
            objectName: "closeActionV3"
            label: "CLOSE"
            accessibleName: "Close Onyx"
            accessibleDescription: "Close the Onyx assistant window"
            onTriggered: root.uiProjection.requestClose()
            KeyNavigation.tab: commandInput
        }
    }

    HoloPanel {
        id: commandDock
        objectName: "commandDockV3"
        z: 21
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: Math.max(22, Math.min(root.width, root.height) * 0.034)
        anchors.rightMargin: anchors.leftMargin
        anchors.bottomMargin: anchors.leftMargin
        height: 76
        radius: 25
        edgeColor: commandInput.activeFocus ? "#0F6B68" : "#1B2227"
        glowStrength: commandInput.activeFocus ? 0.16 : 0.0

        TextInput {
            id: commandInput
            objectName: "commandInputV3"
            anchors.left: parent.left
            anchors.right: sendAction.left
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: 24
            anchors.rightMargin: 18
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
            KeyNavigation.tab: sendAction

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
                if (root.uiProjection.submitCommand(text)) text = ""
            }
        }

        ActionButtonV3 {
            id: sendAction
            objectName: "sendActionV3"
            anchors.right: parent.right
            anchors.rightMargin: 14
            anchors.verticalCenter: parent.verticalCenter
            implicitWidth: 52
            implicitHeight: 48
            label: "RUN"
            accessibleName: "Submit command to Onyx"
            accessibleDescription: "Submit only when the command callback accepts it"
            emphasized: true
            onTriggered: {
                if (root.uiProjection.submitCommand(commandInput.text))
                    commandInput.text = ""
            }
            KeyNavigation.tab: muteAction
        }

        Text {
            objectName: "actionStatusV3"
            anchors.right: sendAction.left
            anchors.rightMargin: 18
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 8
            text: root.uiProjection ? root.uiProjection.actionStatus : ""
            color: text === "COMMAND ACCEPTED" ? "#19C7C0" : "#8C949E"
            font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
            font.pixelSize: 8
            font.letterSpacing: 0.9
            visible: text !== "READY" && text !== ""
        }
    }
}
