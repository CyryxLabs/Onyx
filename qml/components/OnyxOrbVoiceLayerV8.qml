import QtQuick

Item {
    id: voiceLayer
    objectName: "onyxOrbVoiceLayerV8"
    property var projection
    readonly property bool speaking: projection && projection.state === "SPEAKING"
    readonly property real level: projection && projection.audioLevel !== undefined
                                   ? projection.audioLevel : 0
    readonly property int governedFps: speaking && projection.animationRunning
                                        ? Math.min(12, Math.max(1, projection.targetFps))
                                        : 0
    property real phase: 0
    // Smoothed amplitude so the equalizer/rays feel alive even at silence
    // (baseline breathing) and swell with the real voice level when fed.
    property real amp: 0.34
    enabled: false
    opacity: speaking ? 1 : 0

    Behavior on opacity {
        NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
    }

    Canvas {
        id: field
        anchors.fill: parent
        renderTarget: Canvas.Image
        onPaint: {
            var c = getContext("2d")
            c.reset()
            c.clearRect(0, 0, width, height)
            if (!voiceLayer.speaking)
                return

            var cx = width * .52
            var cy = height * .48
            var radius = Math.min(640, width * .72, height * .94) * .39
            var amp = voiceLayer.amp
            c.save()
            c.beginPath()
            c.arc(cx, cy, radius, 0, Math.PI * 2)
            c.clip()

            // Core glow — unchanged palette, breathing with phase + amplitude.
            var breath = .5 + .5 * Math.sin(voiceLayer.phase * 1.7)
            var glow = c.createRadialGradient(cx, cy, radius * .04,
                                              cx, cy, radius * .84)
            glow.addColorStop(0, "rgba(199,201,204," + (.22 + breath * .15 + amp * .13) + ")")
            glow.addColorStop(.22, "rgba(25,199,192," + (.11 + breath * .09 + amp * .11) + ")")
            glow.addColorStop(.68, "rgba(15,107,104,.035)")
            glow.addColorStop(1, "rgba(5,6,7,0)")
            c.fillStyle = glow
            c.fillRect(cx - radius, cy - radius, radius * 2, radius * 2)

            // Internal rays radiating from the core, pulsing with the voice.
            var rays = 22
            c.lineCap = "round"
            for (var r = 0; r < rays; ++r) {
                var ra = (r / rays) * Math.PI * 2 + voiceLayer.phase * .12
                var wobble = .5 + .5 * Math.sin(voiceLayer.phase * 1.9 + r * .8)
                var len = radius * (.28 + amp * .54 * (.45 + .55 * wobble))
                var ix = cx + Math.cos(ra) * radius * .12
                var iy = cy + Math.sin(ra) * radius * .12
                var ox = cx + Math.cos(ra) * len
                var oy = cy + Math.sin(ra) * len
                var rg = c.createLinearGradient(ix, iy, ox, oy)
                var ra0 = .10 + amp * .34 * wobble
                rg.addColorStop(0, "rgba(199,201,204," + ra0 + ")")
                rg.addColorStop(1, "rgba(25,199,192,0)")
                c.strokeStyle = rg
                c.lineWidth = 1.0 + amp * 1.5
                c.beginPath()
                c.moveTo(ix, iy)
                c.lineTo(ox, oy)
                c.stroke()
            }

            c.restore()
        }
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
    }

    Timer {
        interval: voiceLayer.governedFps > 0
                  ? Math.max(83, 1000 / voiceLayer.governedFps)
                  : 1000
        running: voiceLayer.governedFps > 0 && voiceLayer.visible
        repeat: true
        onTriggered: {
            voiceLayer.phase = (voiceLayer.phase + .085) % 6.283185307
            // Ease the amplitude toward a breathing baseline (so the orb is
            // clearly alive even before real audio is wired) plus the live voice
            // level so it swells with speech.
            var breath = .5 + .5 * Math.sin(voiceLayer.phase * 1.35)
            var targetAmp = .44 + .20 * breath
                            + .55 * Math.max(0, Math.min(1, voiceLayer.level))
            if (targetAmp > 1)
                targetAmp = 1
            voiceLayer.amp += (targetAmp - voiceLayer.amp) * .30
            field.requestPaint()
        }
    }

    onSpeakingChanged: {
        if (!speaking) {
            phase = 0
            amp = 0.44
            field.requestPaint()
        }
    }
}
