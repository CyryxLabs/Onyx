pragma ComponentBehavior: Bound
import QtQuick
import "../../components"

Item {
    id: root
    objectName: "goalsHudPageV1"

    property QtObject projection: null
    property bool compact: width < 720
    signal proposalRequested(string kind, var payload)
    signal selectionRequested(string surface, string itemId)

    HudTypographyV1 { id: typography }

    readonly property var goals: projection ? projection.goals : []
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
                eyebrow: "MISSION CONTROL  /  GOALS"
                title: "Operational Intent"
                detail: "Priorities, progress and attention signals from the governed goal projection."
            }

            Flow {
                width: parent.width
                spacing: 10

                HudMetricTileV1 {
                    width: root.compact ? (contentColumn.width - 10) / 2 : 164
                    label: "Active goals"
                    value: String(root.metrics.active_goals || 0)
                    hint: "In execution"
                    active: Number(root.metrics.active_goals || 0) > 0
                }
                HudMetricTileV1 {
                    width: root.compact ? (contentColumn.width - 10) / 2 : 164
                    label: "Visible goals"
                    value: String(root.goals.length)
                    hint: "Bounded projection"
                }
                HudMetricTileV1 {
                    width: root.compact ? (contentColumn.width - 10) / 2 : 164
                    label: "Attention"
                    value: {
                        var count = 0
                        for (var i = 0; i < root.goals.length; ++i)
                            if (root.goals[i].status === "attention" || root.goals[i].status === "blocked")
                                count += 1
                        return String(count)
                    }
                    hint: "Needs review"
                }
            }

            HoloPanel {
                width: parent.width
                height: Math.max(124, goalsColumn.height + 28)
                radius: 18
                surfaceColor: Qt.rgba(.039, .051, .059, .58)

                Column {
                    id: goalsColumn
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 14
                    spacing: 8

                    Text {
                        text: "GOAL ARRAY  /  " + root.goals.length
                        color: "#8C949E"
                        opacity: .62
                        font.family: typography.monoFamily
                        font.pixelSize: 8
                        font.letterSpacing: 1.5
                    }

                    Repeater {
                        model: root.goals

                        HudDataRowV1 {
                            required property var modelData
                            width: goalsColumn.width
                            eyebrow: modelData.priority + "  /  " + modelData.status
                            title: modelData.title
                            detail: modelData.detail
                            trailing: Math.round(Number(modelData.progress) * 100) + "%  " + modelData.due_label
                            active: modelData.status === "active"
                            accessibleName: "Focus goal " + modelData.title
                            onActivated: {
                                root.selectionRequested("goals", modelData.goal_id)
                                root.proposalRequested("goal_focus", {"goal_id": modelData.goal_id})
                            }
                        }
                    }

                    Text {
                        visible: root.goals.length === 0
                        width: parent.width
                        height: 54
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: Text.AlignHCenter
                        text: "NO GOALS IN THE CURRENT PROJECTION"
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
