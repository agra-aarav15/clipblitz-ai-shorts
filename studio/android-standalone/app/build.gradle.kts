plugins {
    id("com.android.application")
    id("com.chaquo.python")
}

android {
    namespace = "com.clipblitz.standalone"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.clipblitz.standalone"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "4.0.0"

        // Python 3.12 and newer ships 64-bit only, so arm64-v8a for real phones and
        // x86_64 so an emulator can run the same build.
        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    // The launcher icon is the same single source of truth as the companion app's:
    // scripts/make_icons.py writes ../../android/res, and this module points at it rather
    // than keeping a second copy that could drift.
    sourceSets.getByName("main") {
        res.srcDirs("../../android/res")
    }

    buildTypes {
        getByName("release") {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    packaging {
        resources.excludes += setOf("META-INF/*.kotlin_module")
    }
}

chaquopy {
    defaultConfig {
        version = "3.12"
    }
    sourceSets {
        getByName("main") {
            // src/main/python is staged by sync-python.py and is not committed;
            // src/android-python is the only place Android-only Python lives.
            setSrcDirs(listOf("src/main/python", "src/android-python"))
        }
    }
}
