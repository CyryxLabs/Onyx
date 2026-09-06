import QtQuick
import "components"

OnyxLiveShellV12 {
    id: root
    objectName: "onyxLiveShellV14Root"

    OnyxHumanoidEntityV11 {
        id: humanoidPresence
        projection: root.uiProjection
        x: root.compact ? -width * .04 : root.width * .18
        y: root.height * .04
        width: root.compact ? root.width * 1.08 : root.width * .70
        height: root.height * .72
        z: 1
    }

    function setVisualAttention(x, y, source) {
        humanoidPresence.setAttention(x, y, source)
    }

    Component.onCompleted: {
        var predecessorOrb = root.findObject(root, "onyxOrbLiquidMetalV9Root")
        if (!predecessorOrb)
            throw new Error("Onyx Orb predecessor contract is unavailable")
        predecessorOrb.visible = false

        // V12's voice layer belongs to the retired Orb: its radial core and
        // spokes land over the humanoid's face.  V10 reacts to the same live
        // audio envelope in WebGL, so retaining this overlay would render two
        // competing speech visualisations.
        var predecessorVoiceLayer = root.findObject(root, "onyxOrbVoiceLayerV8")
        if (!predecessorVoiceLayer)
            throw new Error("Onyx Orb voice-layer contract is unavailable")
        predecessorVoiceLayer.visible = false
    }
}

