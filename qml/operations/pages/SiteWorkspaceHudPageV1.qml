pragma ComponentBehavior: Bound
import QtQuick
import "../../components"

Item {
    id: root
    objectName: "siteWorkspaceHudPageV1"

    property QtObject projection: null
    property bool compact: width < 720
    property string selectedSiteId: ""
    signal proposalRequested(string kind, var payload)
    signal selectionRequested(string surface, string itemId)

    HudTypographyV1 { id: typography }

    readonly property var sites: projection ? projection.sites : []
    readonly property var siteFiles: projection ? projection.siteFiles : []

    function selectFirstSite() {
        if (sites.length === 0) {
            selectedSiteId = ""
            return
        }
        for (var i = 0; i < sites.length; ++i)
            if (sites[i].site_id === selectedSiteId)
                return
        selectedSiteId = sites[0].site_id
    }

    function visibleFileCount() {
        var count = 0
        for (var i = 0; i < siteFiles.length; ++i)
            if (siteFiles[i].site_id === selectedSiteId)
                count += 1
        return count
    }

    onSitesChanged: selectFirstSite()
    Component.onCompleted: selectFirstSite()

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
                eyebrow: "SITE WORKSPACE  /  GOVERNED PREVIEW"
                title: "Project Surfaces"
                detail: "Read-only project status. Preview actions are proposals resolved by the trusted host."
            }

            Flow {
                width: parent.width
                spacing: 10
                HudMetricTileV1 {
                    width: root.compact ? (contentColumn.width - 10) / 2 : 164
                    label: "Projects"
                    value: String(root.sites.length)
                    hint: "Visible workspaces"
                }
                HudMetricTileV1 {
                    width: root.compact ? (contentColumn.width - 10) / 2 : 164
                    label: "Active"
                    value: {
                        var count = 0
                        for (var i = 0; i < root.sites.length; ++i)
                            if (root.sites[i].status === "active")
                                count += 1
                        return String(count)
                    }
                    hint: "In progress"
                    active: Number(value) > 0
                }
            }

            Flow {
                id: siteGrid
                width: parent.width
                spacing: 10

                Repeater {
                    model: root.sites
                    HoloPanel {
                        id: siteCard
                        required property var modelData
                        width: root.compact ? siteGrid.width
                                            : Math.max(240, (siteGrid.width - 10) / 2)
                        height: 154
                        radius: 18
                        edgeColor: root.selectedSiteId === modelData.site_id
                                   ? Qt.rgba(.10, .78, .75, .44) : "#1B2227"
                        surfaceColor: Qt.rgba(.039, .051, .059, .66)

                        Column {
                            anchors.fill: parent
                            anchors.margins: 16
                            spacing: 7
                            Text {
                                text: siteCard.modelData.status.toUpperCase() + "  /  " + siteCard.modelData.preview_state.toUpperCase()
                                color: siteCard.modelData.status === "active" ? "#19C7C0" : "#8C949E"
                                opacity: .74
                                font.family: typography.monoFamily
                                font.pixelSize: 8
                                font.letterSpacing: 1.2
                            }
                            Text {
                                width: parent.width
                                text: siteCard.modelData.name
                                color: "#C7C9CC"
                                elide: Text.ElideRight
                                font.family: typography.displayFamily
                                font.pixelSize: 16
                                font.weight: Font.Medium
                            }
                            Text {
                                width: parent.width
                                text: "BRANCH  /  " + siteCard.modelData.branch
                                color: "#8C949E"
                                opacity: .66
                                elide: Text.ElideMiddle
                                font.family: typography.monoFamily
                                font.pixelSize: 8
                            }
                            Text {
                                text: "UPDATED  /  " + siteCard.modelData.updated_label
                                color: "#8C949E"
                                opacity: .52
                                font.family: typography.bodyFamily
                                font.pixelSize: 8
                            }
                            ActionButtonV3 {
                                label: "PREVIEW PROPOSAL"
                                accessibleName: "Propose preview for " + siteCard.modelData.name
                                emphasized: siteCard.modelData.status === "active"
                                onTriggered: {
                                    root.selectedSiteId = siteCard.modelData.site_id
                                    root.selectionRequested("sites", siteCard.modelData.site_id)
                                    root.proposalRequested("site_preview", {"site_id": siteCard.modelData.site_id})
                                }
                            }
                        }
                    }
                }
            }

            HoloPanel {
                visible: root.sites.length > 0
                width: parent.width
                height: Math.max(150, fileColumn.height + 28)
                radius: 18
                surfaceColor: Qt.rgba(.039, .051, .059, .56)

                Column {
                    id: fileColumn
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 14
                    spacing: 8

                    Text {
                        text: "PROJECTED FILE TREE  /  " + root.visibleFileCount()
                        color: "#8C949E"
                        opacity: .62
                        font.family: typography.monoFamily
                        font.pixelSize: 8
                        font.letterSpacing: 1.3
                    }
                    Text {
                        width: parent.width
                        text: "Metadata projection only. Selection cannot read or modify local files."
                        color: "#8C949E"
                        opacity: .58
                        wrapMode: Text.WordWrap
                        font.family: typography.bodyFamily
                        font.pixelSize: 9
                    }
                    Repeater {
                        model: root.siteFiles
                        HudDataRowV1 {
                            required property var modelData
                            width: fileColumn.width
                            visible: modelData.site_id === root.selectedSiteId
                            height: visible ? implicitHeight : 0
                            eyebrow: modelData.kind + "  /  " + modelData.state
                            title: Array(Number(modelData.depth) + 1).join("  ") + modelData.name
                            detail: "Projected workspace entry"
                            trailing: modelData.state
                            active: modelData.state === "modified" || modelData.state === "added"
                            accessibleName: "Select projected entry " + modelData.name
                            onActivated: root.selectionRequested("sites", modelData.file_id)
                        }
                    }
                    Text {
                        visible: root.visibleFileCount() === 0
                        width: parent.width
                        height: 46
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: Text.AlignHCenter
                        text: "NO FILE METADATA IN THE CURRENT PROJECTION"
                        color: "#8C949E"
                        opacity: .54
                        font.family: typography.monoFamily
                        font.pixelSize: 8
                        font.letterSpacing: 1.0
                    }
                }
            }

            HoloPanel {
                visible: root.sites.length === 0
                width: parent.width
                height: 92
                radius: 18
                Text {
                    anchors.centerIn: parent
                    text: "NO SITE PROJECTS IN THE CURRENT PROJECTION"
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
