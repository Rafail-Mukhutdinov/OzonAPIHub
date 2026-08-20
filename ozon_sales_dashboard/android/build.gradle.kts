allprojects {
    repositories {
        google()
        mavenCentral()
    }
}

// Принудительно заменяем старые версии SDK и Build Tools во всех плагинах
subprojects {
    afterEvaluate {
        if (project.hasProperty("android")) {
            val android = project.extensions.getByName("android")
            try {
                val compileSdkVersion = android.javaClass.getMethod("compileSdkVersion", Int::class.javaPrimitiveType)
                compileSdkVersion.invoke(android, 36)
                
                val buildToolsVersion = android.javaClass.getMethod("buildToolsVersion", String::class.java)
                buildToolsVersion.invoke(android, "36.0.0")
            } catch (e: Exception) {
                // If direct methods fail, try another way or ignore
            }
        }
    }
}

val newBuildDir: Directory =
    rootProject.layout.buildDirectory
        .dir("../../build")
        .get()
rootProject.layout.buildDirectory.value(newBuildDir)

subprojects {
    val newSubprojectBuildDir: Directory = newBuildDir.dir(project.name)
    project.layout.buildDirectory.value(newSubprojectBuildDir)
}
subprojects {
    project.evaluationDependsOn(":app")
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
