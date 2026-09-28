// ClipBlitz Studio, standalone: the phone runs the engine itself.
//
// This is deliberately a separate build from ../../android (the thin companion shell).
// The companion is built by hand with aapt2/javac/d8 and stays the shipped APK until the
// milestones in README.md are done; this project is where the on-device engine is built.
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "ClipBlitzStandalone"
include(":app")
