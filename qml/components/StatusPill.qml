import QtQuick

Rectangle {
    id: pill
    property string label: "READY"
    property bool active: false

    implicitWidth: statusText.implicitWidth + 32
    implicitHeight: 28
    radius: 14
    color: active ? Qt.rgba(0.10, 0.78, 0.75, 0.14)
                  : Qt.rgba(0.067, 0.086, 0.102, 0.80)
    border.width: 1
    border.color: active ? Qt.rgba(0.10, 0.78, 0.75, 0.42) : "#1B2227"

    Text {
        id: statusText
        anchors.centerIn: parent
        text: pill.label
        color: pill.active ? "#C7C9CC" : "#8C949E"
        font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
        font.pixelSize: 10
        font.letterSpacing: 1.4
        font.weight: Font.DemiBold
    }
}
