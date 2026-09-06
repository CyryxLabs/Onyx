import QtQuick

OnyxLiveShellV9 {
    id: root
    objectName: "onyxLiveShellV10Root"

    // Deliberate process termination is a distinct owner action. Historical
    // V7-V9 QML stays byte-exact; only the current successor exposes it.
    Item {
        id: exitAction
        objectName: "exitOnyxActionV10"
        anchors.right: parent.right
        anchors.rightMargin: 42 * root.scaleUnit
        anchors.bottom: parent.bottom
        anchors.bottomMargin: root.compact ? 148 : 174
        width: exitText.implicitWidth + 24
        height: 28
        z: 12
        Accessible.role: Accessible.Button
        Accessible.name: "Exit Onyx completely"

        Rectangle {
            anchors.fill: parent
            radius: height / 2
            color: exitMouse.containsMouse ? "#171013" : "#0A0D0F"
            opacity: .92
            border.width: 1
            border.color: exitMouse.containsMouse ? "#C7C9CC" : "#51333D"
        }
        Text {
            id: exitText
            anchors.centerIn: parent
            text: "EXIT ONYX"
            color: exitMouse.containsMouse ? "#C7C9CC" : "#8C949E"
            font.family: "IBM Plex Mono"
            font.pixelSize: 8
            font.letterSpacing: 1.0
        }
        MouseArea {
            id: exitMouse
            anchors.fill: parent
            hoverEnabled: true
            onClicked: root.uiProjection.requestExit()
        }
    }
}
