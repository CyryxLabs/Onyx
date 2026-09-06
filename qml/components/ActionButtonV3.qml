import QtQuick

Rectangle {
    id: button
    objectName: "onyxActionButtonV3"

    property string label: "ACTION"
    property string accessibleName: label
    property string accessibleDescription: ""
    property bool emphasized: false
    signal triggered()

    function trigger() {
        if (enabled) triggered()
    }

    implicitWidth: Math.max(76, actionLabel.implicitWidth + 30)
    implicitHeight: 34
    radius: implicitHeight / 2
    color: activeFocus || pointer.containsMouse
           ? (emphasized ? "#0F6B68" : "#11161A") : "#0A0D0F"
    border.width: activeFocus ? 2 : 1
    border.color: emphasized || activeFocus ? "#19C7C0" : "#1B2227"
    activeFocusOnTab: true

    Accessible.role: Accessible.Button
    Accessible.name: accessibleName
    Accessible.description: accessibleDescription
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

    Text {
        id: actionLabel
        anchors.centerIn: parent
        text: button.label
        color: "#C7C9CC"
        font.family: Qt.platform.os === "windows" ? "Consolas" : "monospace"
        font.pixelSize: 9
        font.weight: Font.DemiBold
        font.letterSpacing: 1.1
    }

    MouseArea {
        id: pointer
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: button.trigger()
    }
}
