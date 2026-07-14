import { getDatabase } from '@/database/client';

export interface RoutingRule {
  id: number;
  ruleType: 'extension' | 'folder';
  matcher: string;
  destinationTopicId: number;
  tags: string;
  enabled: boolean;
  priority: number;
}

interface RuleRow {
  id: number;
  rule_type: string;
  matcher: string;
  destination_topic_id: number;
  tags: string;
  enabled: number;
  priority: number;
}

const VALID_RULE_TYPES = ['extension', 'folder'] as const;

function mapRule(row: RuleRow): RoutingRule {
  const ruleType = VALID_RULE_TYPES.includes(row.rule_type as 'extension' | 'folder')
    ? (row.rule_type as 'extension' | 'folder')
    : 'extension';
  return {
    id: row.id,
    ruleType,
    matcher: row.matcher,
    destinationTopicId: row.destination_topic_id,
    tags: row.tags,
    enabled: row.enabled === 1,
    priority: row.priority,
  };
}

export async function listRules(): Promise<RoutingRule[]> {
  const database = await getDatabase();
  const rows = await database.getAllAsync<RuleRow>(
    'SELECT * FROM routing_rules ORDER BY priority DESC, rule_type ASC',
  );
  return rows.map(mapRule);
}

export async function saveRule(
  ruleType: 'extension' | 'folder',
  matcher: string,
  destinationTopicId: number,
  tags: string = '',
  priority: number = 0,
): Promise<void> {
  const database = await getDatabase();
  await database.runAsync(
    `INSERT INTO routing_rules (rule_type, matcher, destination_topic_id, tags, enabled, priority)
     VALUES (?, ?, ?, ?, 1, ?)
     ON CONFLICT(rule_type, matcher) DO UPDATE SET
       destination_topic_id = excluded.destination_topic_id,
       tags = excluded.tags,
       priority = excluded.priority,
       enabled = 1`,
    ruleType,
    matcher.toLowerCase(),
    destinationTopicId,
    tags,
    priority,
  );
}

export async function deleteRule(id: number): Promise<void> {
  const database = await getDatabase();
  await database.runAsync('DELETE FROM routing_rules WHERE id = ?', id);
}

export async function setRuleEnabled(id: number, enabled: boolean): Promise<void> {
  const database = await getDatabase();
  await database.runAsync(
    'UPDATE routing_rules SET enabled = ? WHERE id = ?',
    enabled ? 1 : 0,
    id,
  );
}

/**
 * Match a file against routing rules.
 * Priority: extension rule > folder rule > null.
 * Returns the destination topic ID or null if no match.
 */
export function matchRoutingRule(
  filename: string,
  folderName: string | null,
  rules: RoutingRule[],
): number | null {
  const ext = filename.split('.').pop()?.toLowerCase() ?? '';
  const enabledRules = rules.filter((r) => r.enabled);

  // 1. Extension rule
  const extRule = enabledRules.find(
    (r) => r.ruleType === 'extension' && r.matcher === ext,
  );
  if (extRule) return extRule.destinationTopicId;

  // 2. Folder name rule
  if (folderName) {
    const folderRule = enabledRules.find(
      (r) => r.ruleType === 'folder' && r.matcher === folderName.toLowerCase(),
    );
    if (folderRule) return folderRule.destinationTopicId;
  }

  // 3. No match
  return null;
}
