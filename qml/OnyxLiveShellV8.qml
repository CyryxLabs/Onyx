import QtQuick
import "components"

OnyxLiveShellV7 {
    id: root
    objectName: "onyxLiveShellV8Root"

    OnyxOrbVoiceLayerV8 {
        id: voiceParticles
        projection: root.uiProjection
        x: root.compact ? -width * .04 : root.width * .18
        y: root.height * .04
        width: root.compact ? root.width * 1.08 : root.width * .70
        height: root.height * .72
        z: 2
    }
}
