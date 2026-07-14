import { Link } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { initializeDatabase } from '@/database/client';
import { getDashboardSummary } from '@/database/dashboard';
import type { DashboardSummary } from '@/database/types';
import { getTeleDriveNativeModule, isTeleDriveNativeModuleAvailable } from '@/native/TeleDriveModule';
import { formatBytes } from '@/utils/format';
import { subscribe, type ActiveUpload } from '@/services/uploadProgress';
import { getAuthState, onAuthStateChanged, type AuthState } from '@/services/tdlib';

const emptySummary: DashboardSummary = {
  pendingCount: 0,
  uploadingCount: 0,
  failedCount: 0,
  uploadedTodayCount: 0,
  uploadedTodayBytes: 0,
  recentUploads: [],
};

function calcSpeed(upload: ActiveUpload): number {
  const elapsed = (Date.now() - upload.startedAt) / 1000;
  if (elapsed <= 0) return 0;
  return upload.bytesTransferred / elapsed;
}

function calcEta(upload: ActiveUpload): string {
  const remaining = upload.totalBytes - upload.bytesTransferred;
  const speed = calcSpeed(upload);
  if (speed <= 0 || remaining <= 0) return '';
  const secs = remaining / speed;
  if (secs < 60) return `${Math.round(secs)}s`;
  if (secs < 3600) return `${Math.round(secs / 60)}m ${Math.round(secs % 60)}s`;
  return `${Math.round(secs / 3600)}h`;
}

export default function DashboardScreen() {
  const [summary, setSummary] = useState<DashboardSummary>(emptySummary);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isSyncing, setIsSyncing] = useState(false);
  const [activeUploads, setActiveUploads] = useState<ActiveUpload[]>([]);
  const [tdlibState, setTdlibState] = useState<AuthState>(getAuthState());

  const loadDashboard = useCallback(async () => {
    setIsLoading(true);
    setErrorMessage(null);
    try {
      await initializeDatabase();
      setSummary(await getDashboardSummary());
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Could not open the local upload database.');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadDashboard();
    const unsubUploads = subscribe(setActiveUploads);
    const unsubAuth = onAuthStateChanged(setTdlibState);
    return () => { unsubUploads(); unsubAuth(); };
  }, [loadDashboard]);

  // useEffect for setInterval removed — subscription in line 64 already triggers on data changes

  const startSync = async () => {
    setIsSyncing(true);
    setErrorMessage(null);
    try {
      await getTeleDriveNativeModule().syncNow();
      await loadDashboard();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Could not start synchronization.');
    } finally {
      setIsSyncing(false);
    }
  };

  const uploadingItems = activeUploads.filter((u) => u.status === 'uploading');

  function connectionColor(): string {
    if (!isTeleDriveNativeModuleAvailable) return '#f8c458';
    if (tdlibState === 'ready') return '#58d68d';
    if (tdlibState === 'closed') return '#ff5c7c';
    return '#f8c458';
  }

  return (
    <SafeAreaView style={styles.safeArea} edges={['top']}>
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.header}>
          <View>
            <Text style={styles.eyebrow}>TELEDRIVE</Text>
            <Text style={styles.title}>Your private Telegram backup</Text>
          </View>
          <View style={[styles.connectionDot, { backgroundColor: connectionColor() }]} />
        </View>

        {!isTeleDriveNativeModuleAvailable && (
          <View style={styles.notice}>
            <Text style={styles.noticeTitle}>Development build required</Text>
            <Text style={styles.noticeCopy}>
              The local dashboard is ready. Telegram login, folder access, and uploads become available after the Android development build includes TeleDrive native services.
            </Text>
          </View>
        )}

        {errorMessage && (
          <View style={styles.errorBox}>
            <Text style={styles.errorText}>{errorMessage}</Text>
            <Pressable onPress={() => void loadDashboard()} style={styles.retryButton}>
              <Text style={styles.retryText}>Retry</Text>
            </Pressable>
          </View>
        )}

        <View style={styles.card}>
          <Text style={styles.cardTitle}>Today</Text>
          {isLoading ? (
            <ActivityIndicator color="#49a7ff" />
          ) : (
            <View style={styles.statsRow}>
              <Stat value={String(summary.uploadedTodayCount)} label="uploaded" />
              <Stat value={formatBytes(summary.uploadedTodayBytes)} label="backed up" />
              <Stat value={String(summary.pendingCount)} label="waiting" />
              <Stat value={String(uploadingItems.length)} label="active" />
            </View>
          )}
        </View>

        {/* Active Upload Progress */}
        {uploadingItems.length > 0 && (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Uploading {uploadingItems.length} file{uploadingItems.length !== 1 ? 's' : ''}</Text>
            {uploadingItems.map((upload) => {
              const pct = upload.totalBytes > 0 ? Math.round((upload.bytesTransferred / upload.totalBytes) * 100) : 0;
              const speed = calcSpeed(upload);
              const eta = calcEta(upload);
              return (
                <View key={upload.queueItemId} style={styles.progressItem}>
                  <View style={styles.progressHeader}>
                    <Text numberOfLines={1} style={styles.progressName}>{upload.filename}</Text>
                    <Text style={styles.progressPct}>{pct}%</Text>
                  </View>
                  <View style={styles.progressTrack}>
                    <View style={[styles.progressBar, { width: `${pct}%` }]} />
                  </View>
                  <View style={styles.progressMeta}>
                    <Text style={styles.progressText}>
                      {formatBytes(upload.bytesTransferred)} / {formatBytes(upload.totalBytes)}
                    </Text>
                    <Text style={styles.progressText}>
                      {speed > 0 ? `${formatBytes(speed)}/s` : ''}{eta ? ` · ETA ${eta}` : ''}
                    </Text>
                  </View>
                </View>
              );
            })}
          </View>
        )}

        <Pressable
          accessibilityRole="button"
          disabled={isSyncing || !isTeleDriveNativeModuleAvailable}
          onPress={() => void startSync()}
          style={({ pressed }) => [styles.syncButton, (pressed || isSyncing || !isTeleDriveNativeModuleAvailable) && styles.buttonMuted]}>
          <Text style={styles.syncButtonText}>{isSyncing ? 'Starting sync…' : 'Sync now'}</Text>
        </Pressable>

        <View style={styles.navigationGrid}>
          <DashboardLink href="/folders" label="Folders" detail="Add sources" />
          <DashboardLink href="/topics" label="Topics" detail="Forum groups" />
          <DashboardLink href="/routing" label="Routing" detail="File rules" />
          <DashboardLink href="/(tabs)/queue" label="Queue" detail="See pending files" />
          <DashboardLink href="/(tabs)/history" label="History" detail="Find uploads" />
          <DashboardLink href="/(tabs)/settings" label="Settings" detail="Backup rules" />
        </View>

        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>Queue</Text>
          <Text style={styles.sectionMeta}>{summary.uploadingCount} active · {summary.failedCount} failed</Text>
        </View>
        {summary.recentUploads.length === 0 ? (
          <View style={styles.emptyState}>
            <Text style={styles.emptyTitle}>Nothing queued yet</Text>
            <Text style={styles.emptyCopy}>Connect Telegram and add a folder to create your first backup queue.</Text>
            <Link href="/onboarding" style={styles.setupLink}>Set up TeleDrive</Link>
          </View>
        ) : (
          summary.recentUploads.map((upload) => (
            <View key={upload.id} style={styles.queueItem}>
              <View style={styles.fileCopy}>
                <Text numberOfLines={1} style={styles.fileName}>{upload.filename}</Text>
                <Text style={styles.fileMeta}>{formatBytes(upload.fileSize)} · {upload.status}</Text>
              </View>
              <View style={[styles.statusPill,
                upload.status === 'failed' && styles.failedPill,
                upload.status === 'pending' && styles.pendingPill,
                upload.status === 'uploading' && styles.uploadingPill,
              ]}>
                <Text style={styles.statusText}>{upload.status}</Text>
              </View>
            </View>
          ))
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return <View><Text style={styles.statValue}>{value}</Text><Text style={styles.statLabel}>{label}</Text></View>;
}

function DashboardLink({ href, label, detail }: { href: string; label: string; detail: string }) {
  return <Link href={href as any} asChild><Pressable style={({ pressed }) => [styles.navigationCard, pressed && styles.buttonMuted]}><Text style={styles.navigationLabel}>{label}</Text><Text style={styles.navigationDetail}>{detail}</Text></Pressable></Link>;
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: '#09121f' }, content: { padding: 20, gap: 18, paddingBottom: 44 },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', paddingTop: 10 },
  eyebrow: { color: '#49a7ff', fontWeight: '800', fontSize: 12, letterSpacing: 1.5 }, title: { color: '#f7fbff', fontWeight: '700', fontSize: 28, maxWidth: 300, marginTop: 5 },
  connectionDot: { width: 10, height: 10, borderRadius: 5, marginTop: 9 },
  notice: { backgroundColor: '#152840', borderRadius: 14, padding: 16, gap: 5 }, noticeTitle: { color: '#ddecff', fontSize: 16, fontWeight: '700' }, noticeCopy: { color: '#b6c7dc', lineHeight: 20 },
  errorBox: { backgroundColor: '#44202a', borderRadius: 12, padding: 14, gap: 10 }, errorText: { color: '#ffd8df', lineHeight: 20 }, retryButton: { alignSelf: 'flex-start' }, retryText: { color: '#77bcff', fontWeight: '700' },
  card: { backgroundColor: '#101e30', borderRadius: 18, padding: 18, gap: 16 }, cardTitle: { color: '#d6e6f8', fontSize: 16, fontWeight: '700' }, statsRow: { flexDirection: 'row', justifyContent: 'space-between' }, statValue: { color: '#ffffff', fontSize: 22, fontWeight: '800' }, statLabel: { color: '#91a6bf', marginTop: 4, fontSize: 12 },
  progressItem: { gap: 4 },
  progressHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  progressName: { color: '#f1f7ff', fontWeight: '600', fontSize: 13, flex: 1 },
  progressPct: { color: '#62b2ff', fontWeight: '800', fontSize: 13, marginLeft: 8 },
  progressTrack: { height: 6, backgroundColor: '#0c1929', borderRadius: 3, overflow: 'hidden' },
  progressBar: { height: '100%', backgroundColor: '#248de9', borderRadius: 3 },
  progressMeta: { flexDirection: 'row', justifyContent: 'space-between' },
  progressText: { color: '#91a6bf', fontSize: 11 },
  syncButton: { minHeight: 54, borderRadius: 14, backgroundColor: '#248de9', alignItems: 'center', justifyContent: 'center' }, buttonMuted: { opacity: 0.55 }, syncButtonText: { color: '#ffffff', fontWeight: '800', fontSize: 16 },
  navigationGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 }, navigationCard: { backgroundColor: '#101e30', borderRadius: 14, padding: 14, width: '48%', gap: 4 }, navigationLabel: { color: '#f1f7ff', fontWeight: '700' }, navigationDetail: { color: '#91a6bf', fontSize: 12 },
  sectionHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline', marginTop: 8 }, sectionTitle: { color: '#f7fbff', fontWeight: '700', fontSize: 20 }, sectionMeta: { color: '#91a6bf', fontSize: 13 },
  emptyState: { backgroundColor: '#101e30', padding: 22, borderRadius: 18, gap: 8 }, emptyTitle: { color: '#eef7ff', fontWeight: '700', fontSize: 16 }, emptyCopy: { color: '#9db0c6', lineHeight: 20 }, setupLink: { color: '#62b2ff', fontWeight: '700', marginTop: 4 },
  queueItem: { backgroundColor: '#101e30', borderRadius: 14, padding: 14, flexDirection: 'row', alignItems: 'center', gap: 12 }, fileCopy: { flex: 1 }, fileName: { color: '#f1f7ff', fontWeight: '600' }, fileMeta: { color: '#91a6bf', marginTop: 4, fontSize: 12 }, statusPill: { backgroundColor: '#1f4a37', borderRadius: 10, paddingHorizontal: 8, paddingVertical: 4 }, failedPill: { backgroundColor: '#5a2633' }, pendingPill: { backgroundColor: '#8a7030' }, uploadingPill: { backgroundColor: '#248de9' }, statusText: { color: '#d7ffe8', fontSize: 11, fontWeight: '700', textTransform: 'uppercase' },
});
