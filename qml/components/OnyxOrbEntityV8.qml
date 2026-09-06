import QtQuick
import QtQuick.Effects

Item {
    id: entity
    objectName: "onyxOrbEntityV7Root"
    property var projection
    readonly property bool animated: projection && projection.animationRunning
    readonly property int governedFps: animated ? Math.min(12, Math.max(1, projection.targetFps)) : 0
    readonly property real sphereSize: Math.min(640, width * 0.72, height * 0.94)
    property real phase: 0

    Canvas {
        id: atmosphere
        anchors.fill: parent
        renderTarget: Canvas.Image
        onPaint: {
            var c = getContext("2d"); c.reset(); c.clearRect(0, 0, width, height)
            var cx = width * .52, cy = height * .48, r = entity.sphereSize * .5
            var halo = c.createRadialGradient(cx, cy, r * .28, cx, cy, r * 1.34)
            halo.addColorStop(0, "rgba(199,201,204,.22)")
            halo.addColorStop(.30, "rgba(25,199,192,.19)")
            halo.addColorStop(.66, "rgba(15,107,104,.075)")
            halo.addColorStop(1, "rgba(5,6,7,0)")
            c.fillStyle = halo; c.fillRect(0, 0, width, height)
        }
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
    }

    Item {
        id: sphere
        width: entity.sphereSize; height: width
        x: entity.width * .52 - width / 2
        y: entity.height * .48 - height / 2

        Image {
            id: neuralTexture
            anchors.fill: parent
            source: "../assets/onyx-orb-particle-v6.png"
            sourceSize.width: 1024; sourceSize.height: 1024
            fillMode: Image.PreserveAspectCrop
            smooth: true; mipmap: true; cache: true
            visible: false
        }
        Item {
            id: sphereMask
            anchors.fill: parent
            visible: false
            layer.enabled: true
            Rectangle {
                anchors.centerIn: parent; width: parent.width * .78; height: width
                radius: width / 2; color: "white"
            }
        }
        MultiEffect {
            id: maskedPresence
            anchors.fill: parent
            source: neuralTexture
            maskEnabled: true
            maskSource: sphereMask
            maskThresholdMin: .08
            maskSpreadAtMin: .06
            brightness: .04
            contrast: .13
            saturation: -.18
            opacity: !projection || projection.muted || projection.state === "OFFLINE" ? .56 : .96
        }

        Rectangle {
            anchors.centerIn: parent; width: parent.width * .105; height: width
            radius: width / 2; color: "#19C7C0"; opacity: .16
            layer.enabled: true
            layer.effect: MultiEffect { blurEnabled: true; blurMax: 42; blur: 1.0 }
        }
        Rectangle {
            anchors.centerIn: parent; width: parent.width * .028; height: width
            radius: width / 2; color: "#C7C9CC"; opacity: .92
        }
    }

    Timer {
        interval: entity.governedFps > 0 ? Math.max(83, 1000 / entity.governedFps) : 1000
        running: entity.governedFps > 0 && entity.visible
        repeat: true
        onTriggered: {
            entity.phase = (entity.phase + .012) % 6.283
            atmosphere.requestPaint()
        }
    }
}

