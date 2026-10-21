import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'
import type { Plugin } from 'vite'

function firebaseBundleValidatorPlugin(): Plugin {
  return {
    name: 'voicelock-firebase-bundle-validator',
    enforce: 'post',
    generateBundle(_options, bundle) {
      if (process.env.ALLOW_UNCONFIGURED_BUILD === '1') return;

      for (const [fileName, chunk] of Object.entries(bundle)) {
        if (chunk.type === 'chunk' && fileName.endsWith('.js')) {
          const code = chunk.code;

          // Detect empty Firebase apiKey
          const emptyApiKeyPattern = /apiKey:\s*["'`]{2}/;
          if (emptyApiKeyPattern.test(code)) {
            this.error(
              `[VoiceLock Build Error] Emitted chunk "${fileName}" contains an empty Firebase apiKey (""). ` +
              `Production builds must have a valid inlined Firebase Web API key.`
            );
          }

          // Detect placeholder Firebase configuration
          const placeholderApiKeyPattern = /apiKey:\s*["'`](?:your_firebase|placeholder)[^"'`]*["'`]/;
          if (placeholderApiKeyPattern.test(code)) {
            this.error(
              `[VoiceLock Build Error] Emitted chunk "${fileName}" contains placeholder Firebase apiKey.`
            );
          }

          // Detect server secret leakage
          if (code.includes('private_key_id') || code.includes('-----BEGIN PRIVATE KEY-----')) {
            this.error(
              `[VoiceLock Build Error] Emitted chunk "${fileName}" contains private keys (CRITICAL SECRET LEAK).`
            );
          }
        }
      }
    },
  };
}

// https://vite.dev/config/
export default defineConfig(({ mode, command }) => {
  const env = loadEnv(mode, process.cwd(), '');

  // During production builds, validate required client environment variables upfront
  if (command === 'build' && mode === 'production' && process.env.ALLOW_UNCONFIGURED_BUILD !== '1') {
    const requiredVars = [
      'VITE_FIREBASE_API_KEY',
      'VITE_FIREBASE_AUTH_DOMAIN',
      'VITE_FIREBASE_PROJECT_ID',
      'VITE_FIREBASE_STORAGE_BUCKET',
      'VITE_FIREBASE_MESSAGING_SENDER_ID',
      'VITE_FIREBASE_APP_ID',
      'VITE_API_BASE_URL',
    ];

    const missing = requiredVars.filter((key) => {
      const val = (process.env[key] || env[key] || '').trim();
      return !val || val.includes('your_firebase') || val.includes('placeholder');
    });

    if (missing.length > 0) {
      throw new Error(
        `[VoiceLock Build Error] Missing or invalid required production environment variable(s): ${missing.join(', ')}.\n` +
        `Production builds must have valid Firebase and API configuration to ensure genuine client-to-backend authentication.\n` +
        `Configure these variables in .env.production.local, .env.local, or the execution environment before building.`
      );
    }
  }

  return {
    plugins: [react(), firebaseBundleValidatorPlugin()],
  };
});

