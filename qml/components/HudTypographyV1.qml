pragma ComponentBehavior: Bound
import QtQuick

QtObject {
    id: root
    objectName: "hudTypographyV1"

    // No font binary is bundled with Onyx today. These ordered families use
    // platform-native, redistributable system faces and terminate in Qt's
    // generic families. QML selects the first available face deterministically.
    readonly property list<string> displayFamilies: Qt.platform.os === "windows"
        ? ["Segoe UI Variable Display", "Segoe UI", "sans-serif"]
        : Qt.platform.os === "osx"
          ? ["SF Pro Display", ".AppleSystemUIFont", "sans-serif"]
          : ["Noto Sans", "DejaVu Sans", "sans-serif"]
    readonly property list<string> bodyFamilies: Qt.platform.os === "windows"
        ? ["Segoe UI Variable Text", "Segoe UI", "sans-serif"]
        : Qt.platform.os === "osx"
          ? ["SF Pro Text", ".AppleSystemUIFont", "sans-serif"]
          : ["Noto Sans", "DejaVu Sans", "sans-serif"]
    readonly property list<string> monoFamilies: Qt.platform.os === "windows"
        ? ["Cascadia Mono", "Consolas", "monospace"]
        : Qt.platform.os === "osx"
          ? ["SF Mono", "Menlo", "monospace"]
          : ["Noto Sans Mono", "DejaVu Sans Mono", "monospace"]

    function resolveFamily(candidates) {
        var available = Qt.fontFamilies()
        for (var candidateIndex = 0; candidateIndex < candidates.length; ++candidateIndex) {
            var candidate = candidates[candidateIndex]
            for (var familyIndex = 0; familyIndex < available.length; ++familyIndex)
                if (available[familyIndex].toLowerCase() === candidate.toLowerCase())
                    return available[familyIndex]
        }
        return candidates[candidates.length - 1]
    }

    readonly property string displayFamily: resolveFamily(displayFamilies)
    readonly property string bodyFamily: resolveFamily(bodyFamilies)
    readonly property string monoFamily: resolveFamily(monoFamilies)
}
