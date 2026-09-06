pragma ComponentBehavior: Bound
import QtQuick
import "."

HoloPanel {
    id: root
    objectName: "hudMetricTileV1"

    property string label: "METRIC"
    property string value: "0"
    property string hint: ""
    property bool active: false

    HudTypographyV1 { id: typography }

    implicitWidth: 150
    implicitHeight: 82
    radius: 14
    edgeColor: active ? Qt.rgba(.10, .78, .75, .48) : "#1B2227"
    surfaceColor: active ? Qt.rgba(.059, .420, .408, .10)
                         : Qt.rgba(.039, .051, .059, .76)
    glowStrength: active ? .12 : 0

    Column {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 4

        Text {
            text: root.label.toUpperCase()
            color: "#8C949E"
            opacity: .72
            font.family: typography.monoFamily
            font.pixelSize: 8
            font.letterSpacing: 1.2
        }
        Text {
            text: root.value
            color: root.active ? "#19C7C0" : "#C7C9CC"
            font.family: typography.displayFamily
            font.pixelSize: 21
            font.weight: Font.DemiBold
        }
        Text {
            visible: root.hint.length > 0
            text: root.hint
            color: "#8C949E"
            opacity: .56
            font.family: typography.bodyFamily
            font.pixelSize: 8
        }
    }
}
