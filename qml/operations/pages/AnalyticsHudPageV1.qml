pragma ComponentBehavior: Bound
import QtQuick
import "../../components"

Item {
    id: root
    objectName: "analyticsHudPageV1"

    property QtObject projection: null
    property bool compact: width < 760
    property string categoryFilter: "all"
    signal proposalRequested(string kind, var payload)
    signal selectionRequested(string surface, string itemId)

    HudTypographyV1 { id: typography }

    readonly property var events: projection ? projection.events : []
    readonly property var metrics: projection ? projection.metrics : ({})
    readonly property var categories: ["all", "goal", "workflow", "agent", "device", "site", "system"]

    function visibleEventCount() {
        if (categoryFilter === "all")
            return events.length
        var count = 0
        for (var i = 0; i < events.length; ++i)
            if (events[i].category === categoryFilter)
                count += 1
        return count
    }

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
                eyebrow: "MISSION LEDGER  /  ANALYTICS"
                title: "Operational Timeline"
                detail: "Event-derived visibility only: no background polling, screen capture or process sampling."
            }

            Flow {
                width: parent.width
                spacing: 10
                HudMetricTileV1 {
                    width: root.compact ? (contentColumn.width - 10) / 2 : 150
                    label: "Events"
                    value: String(root.metrics.events_today || 0)
                    hint: "Current snapshot"
                    active: Number(root.metrics.events_today || 0) > 0
                }
                HudMetricTileV1 {
                    width: root.compact ? (contentColumn.width - 10) / 2 : 150
                    label: "Workflows"
                    value: String(root.metrics.workflows || 0)
                    hint: "Observed graphs"
                }
                HudMetricTileV1 {
                    width: root.compact ? (contentColumn.width - 10) / 2 : 150
                    label: "Agents"
                    value: String(root.metrics.active_agents || 0)
                    hint: "Active units"
                }
            }

            Flow {
                width: parent.width
                spacing: 7
                Repeater {
                    model: root.categories
                    ActionButtonV3 {
                        required property string modelData
                        label: modelData.toUpperCase()
                        accessibleName: "Filter analytics by " + modelData
                        emphasized: root.categoryFilter === modelData
                        onTriggered: {
                            root.categoryFilter = modelData
                            root.proposalRequested("analytics_filter", {"category": modelData})
                        }
                    }
                }
            }

            HoloPanel {
                width: parent.width
                height: Math.max(130, timelineColumn.height + 28)
                radius: 18
                surfaceColor: Qt.rgba(.039, .051, .059, .56)

                Column {
                    id: timelineColumn
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 14
                    spacing: 8

                    Text {
                        text: "EVENT STREAM  /  " + root.visibleEventCount()
                        color: "#8C949E"
                        opacity: .62
                        font.family: typography.monoFamily
                        font.pixelSize: 8
                        font.letterSpacing: 1.3
                    }
                    Repeater {
                        model: root.events
                        HudDataRowV1 {
                            required property var modelData
                            width: timelineColumn.width
                            visible: root.categoryFilter === "all" || root.categoryFilter === modelData.category
                            height: visible ? implicitHeight : 0
                            eyebrow: modelData.category + "  /  " + modelData.status
                            title: modelData.title
                            detail: modelData.detail
                            trailing: modelData.time_label
                            active: modelData.status === "active" || modelData.status === "running"
                            accessibleName: "Inspect timeline event " + modelData.title
                            onActivated: root.selectionRequested("analytics", modelData.event_id)
                        }
                    }
                    Text {
                        visible: root.visibleEventCount() === 0
                        width: parent.width
                        height: 54
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: Text.AlignHCenter
                        text: "NO EVENTS MATCH THE CURRENT FILTER"
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
