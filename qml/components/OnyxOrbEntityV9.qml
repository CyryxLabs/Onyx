import QtQuick
import QtQuick.Effects

Item {
    id: entity
    objectName: "onyxOrbLiquidMetalV9Root"
    required property var projection
    readonly property bool animated: projection && projection.animationRunning
    readonly property bool reduced: !projection || projection.reducedMotion
    readonly property string operationalState: projection ? projection.state : "OFFLINE"
    readonly property real audio: operationalState === "SPEAKING"
                                  ? Math.max(0, Math.min(1, projection.audioLevel)) : 0
    readonly property int governedFps: animated && !reduced
                                       ? Math.min(24, Math.max(1, projection.targetFps)) : 0
    readonly property real sphereSize: Math.min(640, width * 0.72, height * 0.94)
    readonly property real stateEnergy: operationalState === "SPEAKING" ? .95
                                        : operationalState === "PROCESSING" ? .72
                                        : operationalState === "THINKING" ? .62
                                        : operationalState === "LISTENING" ? .38 : .20
    property real phase: 0
    readonly property real breath: reduced ? 0 : Math.sin(phase)
    readonly property real slowFlow: reduced ? 0 : Math.sin(phase * .47 + .8)
    readonly property real fastFlow: reduced ? 0 : Math.sin(phase * 1.31 + .2)

    Canvas {
        id: atmosphere
        anchors.fill: parent
        renderTarget: Canvas.Image
        onPaint: {
            var c = getContext("2d")
            c.reset(); c.clearRect(0, 0, width, height)
            var cx = width * .52, cy = height * .48, r = entity.sphereSize * .5
            var halo = c.createRadialGradient(cx, cy, r * .22, cx, cy, r * 1.38)
            halo.addColorStop(0, "rgba(199,201,204,.24)")
            halo.addColorStop(.28, "rgba(25,199,192,.20)")
            halo.addColorStop(.64, "rgba(15,107,104,.08)")
            halo.addColorStop(1, "rgba(5,6,7,0)")
            c.fillStyle = halo; c.fillRect(0, 0, width, height)
        }
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
    }

    Item {
        id: vessel
        objectName: "liquidMetalVesselV9"
        width: entity.sphereSize * (1 + entity.breath * (.008 + entity.stateEnergy * .004))
        height: entity.sphereSize * (1 - entity.breath * (.006 + entity.stateEnergy * .003))
        x: entity.width * .52 - width / 2 + entity.slowFlow * width * .003
        y: entity.height * .48 - height / 2 - entity.fastFlow * height * .002
        rotation: entity.slowFlow * (0.35 + entity.stateEnergy * .55)

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
                anchors.centerIn: parent
                width: parent.width * .78; height: parent.height * .78
                radius: Math.min(width, height) / 2; color: "#C7C9CC"
            }
        }
        MultiEffect {
            anchors.fill: parent
            source: neuralTexture
            maskEnabled: true; maskSource: sphereMask
            maskThresholdMin: .08; maskSpreadAtMin: .06
            brightness: .04; contrast: .13; saturation: -.18
            opacity: operationalState === "MUTED" || operationalState === "OFFLINE" ? .56 : .96
        }

        // A second, clipped copy drifts against the base texture. The tiny,
        // non-uniform offset reads as a viscous surface flow while preserving
        // the exact neural artwork and palette.
        Item {
            anchors.centerIn: parent
            width: parent.width * (1.002 + entity.slowFlow * .006)
            height: parent.height * (1.002 - entity.slowFlow * .005)
            x: entity.fastFlow * parent.width * .004
            y: entity.slowFlow * parent.height * .003
            opacity: entity.reduced ? .10 : .16 + entity.stateEnergy * .08
            Image {
                id: flowTexture
                anchors.fill: parent
                source: neuralTexture.source
                sourceSize.width: 1024; sourceSize.height: 1024
                fillMode: Image.PreserveAspectCrop
                smooth: true; mipmap: true; cache: true
                visible: false
            }
            MultiEffect {
                anchors.fill: parent
                source: flowTexture
                maskEnabled: true; maskSource: sphereMask
                maskThresholdMin: .08; maskSpreadAtMin: .06
                brightness: .10; contrast: .22; saturation: -.20
            }
        }

        // Restrained specular caustic: silver and teal only. It crosses the
        // surface slowly and accelerates with cognition/audio, never flashing.
        Rectangle {
            id: specularFlow
            objectName: "liquidMetalSpecularFlowV9"
            width: parent.width * .22; height: parent.height * .72
            radius: width / 2
            x: parent.width * (.39 + entity.slowFlow * .075 + entity.audio * .025)
            y: parent.height * (.13 + entity.fastFlow * .025)
            rotation: -24 + entity.fastFlow * 5
            opacity: entity.reduced ? .08 : .10 + entity.stateEnergy * .08 + entity.audio * .08
            gradient: Gradient {
                GradientStop { position: 0; color: "transparent" }
                GradientStop { position: .46; color: "#C7C9CC" }
                GradientStop { position: .62; color: "#19C7C0" }
                GradientStop { position: 1; color: "transparent" }
            }
            layer.enabled: true
            layer.effect: MultiEffect { blurEnabled: true; blurMax: 42; blur: 1 }
        }

        Rectangle {
            anchors.centerIn: parent
            width: parent.width * (.105 + entity.audio * .015); height: width
            radius: width / 2; color: "#19C7C0"; opacity: .16 + entity.audio * .10
            layer.enabled: true
            layer.effect: MultiEffect { blurEnabled: true; blurMax: 42; blur: 1 }
        }
        Rectangle {
            anchors.centerIn: parent; width: parent.width * .028; height: width
            radius: width / 2; color: "#C7C9CC"; opacity: .92
        }
    }

    Timer {
        interval: entity.governedFps > 0 ? Math.max(42, 1000 / entity.governedFps) : 1000
        running: entity.governedFps > 0 && entity.visible
        repeat: true
        onTriggered: {
            var velocity = entity.operationalState === "SPEAKING" ? .030 + entity.audio * .025
                         : entity.operationalState === "PROCESSING" ? .025
                         : entity.operationalState === "THINKING" ? .022
                         : .014
            entity.phase = (entity.phase + velocity) % 6.283185307
            atmosphere.requestPaint()
        }
    }
}
