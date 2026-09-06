import QtQuick

Rectangle {
    id: panel
    property color edgeColor: "#1B2227"
    property color surfaceColor: Qt.rgba(0.039, 0.051, 0.059, 0.70)
    property real glowStrength: 0.0

    color: surfaceColor
    radius: 22
    border.width: 1
    border.color: edgeColor

    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: Math.max(0, parent.radius - 1)
        color: "transparent"
        border.width: panel.glowStrength > 0 ? 1 : 0
        border.color: Qt.rgba(0.10, 0.78, 0.75, panel.glowStrength)
    }
}
