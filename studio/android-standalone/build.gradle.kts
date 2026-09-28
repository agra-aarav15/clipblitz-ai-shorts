// Plugin versions live here and nowhere else.
//
// Chaquopy ships CPython for Android; the engine is pure standard library, so there are no
// pip requirements to resolve and no native wheel to build. Chaquopy 17.0.0 accepts Android
// Gradle plugin 7.3.x through 9.2.x, so AGP 8.9.1 sits comfortably inside its tested range.
plugins {
    id("com.android.application") version "8.9.1" apply false
    id("com.chaquo.python") version "17.0.0" apply false
}
