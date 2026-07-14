import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Alert, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { initializeDatabase } from '@/database/client';
import { deleteFolderSource, listFolderSources, saveFolderSource, setFolderSourceEnabled, updateFolderDisplayName, updateFolderFileFilter } from '@/database/folders';
import type { FolderSource } from '@/database/types';
import { getTeleDriveNativeModule, isTeleDriveNativeModuleAvailable } from '@/native/TeleDriveModule';
import { scanFolderAndEnqueue } from '@/services/scanner';
import { formatBytes } from '@/utils/format';

export default function FoldersScreen() {
  const [folders, setFolders] = useState<FolderSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState('');
  const [filteringId, setFilteringId] = useState<number | null>(null);
  const [editFilter, setEditFilter] = useState('');
  const [scanningId, setScanningId] = useState<number | null>(null);
  const [preview, setPreview] = useState<{ folder: FolderSource; fileCount: number; totalBytes: number } | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    await initializeDatabase();
    setFolders(await listFolderSources());
    setLoading(false);
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const addFolder = async () => {
    setAdding(true);
    setPreview(null);
    try {
      const selected = await getTeleDriveNativeModule().pickFolder();
      if (selected) {
        const files = await getTeleDriveNativeModule().scanFolder(selected.treeUri);
        const totalBytes = files.reduce((sum, f) => sum + f.size, 0);
        const tempFolder: FolderSource = {
          id: -1,
          treeUri: selected.treeUri,
          displayName: selected.displayName,
          chatId: null,
          topicId: null,
          enabled: true,
          fileFilter: null,
          createdAt: Date.now(),
          updatedAt: Date.now(),
        };
        setPreview({ folder: tempFolder, fileCount: files.length, totalBytes });
      }
    } catch (error) {
      Alert.alert('Could not pick folder', error instanceof Error ? error.message : 'Try again.');
    } finally {
      setAdding(false);
    }
  };

  const confirmAdd = async () => {
    if (!preview) return;
    try {
      await saveFolderSource(preview.folder.treeUri, preview.folder.displayName);
      setPreview(null);
      await refresh();
    } catch (error) {
      Alert.alert('Could not save folder', error instanceof Error ? error.message : 'Try again.');
    }
  };

  const cancelPreview = () => setPreview(null);

  const setEnabled = async (folder: FolderSource, enabled: boolean) => {
    await setFolderSourceEnabled(folder.id, enabled);
    await refresh();
  };

  const remove = (folder: FolderSource) => {
    Alert.alert('Remove folder?', `"${folder.displayName}" will no longer be scanned.`, [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Remove', style: 'destructive', onPress: () => void deleteFolderSource(folder.id).then(refresh) },
    ]);
  };

  const startEdit = (folder: FolderSource) => {
    setEditingId(folder.id);
    setEditName(folder.displayName);
  };

  const saveEdit = async () => {
    if (editingId == null) return;
    try {
      await updateFolderDisplayName(editingId, editName.trim());
      setEditingId(null);
      setEditName('');
      await refresh();
    } catch (error) {
      Alert.alert('Could not rename', error instanceof Error ? error.message : 'Try again.');
    }
  };

  const startFilterEdit = (folder: FolderSource) => {
    setFilteringId(folder.id);
    setEditFilter(folder.fileFilter ?? '');
  };

  const saveFilter = async () => {
    if (filteringId == null) return;
    try {
      const value = editFilter.trim() || null;
      await updateFolderFileFilter(filteringId, value);
      setFilteringId(null);
      setEditFilter('');
      await refresh();
    } catch (error) {
      Alert.alert('Could not save filter', error instanceof Error ? error.message : 'Try again.');
    }
  };

  const handleRescan = async (folder: FolderSource) => {
    setScanningId(folder.id);
    try {
      const result = await scanFolderAndEnqueue(folder);
      Alert.alert('Scan complete', `Found ${result.totalFiles} files, ${result.enqueued} new.`);
    } catch (error) {
      const msg = error instanceof Error ? error.message : '';
      if (msg.includes('Permission') || msg.includes('permission') || msg.includes('ACCESS')) {
        Alert.alert(
          'Permission lost',
          'TeleDrive can no longer access this folder. Grant access again to continue scanning.',
          [
            { text: 'Cancel', style: 'cancel' },
            {
              text: 'Grant access again',
              onPress: async () => {
                try {
                  const selected = await getTeleDriveNativeModule().pickFolder();
                  if (selected && selected.treeUri) {
                    const files = await getTeleDriveNativeModule().scanFolder(selected.treeUri);
                    await updateFolderDisplayName(folder.id, selected.displayName);
                    await refresh();
                    const enqueued = await scanFolderAndEnqueue({ ...folder, treeUri: selected.treeUri, displayName: selected.displayName });
                    Alert.alert('Re-linked', `Found ${files.length} files, ${enqueued.enqueued} new.`);
                  }
                } catch {
                  Alert.alert('Failed', 'Could not re-grant folder access.');
                }
              },
            },
          ],
        );
      } else {
        Alert.alert('Scan failed', msg || 'Could not scan folder.');
      }
    } finally {
      setScanningId(null);
    }
  };

  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title}>Folders</Text>
        <Text style={styles.copy}>Source folders that TeleDrive watches for new files.</Text>

        <Pressable
          disabled={!isTeleDriveNativeModuleAvailable || adding}
          onPress={() => void addFolder()}
          style={({ pressed }) => [styles.button, (pressed || adding || !isTeleDriveNativeModuleAvailable) && styles.muted]}
        >
          <Text style={styles.buttonText}>{adding ? 'Opening folder picker…' : 'Add folder'}</Text>
        </Pressable>

        {!isTeleDriveNativeModuleAvailable && (
          <Text style={styles.warning}>Development build required for folder access.</Text>
        )}

        {preview && (
          <View style={styles.previewCard}>
            <Text style={styles.previewTitle}>{preview.folder.displayName}</Text>
            <Text style={styles.previewStats}>
              {preview.fileCount} files · {formatBytes(preview.totalBytes)}
            </Text>
            <View style={styles.previewActions}>
              <Pressable onPress={() => void confirmAdd()} style={styles.previewConfirm}>
                <Text style={styles.previewConfirmText}>Add this folder</Text>
              </Pressable>
              <Pressable onPress={cancelPreview}>
                <Text style={styles.previewCancel}>Cancel</Text>
              </Pressable>
            </View>
          </View>
        )}

        {loading ? (
          <ActivityIndicator color="#49a7ff" />
        ) : folders.length === 0 ? (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>No folders</Text>
            <Text style={styles.copy}>Choose a root folder like Camera or DCIM.</Text>
          </View>
        ) : (
          folders.map((folder) => (
            <View key={folder.id} style={[styles.card, !folder.enabled && styles.disabled]}>
              <View style={styles.row}>
                <View style={styles.file}>
                  {editingId === folder.id ? (
                    <View style={styles.editRow}>
                      <TextInput
                        value={editName}
                        onChangeText={setEditName}
                        style={styles.editInput}
                        autoFocus
                      />
                      <Pressable onPress={() => void saveEdit()} style={styles.saveEditBtn}>
                        <Text style={styles.saveEditText}>Save</Text>
                      </Pressable>
                      <Pressable onPress={() => setEditingId(null)}>
                        <Text style={styles.cancelEditText}>Cancel</Text>
                      </Pressable>
                    </View>
                  ) : (
                    <>
                      <Text style={styles.cardTitle}>{folder.displayName}</Text>
                      <Text numberOfLines={1} style={styles.uri}>{folder.treeUri}</Text>
                    </>
                  )}
                </View>
                <Switch value={folder.enabled} onValueChange={(value) => void setEnabled(folder, value)} />
              </View>
              {folder.fileFilter && (
                <Text style={styles.filterLabel}>Filter: {folder.fileFilter}</Text>
              )}
              {filteringId === folder.id ? (
                <View style={styles.editRow}>
                  <TextInput
                    value={editFilter}
                    onChangeText={setEditFilter}
                    placeholder="jpg,png,mp4"
                    placeholderTextColor="#5a718a"
                    style={styles.editInput}
                    autoFocus
                  />
                  <Pressable onPress={() => void saveFilter()} style={styles.saveEditBtn}>
                    <Text style={styles.saveEditText}>Save</Text>
                  </Pressable>
                  <Pressable onPress={() => setFilteringId(null)}>
                    <Text style={styles.cancelEditText}>Cancel</Text>
                  </Pressable>
                </View>
              ) : (
                <View style={styles.actions}>
                  <Pressable onPress={() => startEdit(folder)}>
                    <Text style={styles.actionEdit}>Rename</Text>
                  </Pressable>
                  <Pressable onPress={() => startFilterEdit(folder)}>
                    <Text style={styles.actionFilter}>{folder.fileFilter ? 'Edit filter' : 'Filter'}</Text>
                  </Pressable>
                  <Pressable onPress={() => void handleRescan(folder)}>
                    <Text style={styles.actionRescan}>{scanningId === folder.id ? 'Scanning…' : 'Rescan'}</Text>
                  </Pressable>
                  <Pressable onPress={() => remove(folder)}>
                    <Text style={styles.actionRemove}>Remove</Text>
                  </Pressable>
                </View>
              )}
            </View>
          ))
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#09121f' },
  content: { padding: 20, gap: 16, paddingBottom: 42 },
  title: { color: '#fff', fontSize: 28, fontWeight: '800' },
  copy: { color: '#aabdd0', lineHeight: 20 },
  button: { backgroundColor: '#248de9', alignItems: 'center', borderRadius: 13, padding: 16 },
  muted: { opacity: 0.55 },
  buttonText: { color: '#fff', fontWeight: '800' },
  warning: { color: '#f8c458' },
  previewCard: { backgroundColor: '#152840', borderRadius: 14, padding: 16, borderWidth: 1, borderColor: '#248de955', gap: 8 },
  previewTitle: { color: '#eff7ff', fontWeight: '700', fontSize: 16 },
  previewStats: { color: '#58d68d', fontWeight: '600', fontSize: 14 },
  previewActions: { flexDirection: 'row', gap: 12, marginTop: 4 },
  previewConfirm: { backgroundColor: '#248de9', borderRadius: 8, paddingHorizontal: 14, paddingVertical: 8 },
  previewConfirmText: { color: '#fff', fontWeight: '700', fontSize: 13 },
  previewCancel: { color: '#91a6bf', fontWeight: '600', fontSize: 13, paddingHorizontal: 14, paddingVertical: 8 },
  card: { backgroundColor: '#101e30', padding: 16, borderRadius: 16, gap: 12 },
  disabled: { opacity: 0.5 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  file: { flex: 1 },
  cardTitle: { color: '#eff7ff', fontWeight: '700', fontSize: 16 },
  uri: { color: '#8fa6c0', fontSize: 12, marginTop: 4 },
  actions: { flexDirection: 'row', gap: 16 },
  filterLabel: { color: '#58d68d', fontSize: 12, fontWeight: '600' },
  actionEdit: { color: '#62b2ff', fontWeight: '700', fontSize: 13 },
  actionFilter: { color: '#f8c458', fontWeight: '700', fontSize: 13 },
  actionRescan: { color: '#58d68d', fontWeight: '700', fontSize: 13 },
  actionRemove: { color: '#ff90a5', fontWeight: '700', fontSize: 13 },
  editRow: { flexDirection: 'row', gap: 8, alignItems: 'center' },
  editInput: { backgroundColor: '#0c1929', borderRadius: 8, color: '#fff', paddingHorizontal: 10, paddingVertical: 6, fontSize: 14, flex: 1, borderWidth: 1, borderColor: '#1e3a5f' },
  saveEditBtn: { backgroundColor: '#248de9', borderRadius: 6, paddingHorizontal: 10, paddingVertical: 6 },
  saveEditText: { color: '#fff', fontWeight: '700', fontSize: 12 },
  cancelEditText: { color: '#91a6bf', fontWeight: '600', fontSize: 12 },
});
