pragma ComponentBehavior: Bound
import QtQuick
import "../../components"

Item {
    id: root
    objectName: "devicesHudPageV1"

    property QtObject projection: null
    property bool compact: width < 720
    signal proposalRequested(string kind, var payload)
    signal selectionRequested(string surface, string itemId)

    HudTypographyV1 { id: typography }

    readonly property var devices: projection ? projection.devices : []
    readonly property var metrics: projection ? projection.metrics : ({})

    Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: contentColumn.height + 20
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        Column {
            id: contentColumn
            width: parent.width
            spacing: 14

            HudSectionTitleV1 {
                width: parent.width
                compact: root.compact
                eyebrow: "DEVICE MESH  /  TRUST BOUNDARY"
                title: "Bound Devices"
                detail: "Health and trust posture only. Pairing never grants execution authority."
            }

            Flow {
                width: parent.width
                spacing: 10
                HudMetricTileV1 {
                    width: root.compact ? (contentColumn.width - 10) / 2 : 164
                    label: "Online"
                    value: String(root.metrics.online_devices || 0)
                    hint: "Reachable now"
                    active: Number(root.metrics.online_devices || 0) > 0
                }
                HudMetricTileV1 {
                    width: root.compact ? (contentColumn.width - 10) / 2 : 164
                    label: "Enrolled"
                    value: String(root.devices.length)
                    hint: "Visible devices"
                }
            }

            HoloPanel {
                width: parent.width
                height: Math.max(124, devicesColumn.height + 28)
                radius: 18
                surfaceColor: Qt.rgba(.039, .051, .059, .58)

                Column {
                    id: devicesColumn
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 14
                    spacing: 8

                    Text {
                        text: "MESH INVENTORY  /  " + root.devices.length
                        color: "#8C949E"
                        opacity: .62
                        font.family: typography.monoFamily
                        font.pixelSize: 8
                        font.letterSpacing: 1.5
                    }
                    Repeater {
                        model: root.devices
                        HudDataRowV1 {
                            required property var modelData
                            width: devicesColumn.width
                            eyebrow: modelData.platform + "  /  " + modelData.trust
                            title: modelData.name
                            detail: "Last observed " + modelData.last_seen
                            trailing: modelData.status
                            active: modelData.status === "online" && modelData.trust === "bound"
                            accessibleName: "Inspect device " + modelData.name
                            onActivated: {
                                root.selectionRequested("devices", modelData.device_id)
                                root.proposalRequested("device_inspect", {"device_id": modelData.device_id})
                            }
                        }
                    }
                    Text {
                        visible: root.devices.length === 0
                        width: parent.width
                        height: 54
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: Text.AlignHCenter
                        text: "NO DEVICES IN THE CURRENT PROJECTION"
                        color: "#8C949E"
                        opacity: .54
                        font.family: typography.monoFamily
                        font.pixelSize: 8
                        font.letterSpacing: 1.2
                    }
                }
            }
        }
    }
}
