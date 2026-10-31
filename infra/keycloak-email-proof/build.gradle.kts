plugins { `java-library` }

group = "pl.roseru.calorie"
version = "1.0.0"
providers.gradleProperty("calorieBuildDir").orNull?.let { layout.buildDirectory.set(file(it)) }
repositories { mavenCentral() }
java { toolchain { languageVersion.set(JavaLanguageVersion.of(21)) } }
dependencies {
    compileOnly("org.keycloak:keycloak-services:26.8.1")
    testImplementation("org.keycloak:keycloak-services:26.8.1")
    testImplementation("org.junit.jupiter:junit-jupiter:5.11.4")
    testImplementation("org.mockito:mockito-core:5.15.2")
    testRuntimeOnly("org.jboss.resteasy:resteasy-core:6.2.14.Final")
}
tasks.test { useJUnitPlatform(); maxHeapSize = "256m"; maxParallelForks = 1 }
tasks.withType<JavaCompile>().configureEach { options.encoding = "UTF-8" }
tasks.jar { archiveBaseName.set("calorie-keycloak-email-proof") }
