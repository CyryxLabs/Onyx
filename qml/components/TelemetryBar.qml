import QtQuick

Item {
    id: bar
    property real value: 0.0
    property string label: "SIGNAL"

    implicitHeight: 32

    Text {
        anchors.left: parent.left
        anchors.top: parent.top
        text: bar.label
        color: "#8C949E"
        font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
        font.pixelSize: 9
        font.letterSpacing: 1.2
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 3
        radius: 2
        color: "#1B2227"

        Rectangle {
            width: parent.width * Math.max(0, Math.min(1, bar.value))
            height: parent.height
            radius: parent.radius
            color: "#19C7C0"
        }
    }
}
