pragma ComponentBehavior: Bound
import QtQuick
import "../../components"

Item {
    id: root
    objectName: "workflowHudPageV1"

    property QtObject projection: null
    property bool compact: width < 820
    property string linkSourceId: ""
    signal proposalRequested(string kind, var payload)
    signal selectionRequested(string surface, string itemId)

    HudTypographyV1 { id: typography }

    readonly property var nodes: projection ? projection.workflowNodes : []
    readonly property var edges: projection ? projection.workflowEdges : []
    readonly property var catalog: projection ? projection.safeNodeCatalog : []
    readonly property string workflowId: nodes.length > 0
                                                 ? nodes[0].workflow_id
                                                 : "workflow.preview"

    function chooseNode(nodeId) {
        selectionRequested("workflow", nodeId)
        if (linkSourceId.length === 0) {
            linkSourceId = nodeId
            return
        }
        if (linkSourceId !== nodeId) {
            proposalRequested("workflow_connect", {
                "workflow_id": workflowId,
                "source": linkSourceId,
                "target": nodeId,
                "route": "next"
            })
        }
        linkSourceId = ""
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
                eyebrow: "AUTOMATION  /  SAFE GRAPH"
                title: "Workflow Operations"
                detail: "Select two nodes to propose a governed link. The catalog cannot express arbitrary execution."
            }

            Flow {
                id: workflowPanels
                width: parent.width
                spacing: 12

                HoloPanel {
                    width: root.compact ? workflowPanels.width
                                        : Math.max(236, workflowPanels.width * .30)
                    height: Math.max(230, catalogColumn.height + 28)
                    radius: 18
                    surfaceColor: Qt.rgba(.039, .051, .059, .64)

                    Column {
                        id: catalogColumn
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 14
                        spacing: 9

                        Text {
                            text: "SAFE NODE CATALOG  /  " + root.catalog.length
                            color: "#19C7C0"
                            opacity: .72
                            font.family: typography.monoFamily
                            font.pixelSize: 8
                            font.letterSpacing: 1.3
                        }
                        Text {
                            width: parent.width
                            text: "Each action emits a proposal. Execution remains outside this HUD."
                            color: "#8C949E"
                            opacity: .68
                            wrapMode: Text.WordWrap
                            font.family: typography.bodyFamily
                            font.pixelSize: 9
                            lineHeight: 1.35
                        }
                        Repeater {
                            model: root.catalog
                            ActionButtonV3 {
                                required property var modelData
                                width: catalogColumn.width
                                label: "+  " + modelData.label
                                accessibleName: "Propose " + modelData.label + " workflow node"
                                onTriggered: root.proposalRequested("workflow_node_add", {
                                    "workflow_id": root.workflowId,
                                    "kind": modelData.kind,
                                    "label": "New " + modelData.label
                                })
                            }
                        }
                    }
                }

                HoloPanel {
                    width: root.compact ? workflowPanels.width
                                        : workflowPanels.width - Math.max(236, workflowPanels.width * .30) - 12
                    height: Math.max(320, graphColumn.height + 28)
                    radius: 18
                    edgeColor: root.linkSourceId.length > 0
                               ? Qt.rgba(.10, .78, .75, .52) : "#1B2227"
                    surfaceColor: Qt.rgba(.039, .051, .059, .54)

                    Column {
                        id: graphColumn
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 14
                        spacing: 8

                        Row {
                            width: parent.width
                            spacing: 10
                            Text {
                                width: parent.width - linkHint.width - 10
                                text: "GRAPH MONITOR  /  " + root.nodes.length + " NODES"
                                color: "#8C949E"
                                opacity: .64
                                elide: Text.ElideRight
                                font.family: typography.monoFamily
                                font.pixelSize: 8
                                font.letterSpacing: 1.3
                            }
                            Text {
                                id: linkHint
                                text: root.linkSourceId.length > 0 ? "SELECT TARGET" : "SELECT SOURCE"
                                color: root.linkSourceId.length > 0 ? "#19C7C0" : "#8C949E"
                                opacity: .72
                                font.family: typography.monoFamily
                                font.pixelSize: 8
                            }
                        }

                        Repeater {
                            model: root.nodes
                            HudDataRowV1 {
                                required property var modelData
                                width: graphColumn.width
                                eyebrow: modelData.kind + "  /  " + modelData.status
                                title: modelData.label
                                detail: modelData.workflow_id
                                trailing: root.linkSourceId === modelData.node_id ? "SOURCE" : "NODE"
                                selected: root.linkSourceId === modelData.node_id
                                active: modelData.status === "active" || modelData.status === "running"
                                accessibleName: "Select workflow node " + modelData.label
                                onActivated: root.chooseNode(modelData.node_id)
                            }
                        }

                        Rectangle {
                            visible: root.nodes.length > 0 && root.edges.length > 0
                            width: parent.width
                            height: 1
                            color: "#1B2227"
                        }
                        Text {
                            visible: root.edges.length > 0
                            text: "DECLARED LINKS  /  " + root.edges.length
                            color: "#8C949E"
                            opacity: .54
                            font.family: typography.monoFamily
                            font.pixelSize: 8
                            font.letterSpacing: 1.2
                        }
                        Repeater {
                            model: root.edges
                            Text {
                                required property var modelData
                                width: graphColumn.width
                                text: modelData.source + "   ›   " + modelData.target + "   /   " + modelData.route.toUpperCase()
                                color: "#8C949E"
                                opacity: .70
                                elide: Text.ElideMiddle
                                font.family: typography.monoFamily
                                font.pixelSize: 8
                            }
                        }
                        Text {
                            visible: root.nodes.length === 0
                            width: parent.width
                            height: 54
                            verticalAlignment: Text.AlignVCenter
                            horizontalAlignment: Text.AlignHCenter
                            text: "NO WORKFLOW GRAPH IN THE CURRENT PROJECTION"
                            color: "#8C949E"
                            opacity: .54
                            font.family: typography.monoFamily
                            font.pixelSize: 8
                            font.letterSpacing: 1.0
                        }
                    }
                }
            }
        }
    }
}
