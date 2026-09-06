import QtQuick
import QtQuick3D
import QtQuick3D.Particles3D

Item {
    id: root
    objectName: "onyxOrbRoot"

    // The Python bridge changes only on lifecycle transitions. Qt's scene
    // graph owns active rendering; there is no Python repaint timer here.
    readonly property bool simulationRunning: orbBridge.active
    readonly property int configuredParticleBudget: orbBridge.particleBudget

    Rectangle {
        anchors.fill: parent
        color: "#050607"
    }

    View3D {
        id: viewport
        anchors.fill: parent

        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Color
            clearColor: "#050607"
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: orbBridge.quality === "high"
                                 ? SceneEnvironment.High
                                 : SceneEnvironment.Medium
        }

        PerspectiveCamera {
            id: camera
            position: Qt.vector3d(0, 0, 520)
            clipNear: 10
            clipFar: 1600
        }
        camera: camera

        DirectionalLight {
            eulerRotation: Qt.vector3d(-28, -32, 0)
            brightness: 0.95
            color: "#C7C9CC"
        }
        PointLight {
            position: Qt.vector3d(90, 80, 220)
            brightness: 7.5
            color: "#19C7C0"
        }

        Model {
            source: "#Sphere"
            scale: Qt.vector3d(1.35, 1.35, 1.35)
            materials: PrincipledMaterial {
                baseColor: orbBridge.muted ? "#1B2227" : "#0F6B68"
                metalness: 0.72
                roughness: 0.28
                opacity: 0.82
                alphaMode: PrincipledMaterial.Blend
                emissiveFactor: orbBridge.muted
                                ? Qt.vector3d(0.03, 0.03, 0.03)
                                : Qt.vector3d(0.04, 0.54, 0.52)
            }
        }

        Component {
            id: neuralNode
            Model {
                source: "#Sphere"
                scale: Qt.vector3d(0.035, 0.035, 0.035)
                materials: PrincipledMaterial {
                    baseColor: "#C7C9CC"
                    roughness: 0.18
                    emissiveFactor: Qt.vector3d(0.10, 0.78, 0.75)
                }
            }
        }

        // API pattern follows Qt's ModelParticle3D and ParticleSystem3D
        // examples: https://doc.qt.io/qt-6/qml-qtquick3d-particles3d-modelparticle3d.html
        ParticleSystem3D {
            id: neuralField
            objectName: "neuralField"
            running: root.simulationRunning
            paused: !root.simulationRunning
            useRandomSeed: false
            seed: 481

            ModelParticle3D {
                id: neuralParticle
                delegate: neuralNode
                maxAmount: root.configuredParticleBudget
                color: "#B819C7C0"
                colorVariation: Qt.vector4d(0.18, 0.10, 0.08, 0.28)
                fadeInEffect: Particle3D.FadeOpacity
                fadeOutEffect: Particle3D.FadeOpacity
                fadeInDuration: 220
                fadeOutDuration: 520
            }

            ParticleEmitter3D {
                enabled: root.simulationRunning
                particle: neuralParticle
                emitRate: root.simulationRunning
                          ? Math.max(24, root.configuredParticleBudget / 3)
                          : 0
                lifeSpan: 3000
                lifeSpanVariation: 700
                particleScale: 0.75
                particleScaleVariation: 0.38
                scale: Qt.vector3d(1.55, 1.55, 1.55)
                shape: ParticleShape3D {
                    type: ParticleShape3D.Sphere
                    fill: true
                }
                velocity: VectorDirection3D {
                    direction: Qt.vector3d(0, 0, 0)
                    directionVariation: Qt.vector3d(4, 4, 4)
                }
            }

            PointRotator3D {
                enabled: root.simulationRunning
                pivotPoint: Qt.vector3d(0, 0, 0)
                direction: Qt.vector3d(0.25, 1, 0.12)
                magnitude: 8
            }
        }
    }
}
