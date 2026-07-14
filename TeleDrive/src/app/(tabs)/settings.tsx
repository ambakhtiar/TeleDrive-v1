import { useEffect, useState } from 'react';
import { ActivityIndicator, Alert, Linking, ScrollView, StyleSheet, Switch, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getDatabase, initializeDatabase } from '@/database/client';
import { getLocalSettings, type LocalSettings, setLocalSetting } from '@/database/settings';
import { getTeleDriveNativeModule, isTeleDriveNativeModuleAvailable } from '@/native/TeleDriveModule';
import { logoutTdLib } from '@/services/tdlib';

export default function SettingsScreen() {
  const [settings, setSettings] = useState<LocalSettings | null>(null);

  const syncToNative = async (next: LocalSettings) => {
    if (!isTeleDriveNativeModuleAvailable) return;
    try {
      await getTeleDriveNativeModule().syncSettings(next);
    } catch { /* native unavailable */ }
  };

  useEffect(() => {
    void (async () => {
      await initializeDatabase();
      const s = await getLocalSettings();
      setSettings(s);
      await syncToNative(s);
    })();
  }, []);

  const update = async <Key extends keyof LocalSettings>(key: Key, value: LocalSettings[Key]) => {
    await setLocalSetting(key, value);
    const next = await getLocalSettings();
    setSettings(next);
    await syncToNative(next);

    if (key === 'continuousBackup' && isTeleDriveNativeModuleAvailable) {
      try {
        const mod = getTeleDriveNativeModule();
        if (value) {
          await mod.scheduleContinuousBackup();
        } else {
          await mod.cancelContinuousBackup();
        }
      } catch (error) {
        Alert.alert('Background backup', error instanceof Error ? error.message : 'Could not update schedule.');
      }
    }
  };

  const handleLogout = () => {
    Alert.alert(
      'Sign out',
      'This will disconnect your Telegram account from TeleDrive. You can sign in again later.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Sign out',
          style: 'destructive',
          onPress: async () => {
            try {
              await logoutTdLib();
              Alert.alert('Signed out', 'Your Telegram session has been disconnected.');
            } catch (error) {
              Alert.alert('Logout failed', error instanceof Error ? error.message : 'Could not sign out.');
            }
          },
        },
      ],
    );
  };

  const handleBatteryOptimization = async () => {
    try {
      await Linking.openSettings();
    } catch {
      Alert.alert('Battery settings', 'Open your device Settings > Battery > Battery Optimization and disable it for TeleDrive.');
    }
  };

  const handleResetData = () => {
    Alert.alert(
      'Reset all data',
      'This will delete all upload history, folder sources, routing rules, and settings. This cannot be undone.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Reset',
          style: 'destructive',
          onPress: async () => {
            try {
              const db = await getDatabase();
              await db.execAsync(`
                DELETE FROM upload_queue;
                DELETE FROM folder_sources;
                DELETE FROM routing_rules;
                DELETE FROM upload_settings;
                DELETE FROM daily_upload_summaries;
              `);
              if (isTeleDriveNativeModuleAvailable) {
                try { await getTeleDriveNativeModule().cancelContinuousBackup(); } catch { /* ok */ }
              }
              const fresh = await getLocalSettings();
              setSettings(fresh);
              Alert.alert('Data reset', 'All local data has been cleared.');
            } catch (error) {
              Alert.alert('Reset failed', error instanceof Error ? error.message : 'Could not reset data.');
            }
          },
        },
      ],
    );
  };

  if (!settings) {
    return <SafeAreaView style={styles.safe}><ActivityIndicator style={styles.loader} color="#49a7ff" /></SafeAreaView>;
  }

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title}>Settings</Text>
        <Text style={styles.copy}>All settings live in this device&apos;s TeleDrive database.</Text>

        <Toggle
          label="Continuous backup"
          value={settings.continuousBackup}
          onChange={(value) => void update('continuousBackup', value)}
        />
        <Toggle
          label="Wi-Fi only"
          value={settings.wifiOnly}
          onChange={(value) => void update('wifiOnly', value)}
        />
        <Toggle
          label="Charging only"
          value={settings.chargingOnly}
          onChange={(value) => void update('chargingOnly', value)}
        />
        <Toggle
          label="Auto-delete after confirmed upload"
          value={settings.autoDelete}
          onChange={(value) => void update('autoDelete', value)}
        />

        <View style={styles.card}>
          <Text style={styles.label}>Max concurrent uploads</Text>
          <View style={styles.choice}>
            {[1, 2, 3, 4].map((count) => (
              <Text
                key={count}
                onPress={() => void update('maxConcurrentUploads', count)}
                style={[styles.option, settings.maxConcurrentUploads === count && styles.selected]}>
                {count}
              </Text>
            ))}
          </View>
        </View>

        <View style={styles.card}>
          <Text style={styles.label}>Upload speed limit</Text>
          <View style={styles.choice}>
            {[
              { label: 'None', value: 0 },
              { label: '64K', value: 64 },
              { label: '256K', value: 256 },
              { label: '512K', value: 512 },
              { label: '1M', value: 1024 },
            ].map((opt) => (
              <Text
                key={opt.value}
                onPress={() => void update('uploadSpeedLimitKBps', opt.value)}
                style={[styles.option, settings.uploadSpeedLimitKBps === opt.value && styles.selected]}>
                {opt.label}
              </Text>
            ))}
          </View>
          <Text style={styles.meta}>{settings.uploadSpeedLimitKBps > 0 ? `${settings.uploadSpeedLimitKBps} KB/s` : 'Unlimited'}</Text>
        </View>

        <View style={styles.sectionGap} />

        <Text style={styles.sectionTitle}>Account</Text>
        <View style={styles.card}>
          <Text style={styles.label}>Telegram session</Text>
          <Text onPress={handleLogout} style={styles.dangerAction}>Sign out</Text>
        </View>

        <Text style={styles.sectionTitle}>Device</Text>
        <View style={styles.card}>
          <Text style={styles.label}>Battery optimization</Text>
          <Text onPress={handleBatteryOptimization} style={styles.action}>Open settings</Text>
        </View>

        <View style={styles.sectionGap} />

        <Text style={styles.sectionTitle}>Danger zone</Text>
        <View style={styles.card}>
          <Text style={styles.label}>Reset all local data</Text>
          <Text onPress={handleResetData} style={styles.dangerAction}>Reset</Text>
        </View>

        <View style={styles.note}>
          <Text style={styles.noteTitle}>Privacy</Text>
          <Text style={styles.copy}>TeleDrive uses no remote database or analytics.</Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function Toggle({ label, value, onChange }: { label: string; value: boolean; onChange: (value: boolean) => void }) {
  return (
    <View style={styles.card}>
      <Text style={styles.label}>{label}</Text>
      <Switch value={value} onValueChange={onChange} />
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#09121f' },
  loader: { flex: 1 },
  content: { padding: 20, gap: 14, paddingBottom: 40 },
  title: { color: '#fff', fontSize: 28, fontWeight: '800' },
  copy: { color: '#aabdd0', lineHeight: 20 },
  card: { backgroundColor: '#101e30', borderRadius: 15, padding: 16, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  label: { color: '#eff7ff', fontWeight: '700', flex: 1 },
  choice: { flexDirection: 'row', gap: 8 },
  option: { color: '#b3c6db', paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8, backgroundColor: '#172a40' },
  selected: { backgroundColor: '#248de9', color: '#fff', fontWeight: '800' },
  action: { color: '#62b2ff', fontWeight: '700' },
  dangerAction: { color: '#ff6b7a', fontWeight: '700' },
  sectionTitle: { color: '#91a6bf', fontSize: 13, fontWeight: '700', textTransform: 'uppercase', letterSpacing: 0.5, marginTop: 6 },
  sectionGap: { height: 4 },
  meta: { color: '#91a6bf', fontSize: 11 },
  note: { padding: 16, borderRadius: 15, backgroundColor: '#152840', gap: 5 },
  noteTitle: { color: '#eff7ff', fontWeight: '800' },
});
