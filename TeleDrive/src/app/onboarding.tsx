import { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Alert, Linking, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';

import {
  type AuthState,
  getAuthState,
  onAuthStateChanged,
  loginWithPhone,
  verifyCode,
  verifyPassword,
} from '@/services/tdlib';
import { isTeleDriveNativeModuleAvailable } from '@/native/TeleDriveModule';

function classifyTdlibError(error: unknown): { title: string; message: string } {
  const msg = error instanceof Error ? error.message : String(error);
  if (msg.includes('PHONE_CODE_INVALID') || msg.includes('CODE_INVALID')) {
    return { title: 'Invalid code', message: 'The code you entered is not correct. Check the message from Telegram and try again.' };
  }
  if (msg.includes('PHONE_NUMBER_INVALID')) {
    return { title: 'Invalid phone number', message: 'The phone number is not registered on Telegram. Include your country code (e.g. +880).' };
  }
  if (msg.includes('FLOOD_WAIT') || msg.includes('FLOOD')) {
    const wait = msg.match(/\d+/)?.[0] ?? 'some';
    return { title: 'Too many attempts', message: `Please wait ${wait} seconds before trying again.` };
  }
  if (msg.includes('PASSWORD_HASH_INVALID')) {
    return { title: 'Wrong password', message: 'The 2FA password you entered is not correct.' };
  }
  if (msg.includes('NETWORK') || msg.includes('Timeout') || msg.includes('timeout') || msg.includes('ETIMEDOUT')) {
    return { title: 'Network error', message: 'Could not reach Telegram servers. Check your internet connection and try again.' };
  }
  return { title: 'Error', message: msg || 'Something went wrong. Try again.' };
}

export default function OnboardingScreen() {
  const router = useRouter();
  const [authState, setAuthState] = useState<AuthState>('closed');
  const [phoneNumber, setPhoneNumber] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const unsubRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    const initialState = getAuthState();
    setAuthState(initialState);
    if (initialState === 'ready') router.replace('/');

    unsubRef.current = onAuthStateChanged((state: AuthState) => {
      setAuthState(state);
      if (state === 'ready') router.replace('/');
    });

    return () => unsubRef.current?.();
  }, [router]);

  const handleRequestCode = async () => {
    if (!phoneNumber.trim()) {
      Alert.alert('Phone number required', 'Enter your Telegram phone number with its country code.');
      return;
    }
    setIsSubmitting(true);
    try {
      await loginWithPhone(phoneNumber);
    } catch (error) {
      const e = classifyTdlibError(error);
      Alert.alert(e.title, e.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleVerifyCode = async () => {
    if (!code.trim()) {
      Alert.alert('Code required', 'Enter the Telegram code you received.');
      return;
    }
    setIsSubmitting(true);
    try {
      await verifyCode(code);
    } catch (error) {
      const e = classifyTdlibError(error);
      Alert.alert(e.title, e.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleVerifyPassword = async () => {
    if (!password) {
      Alert.alert('Password required', 'Enter your Telegram 2FA password.');
      return;
    }
    setIsSubmitting(true);
    try {
      await verifyPassword(password);
    } catch (error) {
      const e = classifyTdlibError(error);
      Alert.alert(e.title, e.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleOpenBatterySettings = async () => {
    try {
      await Linking.openSettings();
    } catch {
      Alert.alert('Battery settings', 'Open Settings > Battery > Battery Optimization and disable it for TeleDrive.');
    }
  };

  if (!isTeleDriveNativeModuleAvailable) {
    return (
      <SafeAreaView style={styles.safeArea} edges={['top']}>
        <ScrollView contentContainerStyle={styles.content}>
          <Text style={styles.eyebrow}>SET UP TELEDRIVE</Text>
          <Text style={styles.title}>Development build required</Text>
          <Text style={styles.copy}>
            Install the Android development build to sign in with Telegram and back up your files.
          </Text>
        </ScrollView>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safeArea} edges={['top']}>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <Text style={styles.eyebrow}>SET UP TELEDRIVE</Text>
        <Text style={styles.title}>Back up your files to your own Telegram topics.</Text>
        <Text style={styles.copy}>
          Nothing is sent to a TeleDrive server. Your session and upload history stay on this device.
        </Text>

        {/* Step 1: Phone Number */}
        <Step number="1" title="Sign in to Telegram" active={authState === 'waitPhoneNumber' || authState === 'unknown'}>
          {authState === 'waitPhoneNumber' || authState === 'unknown' ? (
            <>
              <TextInput
                accessibilityLabel="Telegram phone number"
                autoComplete="tel"
                keyboardType="phone-pad"
                onChangeText={setPhoneNumber}
                placeholder="+880 1…"
                placeholderTextColor="#7e96b0"
                style={styles.input}
                value={phoneNumber}
              />
              <Pressable
                disabled={isSubmitting}
                onPress={() => void handleRequestCode()}
                style={({ pressed }) => [styles.button, (pressed || isSubmitting) && styles.muted]}>
                {isSubmitting ? <ActivityIndicator color="#fff" /> : <Text style={styles.buttonText}>Request Telegram code</Text>}
              </Pressable>
            </>
          ) : authState === 'waitCode' ? (
            <View style={styles.activeBadge}>
              <Text style={styles.badgeText}>Waiting for code verification…</Text>
            </View>
          ) : authState === 'ready' ? (
            <View style={styles.doneBadge}>
              <Text style={styles.doneBadgeText}>Signed in</Text>
            </View>
          ) : null}
        </Step>

        {/* Step 2: Code Verification */}
        {authState === 'waitCode' && (
          <Step number="2" title="Enter the code" active>
            <TextInput
              accessibilityLabel="Telegram verification code"
              keyboardType="number-pad"
              onChangeText={setCode}
              placeholder="12345"
              placeholderTextColor="#7e96b0"
              style={styles.input}
              value={code}
              maxLength={6}
            />
            <Pressable
              disabled={isSubmitting}
              onPress={() => void handleVerifyCode()}
              style={({ pressed }) => [styles.button, (pressed || isSubmitting) && styles.muted]}>
              {isSubmitting ? <ActivityIndicator color="#fff" /> : <Text style={styles.buttonText}>Verify code</Text>}
            </Pressable>
          </Step>
        )}

        {/* Step 3: 2FA Password */}
        {authState === 'waitPassword' && (
          <Step number="2" title="Enter your 2FA password" active>
            <TextInput
              accessibilityLabel="Telegram 2FA password"
              onChangeText={setPassword}
              placeholder="Password"
              placeholderTextColor="#7e96b0"
              secureTextEntry
              style={styles.input}
              value={password}
            />
            <Pressable
              disabled={isSubmitting}
              onPress={() => void handleVerifyPassword()}
              style={({ pressed }) => [styles.button, (pressed || isSubmitting) && styles.muted]}>
              {isSubmitting ? <ActivityIndicator color="#fff" /> : <Text style={styles.buttonText}>Verify password</Text>}
            </Pressable>
          </Step>
        )}

        {/* Step: Choose Folders */}
        <Step number={authState === 'ready' ? '2' : '3'} title="Choose folders" active={authState === 'ready'}>
          <Text style={styles.stepDetail}>
            TeleDrive requests access through Android&apos;s folder picker and keeps that permission after restart.
          </Text>
        </Step>

        {/* Step: Allow Reliable Backup */}
        <Step number={authState === 'ready' ? '3' : '4'} title="Allow reliable backup" active={false}>
          <Text style={styles.stepDetail}>
            Enable battery optimization exemption only if you want continuous backup while the app is not open.
          </Text>
          <Pressable onPress={() => void handleOpenBatterySettings()} style={styles.smallButton}>
            <Text style={styles.smallButtonText}>Open battery settings</Text>
          </Pressable>
        </Step>
      </ScrollView>
    </SafeAreaView>
  );
}

function Step({ number, title, active, children }: { number: string; title: string; active: boolean; children?: React.ReactNode }) {
  return (
    <View style={[styles.step, active && styles.stepActive]}>
      <Text style={[styles.stepNumber, active && styles.stepNumberActive]}>{number}</Text>
      <View style={styles.stepCopy}>
        <Text style={[styles.stepTitle, active && styles.stepTitleActive]}>{title}</Text>
        {children}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: '#09121f' },
  content: { padding: 20, gap: 16, paddingBottom: 44 },
  eyebrow: { color: '#49a7ff', fontWeight: '800', fontSize: 12, letterSpacing: 1.4, marginTop: 10 },
  title: { color: '#f7fbff', fontWeight: '700', fontSize: 28, lineHeight: 35 },
  copy: { color: '#adc0d4', lineHeight: 21, marginBottom: 6 },
  step: { flexDirection: 'row', gap: 12, backgroundColor: '#101e30', padding: 16, borderRadius: 16 },
  stepActive: { backgroundColor: '#152840', borderWidth: 1, borderColor: '#248de933' },
  stepNumber: { color: '#49a7ff', fontSize: 18, fontWeight: '800' },
  stepNumberActive: { color: '#49a7ff' },
  stepCopy: { flex: 1, gap: 8 },
  stepTitle: { color: '#ecf5ff', fontWeight: '700', fontSize: 16 },
  stepTitleActive: { color: '#f7fbff' },
  stepDetail: { color: '#9db0c6', lineHeight: 20 },
  input: { backgroundColor: '#152840', borderRadius: 12, color: '#fff', paddingHorizontal: 16, paddingVertical: 15, fontSize: 16 },
  button: { minHeight: 52, borderRadius: 12, alignItems: 'center', justifyContent: 'center', backgroundColor: '#248de9' },
  smallButton: { minHeight: 42, borderRadius: 10, alignItems: 'center', justifyContent: 'center', backgroundColor: '#1e3a5f', marginTop: 6 },
  smallButtonText: { color: '#62b2ff', fontWeight: '700', fontSize: 14 },
  muted: { opacity: 0.55 },
  buttonText: { color: '#fff', fontWeight: '800' },
  activeBadge: { backgroundColor: '#1f4a37', padding: 10, borderRadius: 8, alignItems: 'center' },
  badgeText: { color: '#d7ffe8', fontWeight: '600', fontSize: 13 },
  doneBadge: { backgroundColor: '#1f4a37', padding: 10, borderRadius: 8, alignItems: 'center' },
  doneBadgeText: { color: '#58d68d', fontWeight: '700', fontSize: 13 },
});
