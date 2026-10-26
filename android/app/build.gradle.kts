plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.ksp)
}

android {
    namespace = "pl.roseru.kalorie"
    compileSdk = 35
    defaultConfig {
        applicationId = "pl.roseru.kalorie"
        minSdk = 26
        targetSdk = 35
        versionCode = 51
        versionName = "0.8.40"
        // Public deployment configuration only. No credentials or client secret in the APK.
        val issuer = providers.gradleProperty("CALORIE_OIDC_ISSUER").orElse("").get()
        require(issuer.none { it == '\n' || it == '\r' || it == '"' || it == '\\' })
        resValue("string", "oidc_issuer", issuer)
        val apiBase = providers.gradleProperty("CALORIE_API_BASE_URL").orElse("").get()
        require(apiBase.none { it == '\n' || it == '\r' || it == '"' || it == '\\' })
        resValue("string", "api_base_url", apiBase)
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }
    buildFeatures { compose = true }
    // Device tests use a separate application and never uninstall the user's diary.
    buildTypes {
        create("validation") {
            initWith(getByName("debug"))
            applicationIdSuffix = ".validation"
            matchingFallbacks += "debug"
        }
    }
    testBuildType = "validation"
    // The regular APK has a no-op observer; HTTP receipts exist only in validation.
    sourceSets.getByName("debug").java.srcDir("src/standard/java")
    sourceSets.getByName("release").java.srcDir("src/standard/java")
    sourceSets.getByName("androidTest").assets.srcDir("$projectDir/schemas")
    sourceSets.getByName("androidTest").assets.srcDir("src/test/resources/photo")
    sourceSets.getByName("androidTest").assets.srcDir("src/test/resources/community")
    sourceSets.getByName("androidTest").assets.srcDir("src/test/resources/energy")
    // Real API driver is deliberately excluded from ordinary CI/device fixtures.
    if (providers.gradleProperty("O1_LIVE_API_RECEIPT_TEST").orElse("false").get() == "true") {
        sourceSets.getByName("androidTest").java.srcDir("src/liveReceipt/java")
    }
    if (providers.gradleProperty("O1_LIVE_E4_REPLAY_TEST").orElse("false").get() == "true") {
        sourceSets.getByName("androidTest").java.srcDir("src/liveReplay/java")
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    packaging { resources.excludes += "/META-INF/{AL2.0,LGPL2.1}" }
}

ksp { arg("room.schemaLocation", "$projectDir/schemas") }

// New migration fixtures must include the schema exported by the application compilation.
tasks.matching {it.name=="mergeValidationAndroidTestAssets"}.configureEach {dependsOn("kspValidationKotlin")}

// JVM catalogue tests read these files directly, so asset changes must invalidate their results.
tasks.withType<org.gradle.api.tasks.testing.Test>().configureEach {
    inputs.dir("src/main/assets/catalog").withPropertyName("catalogAssets")
        .withPathSensitivity(org.gradle.api.tasks.PathSensitivity.RELATIVE)
}

dependencies {
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.preview)
    implementation(libs.compose.material3)
    implementation(libs.compose.icons)
    implementation(libs.activity.compose)
    implementation(libs.lifecycle.viewmodel)
    implementation(libs.lifecycle.runtime)
    implementation(libs.navigation.compose)
    implementation(libs.room.runtime)
    implementation(libs.room.ktx)
    ksp(libs.room.compiler)
    implementation(libs.datastore.preferences)
    implementation("androidx.work:work-runtime-ktx:2.10.5")
    implementation(libs.appauth)
    implementation(libs.exifinterface)
    debugImplementation(libs.compose.tooling)
    debugImplementation(libs.compose.test.manifest)
    "validationImplementation"(libs.compose.tooling)
    "validationImplementation"(libs.compose.test.manifest)
    testImplementation(libs.junit)
    testImplementation("org.json:json:20240303")
    androidTestImplementation(platform(libs.compose.bom))
    androidTestImplementation(libs.compose.ui.test)
    androidTestImplementation(libs.android.test.runner)
    androidTestImplementation(libs.android.test.junit)
    androidTestImplementation("androidx.work:work-testing:2.10.5")
}

// Independent validation version channel prevents downgrading shared test data.
androidComponents {
    onVariants(selector().withBuildType("validation")) { variant ->
        variant.outputs.forEach { output ->
            output.versionCode.set(1000 + checkNotNull(android.defaultConfig.versionCode))
            output.versionName.set(checkNotNull(android.defaultConfig.versionName) + ".validation")
        }
    }
}
