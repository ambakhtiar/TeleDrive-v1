const { withAndroidManifest, withAppBuildGradle, withDangerousMod } = require('@expo/config-plugins');
const fs = require('fs');
const path = require('path');

const ANDROID_PERMISSIONS = [
  'android.permission.FOREGROUND_SERVICE',
  'android.permission.FOREGROUND_SERVICE_DATA_SYNC',
  'android.permission.POST_NOTIFICATIONS',
  'android.permission.INTERNET',
  'android.permission.ACCESS_NETWORK_STATE',
  'android.permission.ACCESS_WIFI_STATE',
  'android.permission.WAKE_LOCK',
  'android.permission.RECEIVE_BOOT_COMPLETED',
];

function withPermissions(config) {
  return withAndroidManifest(config, (androidConfig) => {
    const manifest = androidConfig.modResults.manifest;
    const existing = new Set(
      (manifest['uses-permission'] ?? []).map((permission) => permission.$?.['android:name']),
    );
    const missing = ANDROID_PERMISSIONS
      .filter((permission) => !existing.has(permission))
      .map((permission) => ({ $: { 'android:name': permission } }));
    manifest['uses-permission'] = [...(manifest['uses-permission'] ?? []), ...missing];
    return androidConfig;
  });
}

function withWorkManagerDependency(config) {
  return withAppBuildGradle(config, (config) => {
    if (config.modResults.contents.includes('security-crypto')) {
      return config;
    }
    config.modResults.contents = config.modResults.contents.replace(
      /dependencies \{/,
      `dependencies {
    implementation("androidx.work:work-runtime-ktx:2.10.1")
    implementation("androidx.security:security-crypto:1.1.0")`
    );
    return config;
  });
}

function withNativeModule(config) {
  return withDangerousMod(config, [
    'android',
    (config) => {
      const projectRoot = config.modRequest.platformProjectRoot;
      const pkg = path.join(projectRoot, 'app/src/main/java/com/ambakhtiar/teledrive');
      const pluginDir = path.resolve(__dirname, 'kotlin/com/ambakhtiar/teledrive');

      if (!fs.existsSync(pkg)) {
        fs.mkdirSync(pkg, { recursive: true });
      }

      const files = [
        'TeleDriveModule.kt',
        'TeleDrivePackage.kt',
        'TeleDriveForegroundService.kt',
        'UploadWorker.kt',
        'BootReceiver.kt',
        'NativeUploader.kt',
        'BackgroundUploader.kt',
        'DatabaseHelper.kt',
        'SecurePrefs.kt',
      ];
      for (const file of files) {
        const src = path.join(pluginDir, file);
        const dest = path.join(pkg, file);
        if (fs.existsSync(src)) {
          fs.copyFileSync(src, dest);
        }
      }

      return config;
    },
  ]);
}

function withPackageRegistration(config) {
  return withDangerousMod(config, [
    'android',
    (config) => {
      const projectRoot = config.modRequest.platformProjectRoot;
      const mainApp = path.join(projectRoot, 'app/src/main/java/com/ambakhtiar/teledrive/MainApplication.kt');

      if (!fs.existsSync(mainApp)) return config;

      let content = fs.readFileSync(mainApp, 'utf-8');
      if (!content.includes('TeleDrivePackage')) {
        const marker = 'PackageList(this).packages.apply {';
        const idx = content.indexOf(marker);
        if (idx >= 0) {
          const insertAt = idx + marker.length;
          content = content.slice(0, insertAt) + '\n          add(TeleDrivePackage())\n        ' + content.slice(insertAt);
          fs.writeFileSync(mainApp, content);
        }
      }

      return config;
    },
  ]);
}

function withBootReceiver(config) {
  return withAndroidManifest(config, (androidConfig) => {
    const manifest = androidConfig.modResults.manifest;
    const application = manifest['application']?.[0];
    if (application) {
      const receivers = application['receiver'] ?? [];
      const hasBootReceiver = receivers.some(
        (r) => r.$?.['android:name'] === '.BootReceiver',
      );
      if (!hasBootReceiver) {
        application['receiver'] = [
          ...receivers,
          {
            $: {
              'android:name': '.BootReceiver',
              'android:exported': 'false',
            },
            'intent-filter': [
              {
                action: [{ $: { 'android:name': 'android.intent.action.BOOT_COMPLETED' } }],
              },
            ],
          },
        ];
      }
    }
    return androidConfig;
  });
}

function withForegroundService(config) {
  return withAndroidManifest(config, (androidConfig) => {
    const manifest = androidConfig.modResults.manifest;
    const application = manifest['application']?.[0];
    if (!application) return androidConfig;
    const services = application['service'] ?? [];
    const hasService = services.some(
      (s) => s.$?.['android:name'] === '.TeleDriveForegroundService',
    );
    if (!hasService) {
      application['service'] = [
        ...services,
        {
          $: {
            'android:name': '.TeleDriveForegroundService',
            'android:exported': 'false',
            'android:foregroundServiceType': 'dataSync',
          },
        },
      ];
    }
    return androidConfig;
  });
}

function withProguardRules(config) {
  return withDangerousMod(config, [
    'android',
    (config) => {
      const projectRoot = config.modRequest.platformProjectRoot;
      const proguardFile = path.join(projectRoot, 'app/proguard-rules.pro');
      const rules = `
# TeleDrive: keep the react-native-tdlib client so reflection from the
# TeleDriveModule / NativeUploader (getLiveTdLibClient) keeps working under R8.
-keep class com.reactnativetdlib.tdlibclient.TdLibModule { *; }
-keepclassmembers class com.reactnativetdlib.tdlibclient.TdLibModule {
    private org.drinkless.tdlib.Client client;
}
-keep class org.drinkless.tdlib.** { *; }
`;
      let content = fs.existsSync(proguardFile) ? fs.readFileSync(proguardFile, 'utf-8') : '';
      if (!content.includes('reactnativetdlib.tdlibclient.TdLibModule')) {
        content += rules;
        fs.writeFileSync(proguardFile, content);
      }
      return config;
    },
  ]);
}

function withTeleDrive(config) {
  config = withPermissions(config);
  config = withWorkManagerDependency(config);
  config = withNativeModule(config);
  config = withPackageRegistration(config);
  config = withBootReceiver(config);
  config = withForegroundService(config);
  config = withProguardRules(config);
  return config;
}

module.exports = withTeleDrive;
