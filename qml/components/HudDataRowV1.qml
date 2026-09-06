pragma ComponentBehavior: Bound
import QtQuick
import "."

HoloPanel {
    id: root
    objectName: "hudDataRowV1"

    property string eyebrow: "READY"
    property string title: "Item"
    property string detail: ""
    property string trailing: ""
    property bool active: false
    property bool selected: false
    property string accessibleName: title
    signal activated()

    HudTypographyV1 { id: typography }

    function trigger() {
        if (enabled)
            activated()
    }

    implicitHeight: 68
    radius: 14
    edgeColor: selected || active ? Qt.rgba(.10, .78, .75, .46) : "#1B2227"
    surfaceColor: selected ? Qt.rgba(.059, .420, .408, .12)
                           : Qt.rgba(.039, .051, .059, .72)
    glowStrength: selected ? .14 : 0
    activeFocusOnTab: true

    Accessible.role: Accessible.Button
    Accessible.name: accessibleName
    Accessible.description: detail
    Accessible.onPressAction: trigger()

    Keys.onReturnPressed: function(event) {
        trigger()
        event.accepted = true
    }
    Keys.onEnterPressed: function(event) {
        trigger()
        event.accepted = true
    }
    Keys.onSpacePressed: function(event) {
        trigger()
        event.accepted = true
    }

    Rectangle {
        visible: root.active || root.selected || root.activeFocus
        anchors.left: parent.left
        anchors.leftMargin: 1
        anchors.verticalCenter: parent.verticalCenter
        width: 2
        height: parent.height - 24
        radius: 1
        color: "#19C7C0"
        opacity: root.activeFocus ? .92 : .62
    }

    Column {
        anchors.left: parent.left
        anchors.leftMargin: 16
        anchors.right: trailingText.left
        anchors.rightMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        spacing: 4

        Text {
            width: parent.width
            text: root.eyebrow.toUpperCase()
            color: root.active ? "#19C7C0" : "#8C949E"
            opacity: .74
            elide: Text.ElideRight
            font.family: typography.monoFamily
            font.pixelSize: 8
            font.letterSpacing: 1.2
        }
        Text {
            width: parent.width
            text: root.title
            color: "#C7C9CC"
            elide: Text.ElideRight
            font.family: typography.bodyFamily
            font.pixelSize: 11
            font.weight: Font.Medium
        }
        Text {
            visible: root.detail.length > 0
            width: parent.width
            text: root.detail
            color: "#8C949E"
            opacity: .68
            elide: Text.ElideRight
            font.family: typography.bodyFamily
            font.pixelSize: 9
        }
    }

    Text {
        id: trailingText
        anchors.right: parent.right
        anchors.rightMargin: 14
        anchors.verticalCenter: parent.verticalCenter
        width: Math.min(104, implicitWidth)
        text: root.trailing
        color: root.active ? "#19C7C0" : "#8C949E"
        opacity: .72
        horizontalAlignment: Text.AlignRight
        elide: Text.ElideRight
        font.family: typography.monoFamily
        font.pixelSize: 8
        font.letterSpacing: .8
    }

    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.trigger()
    }
}
