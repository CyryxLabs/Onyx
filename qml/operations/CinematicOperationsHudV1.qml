pragma ComponentBehavior: Bound
import QtQuick
import "../components"

Item {
    id: root
    objectName: "cinematicOperationsHudV1"
    width: parent ? parent.width : 1280
    height: parent ? parent.height : 800

    property QtObject projection: null
    readonly property bool compact: width < 880 || height < 620
    readonly property bool reducedMotion: !projection || projection.reducedMotion
    readonly property string activePage: projection ? projection.activePage : "goals"
    readonly property var navigation: [
        {"page": "goals", "label": "GOALS"},
        {"page": "workflow", "label": "WORKFLOW"},
        {"page": "devices", "label": "DEVICES"},
        {"page": "sites", "label": "SITES"},
        {"page": "agents", "label": "AGENTS"},
        {"page": "analytics", "label": "TIMELINE"}
    ]

    signal navigationRequested(string page)
    signal selectionRequested(string surface, string itemId)
    signal proposalRequested(string kind, var payload)

    HudTypographyV1 { id: typography }

    enabled: projection !== null && projection.enabled
    visible: enabled

    function navigate(page) {
        if (projection && projection.requestNavigation(page))
            navigationRequested(page)
    }

    function selectItem(surface, itemId) {
        if (projection && projection.requestSelection(surface, itemId))
            selectionRequested(surface, itemId)
    }

    function propose(kind, payload) {
        if (projection && projection.requestProposal(kind, payload))
            proposalRequested(kind, payload)
    }

    Rectangle {
        anchors.fill: parent
        color: "#050607"
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#0A0D0F" }
            GradientStop { position: 0.54; color: "#050607" }
            GradientStop { position: 1.0; color: "#0A0D0F" }
        }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 2
        color: "#0F6B68"
        opacity: .68
    }

    Item {
        id: header
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: root.compact ? 18 : 28
        anchors.rightMargin: root.compact ? 18 : 28
        anchors.topMargin: root.compact ? 14 : 20
        height: root.compact ? 52 : 60

        Column {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            spacing: 2
            Text {
                text: "ONYX  /  OPERATIONS"
                color: "#C7C9CC"
                font.family: typography.displayFamily
                font.pixelSize: root.compact ? 17 : 21
                font.weight: Font.DemiBold
                font.letterSpacing: 2.2
            }
            Text {
                text: "CYRYX LABS  ·  GOVERNED INTELLIGENCE SURFACE"
                color: "#8C949E"
                opacity: .62
                font.family: typography.monoFamily
                font.pixelSize: root.compact ? 7 : 8
                font.letterSpacing: 1.2
            }
        }

        Row {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8
            StatusPill {
                label: root.projection ? root.projection.statusLabel : "STANDBY"
                active: root.projection && root.projection.enabled
            }
            StatusPill {
                visible: !root.compact
                label: root.reducedMotion ? "MOTION REDUCED" : "MOTION READY"
                active: false
            }
        }
    }

    HoloPanel {
        id: desktopRail
        objectName: "operationsDesktopRailV1"
        visible: !root.compact
        anchors.left: parent.left
        anchors.top: header.bottom
        anchors.bottom: parent.bottom
        anchors.leftMargin: 28
        anchors.topMargin: 16
        anchors.bottomMargin: 24
        width: 176
        radius: 20
        surfaceColor: Qt.rgba(.039, .051, .059, .58)

        Column {
            anchors.fill: parent
            anchors.margins: 14
            spacing: 9
            Text {
                text: "OPERATING LAYERS"
                color: "#8C949E"
                opacity: .54
                font.family: typography.monoFamily
                font.pixelSize: 8
                font.letterSpacing: 1.3
            }
            Repeater {
                model: root.navigation
                ActionButtonV3 {
                    required property var modelData
                    objectName: "operationsNav_" + modelData.page
                    width: 148
                    label: modelData.label
                    emphasized: root.activePage === modelData.page
                    accessibleName: "Open " + modelData.label + " operations"
                    onTriggered: root.navigate(modelData.page)
                }
            }
            Item { width: 1; height: 10 }
            Rectangle {
                width: parent.width
                height: 1
                color: "#1B2227"
            }
            Text {
                width: parent.width
                text: "PROJECTION ONLY\nNO DIRECT EXECUTION"
                color: "#8C949E"
                opacity: .48
                wrapMode: Text.WordWrap
                font.family: typography.monoFamily
                font.pixelSize: 7
                font.letterSpacing: 1.0
                lineHeight: 1.5
            }
        }
    }

    Flickable {
        id: compactNavigation
        objectName: "operationsCompactNavigationV1"
        visible: root.compact
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: header.bottom
        anchors.leftMargin: 18
        anchors.rightMargin: 18
        anchors.topMargin: 8
        height: 38
        contentWidth: compactNavigationRow.width
        contentHeight: height
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        Row {
            id: compactNavigationRow
            height: parent.height
            spacing: 7
            Repeater {
                model: root.navigation
                ActionButtonV3 {
                    required property var modelData
                    objectName: "operationsCompactNav_" + modelData.page
                    height: 32
                    label: modelData.label
                    emphasized: root.activePage === modelData.page
                    accessibleName: "Open " + modelData.label + " operations"
                    onTriggered: root.navigate(modelData.page)
                }
            }
        }
    }

    Loader {
        id: pageLoader
        objectName: "operationsPageLoaderV1"
        anchors.left: root.compact ? parent.left : desktopRail.right
        anchors.right: parent.right
        anchors.top: root.compact ? compactNavigation.bottom : header.bottom
        anchors.bottom: parent.bottom
        anchors.leftMargin: root.compact ? 18 : 18
        anchors.rightMargin: root.compact ? 18 : 28
        anchors.topMargin: root.compact ? 14 : 16
        anchors.bottomMargin: root.compact ? 14 : 24
        asynchronous: false
        source: {
            if (root.activePage === "workflow")
                return "pages/WorkflowHudPageV1.qml"
            if (root.activePage === "devices")
                return "pages/DevicesHudPageV1.qml"
            if (root.activePage === "sites")
                return "pages/SiteWorkspaceHudPageV1.qml"
            if (root.activePage === "agents")
                return "pages/AgentsHudPageV1.qml"
            if (root.activePage === "analytics")
                return "pages/AnalyticsHudPageV1.qml"
            return "pages/GoalsHudPageV1.qml"
        }
        onLoaded: {
            if (item) {
                item.projection = root.projection
                item.compact = root.compact
            }
        }
    }

    Connections {
        target: pageLoader.item
        ignoreUnknownSignals: true
        function onProposalRequested(kind, payload) {
            root.propose(kind, payload)
        }
        function onSelectionRequested(surface, itemId) {
            root.selectItem(surface, itemId)
        }
    }

    onProjectionChanged: {
        if (pageLoader.item)
            pageLoader.item.projection = projection
    }
    onCompactChanged: {
        if (pageLoader.item)
            pageLoader.item.compact = compact
    }
}
