import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';

import { initializeDatabase } from '@/database/client';
import { listRules, saveRule, deleteRule, setRuleEnabled, type RoutingRule, matchRoutingRule } from '@/database/rules';
import { loadForumGroupsWithTopics, type ForumGroup } from '@/services/telegram';
import { isTeleDriveNativeModuleAvailable } from '@/native/TeleDriveModule';

const COMMON_FILES = [
  { name: 'photo.jpg', ext: 'jpg', folder: 'Camera' },
  { name: 'video.mp4', ext: 'mp4', folder: 'WhatsApp Video' },
  { name: 'doc.pdf', ext: 'pdf', folder: 'Documents' },
  { name: 'song.mp3', ext: 'mp3', folder: 'Music' },
  { name: 'archive.zip', ext: 'zip', folder: 'Downloads' },
  { name: 'script.js', ext: 'js', folder: 'Projects' },
];

export default function RoutingScreen() {
  const router = useRouter();
  const [rules, setRules] = useState<RoutingRule[]>([]);
  const [groups, setGroups] = useState<ForumGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [formRuleType, setFormRuleType] = useState<'extension' | 'folder'>('extension');
  const [formMatcher, setFormMatcher] = useState('');
  const [formTopicId, setFormTopicId] = useState('');
  const [formTags, setFormTags] = useState('');
  const [previewInput, setPreviewInput] = useState('');
  const [previewFolder, setPreviewFolder] = useState('');
  const [showPreview, setShowPreview] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      await initializeDatabase();
      const r = await listRules();
      setRules(r);

      if (isTeleDriveNativeModuleAvailable) {
        try {
          const forumGroups = await loadForumGroupsWithTopics();
          setGroups(forumGroups);
        } catch {
          // TDLib not connected — groups stay empty
        }
      }
    } catch (error) {
      Alert.alert('Error', error instanceof Error ? error.message : 'Failed to load routing rules.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleSave = async () => {
    const topicId = parseInt(formTopicId, 10);
    if (!formMatcher.trim() || isNaN(topicId)) {
      Alert.alert('Invalid', 'Matcher and topic ID are required.');
      return;
    }
    try {
      await saveRule(formRuleType, formMatcher.trim(), topicId, formTags.trim());
      setFormMatcher('');
      setFormTopicId('');
      setFormTags('');
      setShowForm(false);
      await load();
    } catch (error) {
      Alert.alert('Error', error instanceof Error ? error.message : 'Failed to save rule.');
    }
  };

  const handleDelete = (rule: RoutingRule) => {
    Alert.alert('Delete rule?', `Remove "${rule.matcher}" → topic ${rule.destinationTopicId}?`, [
      { text: 'No', style: 'cancel' },
      {
        text: 'Delete',
        style: 'destructive',
        onPress: async () => {
          await deleteRule(rule.id);
          await load();
        },
      },
    ]);
  };

  const handleToggle = async (rule: RoutingRule) => {
    await setRuleEnabled(rule.id, !rule.enabled);
    await load();
  };

  const allTopics = useMemo(() =>
    groups.flatMap((g) =>
      g.topics.map((t) => ({ groupTitle: g.title, topicId: t.id, topicName: t.name })),
    ),
    [groups],
  );

  function getDestDisplayName(topicId: number | null): string {
    if (topicId == null) return 'No destination';
    const topic = allTopics.find((t) => t.topicId === topicId);
    return topic ? `${topic.groupTitle} › ${topic.topicName}` : `Topic ${topicId}`;
  }

  function previewRouting(filename: string, folderName: string): number | null {
    return matchRoutingRule(filename, folderName || null, rules);
  }

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color="#49a7ff" />
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} style={styles.backBtn}>
            <Text style={styles.backText}>← Back</Text>
          </Pressable>
          <Text style={styles.title}>Routing Rules</Text>
          <Text style={styles.subtitle}>
            Map file extensions or folder names to Telegram forum topics.
          </Text>
        </View>

        <Pressable
          onPress={() => setShowForm(!showForm)}
          style={styles.addBtn}
        >
          <Text style={styles.addBtnText}>{showForm ? 'Cancel' : '+ New rule'}</Text>
        </Pressable>

        {showForm && (
          <View style={styles.formCard}>
            <Text style={styles.formLabel}>Rule type</Text>
            <View style={styles.typeRow}>
              <Pressable
                onPress={() => setFormRuleType('extension')}
                style={[styles.typeBtn, formRuleType === 'extension' && styles.typeBtnActive]}
              >
                <Text style={[styles.typeBtnText, formRuleType === 'extension' && styles.typeBtnTextActive]}>Extension</Text>
              </Pressable>
              <Pressable
                onPress={() => setFormRuleType('folder')}
                style={[styles.typeBtn, formRuleType === 'folder' && styles.typeBtnActive]}
              >
                <Text style={[styles.typeBtnText, formRuleType === 'folder' && styles.typeBtnTextActive]}>Folder name</Text>
              </Pressable>
            </View>

            <Text style={styles.formLabel}>{formRuleType === 'extension' ? 'Extension (e.g. jpg)' : 'Folder name (e.g. Camera)'}</Text>
            <TextInput
              value={formMatcher}
              onChangeText={setFormMatcher}
              placeholder={formRuleType === 'extension' ? 'jpg' : 'Camera'}
              placeholderTextColor="#475569"
              style={styles.input}
              autoCapitalize="none"
            />

            <Text style={styles.formLabel}>Destination topic ID</Text>
            <TextInput
              value={formTopicId}
              onChangeText={setFormTopicId}
              placeholder="Topic ID (number)"
              placeholderTextColor="#475569"
              style={styles.input}
              keyboardType="numeric"
            />

            {allTopics.length > 0 && (
              <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.topicPills}>
                {allTopics.map((t) => (
                  <Pressable
                    key={`${t.topicId}`}
                    onPress={() => setFormTopicId(String(t.topicId))}
                    style={styles.topicPill}
                  >
                    <Text style={styles.topicPillText}>
                      {t.groupTitle} › {t.topicName} ({t.topicId})
                    </Text>
                  </Pressable>
                ))}
              </ScrollView>
            )}

            <Text style={styles.formLabel}>Tags (optional)</Text>
            <TextInput
              value={formTags}
              onChangeText={setFormTags}
              placeholder="photo, backup"
              placeholderTextColor="#475569"
              style={styles.input}
            />

            <Pressable onPress={handleSave} style={styles.saveBtn}>
              <Text style={styles.saveBtnText}>Save rule</Text>
            </Pressable>
          </View>
        )}

        {/* Routing Preview */}
        <Pressable onPress={() => setShowPreview(!showPreview)} style={styles.previewToggle}>
          <Text style={styles.previewToggleText}>{showPreview ? 'Hide routing preview' : 'Show routing preview'}</Text>
        </Pressable>

        {showPreview && (
          <View style={styles.previewSection}>
            <Text style={styles.formLabel}>Sample filename</Text>
            <TextInput
              value={previewInput}
              onChangeText={setPreviewInput}
              placeholder="e.g. vacation.mp4"
              placeholderTextColor="#475569"
              style={styles.input}
              autoCapitalize="none"
            />
            <Text style={styles.formLabel}>Source folder (optional)</Text>
            <TextInput
              value={previewFolder}
              onChangeText={setPreviewFolder}
              placeholder="e.g. Camera"
              placeholderTextColor="#475569"
              style={styles.input}
              autoCapitalize="none"
            />

            {previewInput.trim() ? (
              <View style={styles.previewResult}>
                <Text style={styles.previewResultLabel}>
                  {previewInput.trim()}
                  {previewFolder.trim() ? ` (from ${previewFolder.trim()})` : ''}
                </Text>
                <Text style={styles.previewResultDest}>
                  → {getDestDisplayName(previewRouting(previewInput.trim(), previewFolder.trim()))}
                </Text>
              </View>
            ) : null}

            <View style={styles.previewDivider} />

            <Text style={styles.formLabel}>Common file types</Text>
            {COMMON_FILES.map((f) => {
              const dest = previewRouting(f.name, f.folder);
              return (
                <View key={f.name} style={styles.previewRow}>
                  <View style={styles.previewFileInfo}>
                    <Text style={styles.previewName}>{f.name}</Text>
                    <Text style={styles.previewFolder}>from &quot;{f.folder}&quot;</Text>
                  </View>
                  <Text style={[styles.previewArrow, dest != null && styles.previewArrowMatch]}>→</Text>
                  <Text style={[styles.previewDest, dest != null && styles.previewDestMatch]}>
                    {getDestDisplayName(dest)}
                  </Text>
                </View>
              );
            })}
          </View>
        )}

        {rules.length === 0 ? (
          <View style={styles.emptyCard}>
            <Text style={styles.emptyTitle}>No routing rules</Text>
            <Text style={styles.emptyCopy}>
              Add a rule to route files by extension or folder name to a Telegram forum topic.
            </Text>
          </View>
        ) : (
          rules.map((rule) => {
            const topic = allTopics.find((t) => t.topicId === rule.destinationTopicId);
            return (
              <View key={rule.id} style={[styles.ruleCard, !rule.enabled && styles.ruleDisabled]}>
                <View style={styles.ruleRow}>
                  <View style={styles.ruleInfo}>
                    <Text style={styles.ruleType}>{rule.ruleType === 'extension' ? '.ext' : 'folder'}</Text>
                    <Text style={styles.ruleMatcher}>{rule.matcher}</Text>
                  </View>
                  <Text style={styles.ruleArrow}>→</Text>
                  <Text style={styles.ruleDest}>
                    {topic ? `${topic.topicName} (${topic.topicId})` : `Topic ${rule.destinationTopicId}`}
                  </Text>
                </View>
                {rule.tags ? <Text style={styles.ruleTags}>Tags: {rule.tags}</Text> : null}
                <View style={styles.ruleActions}>
                  <Pressable onPress={() => void handleToggle(rule)}>
                    <Text style={[styles.actionText, rule.enabled ? styles.actionDisable : styles.actionEnable]}>
                      {rule.enabled ? 'Disable' : 'Enable'}
                    </Text>
                  </Pressable>
                  <Pressable onPress={() => handleDelete(rule)}>
                    <Text style={styles.actionDelete}>Delete</Text>
                  </Pressable>
                </View>
              </View>
            );
          })
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#09121f' },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#09121f' },
  content: { padding: 20, gap: 14, paddingBottom: 40 },
  header: { gap: 6 },
  backBtn: { marginBottom: 4 },
  backText: { color: '#49a7ff', fontSize: 14, fontWeight: '600' },
  title: { color: '#f7fbff', fontSize: 28, fontWeight: '800' },
  subtitle: { color: '#91a6bf', lineHeight: 20 },
  addBtn: { backgroundColor: '#248de9', padding: 14, borderRadius: 12, alignItems: 'center' },
  addBtnText: { color: '#fff', fontWeight: '800', fontSize: 15 },
  formCard: { backgroundColor: '#101e30', borderRadius: 14, padding: 16, gap: 10 },
  formLabel: { color: '#91a6bf', fontSize: 12, fontWeight: '700', textTransform: 'uppercase', letterSpacing: 0.8, marginTop: 4 },
  input: { backgroundColor: '#0c1929', borderRadius: 10, padding: 12, color: '#f1f7ff', fontSize: 15, borderWidth: 1, borderColor: '#1e3a5f' },
  typeRow: { flexDirection: 'row', gap: 8 },
  typeBtn: { flex: 1, padding: 10, borderRadius: 8, backgroundColor: '#0c1929', alignItems: 'center' },
  typeBtnActive: { backgroundColor: '#248de9' },
  typeBtnText: { color: '#91a6bf', fontWeight: '700', fontSize: 13 },
  typeBtnTextActive: { color: '#fff' },
  topicPills: { flexDirection: 'row', gap: 6, marginTop: 4 },
  topicPill: { backgroundColor: '#1e3a5f', borderRadius: 8, paddingHorizontal: 10, paddingVertical: 6 },
  topicPillText: { color: '#91a6bf', fontSize: 11, fontWeight: '600' },
  saveBtn: { backgroundColor: '#58d68d', borderRadius: 10, padding: 12, alignItems: 'center', marginTop: 8 },
  saveBtnText: { color: '#09121f', fontWeight: '800', fontSize: 14 },
  previewToggle: { backgroundColor: '#152840', padding: 12, borderRadius: 10, alignItems: 'center' },
  previewToggleText: { color: '#62b2ff', fontWeight: '700', fontSize: 13 },
  previewSection: { backgroundColor: '#101e30', borderRadius: 14, padding: 16, gap: 10 },
  previewResult: { backgroundColor: '#152840', borderRadius: 10, padding: 12, gap: 4 },
  previewResultLabel: { color: '#f1f7ff', fontWeight: '600', fontSize: 14 },
  previewResultDest: { color: '#58d68d', fontWeight: '700', fontSize: 13 },
  previewDivider: { height: 1, backgroundColor: '#1e3a5f', marginVertical: 4 },
  previewRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: '#0c1929' },
  previewFileInfo: { flex: 1 },
  previewName: { color: '#f1f7ff', fontWeight: '600', fontSize: 13 },
  previewFolder: { color: '#64748b', fontSize: 11, marginTop: 2 },
  previewArrow: { color: '#475569', fontSize: 16, fontWeight: '700' },
  previewArrowMatch: { color: '#58d68d' },
  previewDest: { color: '#91a6bf', fontWeight: '600', fontSize: 12, maxWidth: 140, textAlign: 'right' },
  previewDestMatch: { color: '#58d68d' },
  emptyCard: { backgroundColor: '#101e30', borderRadius: 14, padding: 22, gap: 8 },
  emptyTitle: { color: '#eef7ff', fontWeight: '700', fontSize: 16 },
  emptyCopy: { color: '#9db0c6', lineHeight: 20 },
  ruleCard: { backgroundColor: '#101e30', borderRadius: 12, padding: 14, gap: 6 },
  ruleDisabled: { opacity: 0.5 },
  ruleRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  ruleInfo: { flexDirection: 'row', alignItems: 'center', gap: 6, flex: 1 },
  ruleType: { color: '#49a7ff', fontSize: 11, fontWeight: '800', backgroundColor: '#1e3a5f', borderRadius: 6, paddingHorizontal: 6, paddingVertical: 2, overflow: 'hidden' },
  ruleMatcher: { color: '#f1f7ff', fontWeight: '700', fontSize: 15 },
  ruleArrow: { color: '#475569', fontSize: 16, fontWeight: '700' },
  ruleDest: { color: '#58d68d', fontWeight: '600', fontSize: 13 },
  ruleTags: { color: '#91a6bf', fontSize: 12 },
  ruleActions: { flexDirection: 'row', gap: 16, marginTop: 6 },
  actionText: { fontWeight: '700', fontSize: 12 },
  actionEnable: { color: '#58d68d' },
  actionDisable: { color: '#f8c458' },
  actionDelete: { color: '#ff5c7c', fontWeight: '700', fontSize: 12 },
});
