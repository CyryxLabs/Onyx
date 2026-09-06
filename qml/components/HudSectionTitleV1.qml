pragma ComponentBehavior: Bound
import QtQuick

Item {
    id: root
    objectName: "hudSectionTitleV1"

    property string eyebrow: "OPERATIONS"
    property string title: "SECTION"
    property string detail: ""
    property bool compact: false

    HudTypographyV1 { id: typography }

    implicitHeight: detail.length > 0 ? (compact ? 64 : 72) : (compact ? 42 : 48)

    Column {
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: root.compact ? 3 : 5

        Text {
            text: root.eyebrow.toUpperCase()
            color: "#19C7C0"
            opacity: .76
            font.family: typography.monoFamily
            font.pixelSize: root.compact ? 8 : 9
            font.letterSpacing: 1.8
        }
        Text {
            width: parent.width
            text: root.title
            color: "#C7C9CC"
            elide: Text.ElideRight
            font.family: typography.displayFamily
            font.pixelSize: root.compact ? 18 : 23
            font.weight: Font.DemiBold
            font.letterSpacing: .4
        }
        Text {
            visible: root.detail.length > 0
            width: parent.width
            text: root.detail
            color: "#8C949E"
            opacity: .78
            elide: Text.ElideRight
            font.family: typography.bodyFamily
            font.pixelSize: root.compact ? 9 : 10
        }
    }
}
