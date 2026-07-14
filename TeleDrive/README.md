# TeleDrive mobile app

TeleDrive is an Android-only, local-first file backup app. It stores the queue and history in on-device SQLite and uploads original documents to user-selected Telegram forum topics.

## Development

```powershell
cd mobile
npm run typecheck
npx expo start --dev-client
```

TeleDrive requires an Android development client because Telegram, folder access, and background uploads depend on native code. Expo Go cannot provide those features.

Build an installable development APK with `eas build --profile development --platform android`. Create shareable private APKs with `eas build --profile preview --platform android`.

## Secrets

Set `TELEDRIVE_API_ID` and `TELEDRIVE_API_HASH` in the EAS build environment. Do not commit credentials or a populated `.env` file. Link the project with `eas init` before the first cloud build.
