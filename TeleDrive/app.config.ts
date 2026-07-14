import { ExpoConfig, ConfigContext } from 'expo/config';

const API_ID = process.env.TELEDRIVE_API_ID || '';
const API_HASH = process.env.TELEDRIVE_API_HASH || '';

export default ({ config }: ConfigContext): ExpoConfig => ({
  ...config,
  name: config.name ?? 'TeleDrive',
  slug: config.slug ?? 'teledrive',
  extra: {
    ...config.extra,
    teledriveApiId: API_ID,
    teledriveApiHash: API_HASH,
  },
});
