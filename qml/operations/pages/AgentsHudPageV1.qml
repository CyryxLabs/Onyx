pragma ComponentBehavior: Bound
import QtQuick
import "../../components"

Item {
    id: root
    objectName: "agentsHudPageV1"

    property QtObject projection: null
    property bool compact: width < 820
    property string selectedAgentId: ""
    signal proposalRequested(string kind, var payload)
    signal selectionRequested(string surface, string itemId)

    HudTypographyV1 { id: typography }

    readonly property var agents: projection ? projection.agents : []
    readonly property var inbox: projection ? projection.inbox : []
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
                eyebrow: "AGENT OPERATIONS  /  ROSTER"
                title: "Delegation Console"
                detail: "Select an agent, then an inbox item, to emit a delegation proposal."
            }

            Flow {
                width: parent.width
                spacing: 10
                HudMetricTileV1 {
                    width: root.compact ? (contentColumn.width - 10) / 2 : 164
                    label: "Active agents"
                    value: String(root.metrics.active_agents || 0)
                    hint: "Currently assigned"
                    active: Number(root.metrics.active_agents || 0) > 0
                }
                HudMetricTileV1 {
                    width: root.compact ? (contentColumn.width - 10) / 2 : 164
                    label: "Inbox"
                    value: String(root.inbox.length)
                    hint: "Awaiting triage"
                }
            }

            Flow {
                id: agentPanels
                width: parent.width
                spacing: 12

                HoloPanel {
                    width: root.compact ? agentPanels.width : (agentPanels.width - 12) * .52
                    height: Math.max(170, rosterColumn.height + 28)
                    radius: 18
                    surfaceColor: Qt.rgba(.039, .051, .059, .60)
                    Column {
                        id: rosterColumn
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 14
                        spacing: 8
                        Text {
                            text: "COMMAND UNIT ROSTER  /  " + root.agents.length
                            color: "#8C949E"
                            opacity: .62
                            font.family: typography.monoFamily
                            font.pixelSize: 8
                            font.letterSpacing: 1.3
                        }
                        Repeater {
                            model: root.agents
                            HudDataRowV1 {
                                required property var modelData
                                width: rosterColumn.width
                                eyebrow: modelData.role + "  /  " + modelData.status
                                title: modelData.name
                                detail: modelData.task
                                trailing: modelData.load_label
                                active: modelData.status === "active" || modelData.status === "running"
                                selected: root.selectedAgentId === modelData.agent_id
                                accessibleName: "Select agent " + modelData.name
                                onActivated: {
                                    root.selectedAgentId = modelData.agent_id
                                    root.selectionRequested("agents", modelData.agent_id)
                                }
                            }
                        }
                    }
                }

                HoloPanel {
                    width: root.compact ? agentPanels.width : (agentPanels.width - 12) * .48
                    height: Math.max(170, inboxColumn.height + 28)
                    radius: 18
                    edgeColor: root.selectedAgentId.length > 0
                               ? Qt.rgba(.10, .78, .75, .44) : "#1B2227"
                    surfaceColor: Qt.rgba(.039, .051, .059, .60)
                    Column {
                        id: inboxColumn
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 14
                        spacing: 8
                        Text {
                            text: root.selectedAgentId.length > 0
                                  ? "INBOX  /  SELECT WORK"
                                  : "INBOX  /  SELECT AN AGENT FIRST"
                            color: root.selectedAgentId.length > 0 ? "#19C7C0" : "#8C949E"
                            opacity: .68
                            font.family: typography.monoFamily
                            font.pixelSize: 8
                            font.letterSpacing: 1.2
                        }
                        Repeater {
                            model: root.inbox
                            HudDataRowV1 {
                                required property var modelData
                                width: inboxColumn.width
                                enabled: root.selectedAgentId.length > 0
                                eyebrow: modelData.source + "  /  " + modelData.status
                                title: modelData.title
                                detail: "Delegation proposal only"
                                trailing: modelData.age_label
                                accessibleName: "Propose delegation of " + modelData.title
                                onActivated: {
                                    root.selectionRequested("agents", modelData.inbox_id)
                                    root.proposalRequested("agent_delegate", {
                                        "agent_id": root.selectedAgentId,
                                        "inbox_id": modelData.inbox_id
                                    })
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
