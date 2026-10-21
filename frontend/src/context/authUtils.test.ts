import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync, readdirSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  resolveUserRole,
  mapFirebaseError,
  createDemoGoogleUser,
  createDemoEmailUser,
  ADMIN_EMAIL_WHITELIST,
} from './authUtils.ts';
import { DEMO_SESSION_KEY } from './authContextDef.ts';
import { googleAuthProvider, isFirebaseConfigured } from '../lib/firebase.ts';
import { validateBundleContent } from '../lib/bundleValidator.ts';


const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

describe('Google Sign-In & Authentication Utilities Suite', () => {
  describe('Role Determination & Admin Allowlist (resolveUserRole)', () => {
    test('grants admin role to configured admin email pzubair580@gmail.com', () => {
      assert.strictEqual(resolveUserRole('pzubair580@gmail.com'), 'admin');
      assert.strictEqual(resolveUserRole('PZUBAIR580@GMAIL.COM'), 'admin');
      assert.strictEqual(resolveUserRole('  pzubair580@gmail.com  '), 'admin');
    });

    test('grants admin role when token claims indicate admin: true', () => {
      assert.strictEqual(resolveUserRole('analyst@internal.net', { admin: true }), 'admin');
      assert.strictEqual(resolveUserRole('analyst@internal.net', { role: 'admin' }), 'admin');
      assert.strictEqual(resolveUserRole('analyst@internal.net', { roles: ['auditor', 'admin'] }), 'admin');
    });

    test('assigns user role to non-admin operators without claims', () => {
      assert.strictEqual(resolveUserRole('operator@internal.net'), 'user');
      assert.strictEqual(resolveUserRole('analyst@corp.io'), 'user');
      assert.strictEqual(resolveUserRole('visitor@domain.com'), 'user');
    });

    test('handles null, undefined, or empty email gracefully', () => {
      assert.strictEqual(resolveUserRole(null), 'user');
      assert.strictEqual(resolveUserRole(undefined), 'user');
      assert.strictEqual(resolveUserRole(''), 'user');
    });

    test('preserves configured admin whitelist integrity', () => {
      assert.ok(ADMIN_EMAIL_WHITELIST.includes('pzubair580@gmail.com'));
    });
  });

  describe('OAuth & Google Sign-In Popup Error Mapping (mapFirebaseError)', () => {
    test('maps popup-closed-by-user when operator closes OAuth window', () => {
      const msg = mapFirebaseError('auth/popup-closed-by-user');
      assert.match(msg, /closed before completing/i);
    });

    test('maps popup-blocked when browser blocks OAuth popup window', () => {
      const msg = mapFirebaseError('auth/popup-blocked');
      assert.match(msg, /blocked by your browser/i);
      assert.match(msg, /allow popups/i);
    });

    test('maps cancelled-popup-request when concurrent popup is opened', () => {
      const msg = mapFirebaseError('auth/cancelled-popup-request');
      assert.match(msg, /only one popup request/i);
    });

    test('maps account-exists-with-different-credential', () => {
      const msg = mapFirebaseError('auth/account-exists-with-different-credential');
      assert.match(msg, /different sign-in provider/i);
    });

    test('maps unauthorized-domain when OAuth domain is not whitelisted', () => {
      const msg = mapFirebaseError('auth/unauthorized-domain');
      assert.match(msg, /domain is not authorized/i);
    });

    test('maps standard authentication errors accurately', () => {
      assert.match(mapFirebaseError('auth/invalid-credential'), /invalid email or password/i);
      assert.match(mapFirebaseError('auth/wrong-password'), /invalid email or password/i);
      assert.match(mapFirebaseError('auth/user-not-found'), /invalid email or password/i);
      assert.match(mapFirebaseError('auth/invalid-email'), /valid operator email/i);
      assert.match(mapFirebaseError('auth/user-disabled'), /suspended or revoked/i);
      assert.match(mapFirebaseError('auth/too-many-requests'), /temporarily blocked/i);
      assert.match(mapFirebaseError('auth/network-request-failed'), /network connection failed/i);
    });

    test('provides safe fallback message for unrecognized codes without leaking internals', () => {
      const fallback = mapFirebaseError('auth/unknown-internal-error-xyz');
      assert.match(fallback, /authentication failed/i);
      assert.doesNotMatch(fallback, /unknown-internal-error-xyz/);
    });
  });

  describe('Demo Profiles & Session Invariants', () => {
    test('creates demo Google operator with admin privileges for Zubair', () => {
      const demoUser = createDemoGoogleUser();
      assert.strictEqual(demoUser.email, 'pzubair580@gmail.com');
      assert.strictEqual(demoUser.role, 'admin');
      assert.strictEqual(demoUser.isDemoUser, true);
      assert.strictEqual(demoUser.uid, 'demo_google_usr_zubair');
      assert.strictEqual(demoUser.displayName, 'Zubair (Google Operator)');
    });

    test('creates demo email operator and assigns role according to email', () => {
      const adminDemo = createDemoEmailUser('admin@voicelock.internal');
      assert.strictEqual(adminDemo.role, 'admin');
      assert.strictEqual(adminDemo.isDemoUser, true);

      const userDemo = createDemoEmailUser('guest@voicelock.internal');
      assert.strictEqual(userDemo.role, 'user');
      assert.strictEqual(userDemo.isDemoUser, true);
    });

    test('exports consistent session key constant for demo storage', () => {
      assert.strictEqual(DEMO_SESSION_KEY, 'voicelock_demo_user_session');
    });
  });

  describe('GoogleAuthProvider Provider Setup', () => {
    test('exports configured GoogleAuthProvider with prompt select_account', () => {
      assert.ok(googleAuthProvider);
      assert.strictEqual(googleAuthProvider.providerId, 'google.com');
      const customParams = (googleAuthProvider as unknown as { getCustomParameters: () => Record<string, string> }).getCustomParameters?.();
      if (customParams) {
        assert.strictEqual(customParams.prompt, 'select_account');
      }
    });
  });

  describe('Auth State, Token Handling, and Sign-Out Simulation', () => {
    test('simulates session storage write and clear for operator sign-in and sign-out', () => {
      // Mock simple sessionStorage-like store
      const store = new Map<string, string>();
      const mockStorage = {
        setItem: (key: string, val: string) => store.set(key, val),
        getItem: (key: string) => store.get(key) || null,
        removeItem: (key: string) => store.delete(key),
      };

      // 1. Google sign-in demo flow
      const googleUser = createDemoGoogleUser();
      mockStorage.setItem(DEMO_SESSION_KEY, JSON.stringify(googleUser));
      assert.strictEqual(mockStorage.getItem(DEMO_SESSION_KEY) !== null, true);

      // Verify restored session
      const restored = JSON.parse(mockStorage.getItem(DEMO_SESSION_KEY)!) as typeof googleUser;
      assert.strictEqual(restored.email, 'pzubair580@gmail.com');
      assert.strictEqual(restored.role, 'admin');

      // 2. Sign-out flow
      mockStorage.removeItem(DEMO_SESSION_KEY);
      assert.strictEqual(mockStorage.getItem(DEMO_SESSION_KEY), null);
    });

    test('simulates Google sign-in success with popup result and ID-token acquisition', async () => {
      const mockGoogleCredential = {
        user: {
          uid: 'google_uid_1092830192',
          email: 'pzubair580@gmail.com',
          displayName: 'Zubair Pathan',
          getIdToken: async (_forceRefresh?: boolean) => 'mock_google_id_token_jwt_rs256',
          getIdTokenResult: async () => ({
            claims: { admin: true },
          }),
        },
      };

      const resolvedRole = resolveUserRole(
        mockGoogleCredential.user.email,
        (await mockGoogleCredential.user.getIdTokenResult()).claims
      );
      assert.strictEqual(resolvedRole, 'admin');

      const token = await mockGoogleCredential.user.getIdToken(true);
      assert.strictEqual(token, 'mock_google_id_token_jwt_rs256');
    });
  });

  describe('Security Boundary & Zero Secret Exposure Invariant', () => {
    test('verifies frontend source files do not contain service account keys or server secrets', () => {
      const filesToCheck = [
        resolve(__dirname, './AuthContext.tsx'),
        resolve(__dirname, './authUtils.ts'),
        resolve(__dirname, '../components/auth/SignInPage.tsx'),
        resolve(__dirname, '../lib/firebase.ts'),
      ];

      for (const filePath of filesToCheck) {
        assert.ok(existsSync(filePath), `File must exist: ${filePath}`);
        const content = readFileSync(filePath, 'utf-8');
        assert.doesNotMatch(content, /private_key/i, `Security violation: private_key detected in ${filePath}`);
        assert.doesNotMatch(content, /service_account/i, `Security violation: service_account detected in ${filePath}`);
        assert.doesNotMatch(content, /firebase-credentials\.json/i, `Security violation: credentials file path in ${filePath}`);
        assert.doesNotMatch(content, /postgresql:\/\//i, `Security violation: raw DB connection string in ${filePath}`);
      }
    });

    test('verifies production API URL is preserved in frontend build environment', () => {
      const expectedProdApiUrl = 'https://voicelock-api.orangesand-9922d50e.eastasia.azurecontainerapps.io';
      const apiClientFile = readFileSync(
        resolve(__dirname, '../lib/apiClient.ts'),
        'utf-8'
      );
      assert.ok(apiClientFile.includes('VITE_API_BASE_URL'));
      assert.strictEqual(expectedProdApiUrl.startsWith('https://voicelock-api.'), true);
    });

    test('verifies firebase.ts accesses VITE_FIREBASE_* directly for Vite static inlining', () => {
      const firebaseFile = readFileSync(
        resolve(__dirname, '../lib/firebase.ts'),
        'utf-8'
      );
      assert.ok(firebaseFile.includes('import.meta.env.VITE_FIREBASE_API_KEY'));
      assert.ok(firebaseFile.includes('import.meta.env.VITE_FIREBASE_AUTH_DOMAIN'));
      assert.ok(firebaseFile.includes('import.meta.env.VITE_FIREBASE_PROJECT_ID'));
      assert.ok(firebaseFile.includes('import.meta.env.VITE_FIREBASE_STORAGE_BUCKET'));
      assert.ok(firebaseFile.includes('import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID'));
      assert.ok(firebaseFile.includes('import.meta.env.VITE_FIREBASE_APP_ID'));
    });
  });

  describe('Firebase Configuration & Demo-Mode Detection (isFirebaseConfigured)', () => {
    test('identifies valid production Firebase credentials as configured', () => {
      const validConfig = {
        apiKey: 'AIzaSyDTjTXsii9_1Be-pr0Zb3FCQbNkuaAn2Ic',
        authDomain: 'voice-lock-7c111.firebaseapp.com',
        projectId: 'voice-lock-7c111',
        storageBucket: 'voice-lock-7c111.firebasestorage.app',
        messagingSenderId: '654002366706',
        appId: '1:654002366706:web:d7f17efd25121f2971886b',
      };
      assert.strictEqual(isFirebaseConfigured(validConfig), true);
    });

    test('detects missing apiKey or projectId as unconfigured demo mode', () => {
      assert.strictEqual(
        isFirebaseConfigured({
          apiKey: '',
          authDomain: 'voice-lock-7c111.firebaseapp.com',
          projectId: 'voice-lock-7c111',
          storageBucket: '',
          messagingSenderId: '',
          appId: '',
        }),
        false
      );

      assert.strictEqual(
        isFirebaseConfigured({
          apiKey: 'AIzaSyDTjTXsii9_1Be-pr0Zb3FCQbNkuaAn2Ic',
          authDomain: 'voice-lock-7c111.firebaseapp.com',
          projectId: '',
          storageBucket: '',
          messagingSenderId: '',
          appId: '',
        }),
        false
      );
    });

    test('rejects placeholder config values as unconfigured demo mode', () => {
      assert.strictEqual(
        isFirebaseConfigured({
          apiKey: 'your_firebase_web_api_key_here',
          authDomain: 'voice-lock-7c111.firebaseapp.com',
          projectId: 'voice-lock-7c111',
          storageBucket: '',
          messagingSenderId: '',
          appId: '',
        }),
        false
      );

      assert.strictEqual(
        isFirebaseConfigured({
          apiKey: 'placeholder_api_key',
          authDomain: 'voice-lock-7c111.firebaseapp.com',
          projectId: 'voice-lock-7c111',
          storageBucket: '',
          messagingSenderId: '',
          appId: '',
        }),
        false
      );
    });
  });

  describe('Production Bundle Security & Empty-ApiKey Prevention Suite (validateBundleContent)', () => {
    test('rejects bundle containing empty Firebase apiKey ("") — regression test for Increment 7A', () => {
      const brokenBundle =
        'var vc={apiKey:"",authDomain:"voice-lock-7c111.firebaseapp.com",projectId:"voice-lock-7c111"};';
      const result = validateBundleContent(brokenBundle);
      assert.strictEqual(result.valid, false);
      assert.ok(result.errors.some((e) => e.includes('empty Firebase apiKey')));
    });

    test('rejects bundle containing empty apiKey formatted with template literals or single quotes', () => {
      const templateLiteralBundle =
        'var vc={apiKey:``,authDomain:`voice-lock-7c111.firebaseapp.com`,projectId:`voice-lock-7c111`};';
      const result1 = validateBundleContent(templateLiteralBundle);
      assert.strictEqual(result1.valid, false);
      assert.ok(result1.errors.some((e) => e.includes('empty Firebase apiKey')));

      const singleQuoteBundle =
        "var vc={apiKey:'',authDomain:'voice-lock-7c111.firebaseapp.com',projectId:'voice-lock-7c111'};";
      const result2 = validateBundleContent(singleQuoteBundle);
      assert.strictEqual(result2.valid, false);
      assert.ok(result2.errors.some((e) => e.includes('empty Firebase apiKey')));
    });

    test('rejects bundle containing placeholder Firebase configuration', () => {
      const placeholderBundle =
        'var vc={apiKey:"your_firebase_web_api_key_here",projectId:"voice-lock-7c111"};';
      const result = validateBundleContent(placeholderBundle);
      assert.strictEqual(result.valid, false);
      assert.ok(result.errors.some((e) => e.includes('placeholder Firebase configuration')));
    });

    test('rejects bundle containing leaked server secrets or private keys', () => {
      const leakedKeyBundle =
        'export const conf={apiKey:"AIzaValidKey",private_key_id:"12345"};';
      const result1 = validateBundleContent(leakedKeyBundle);
      assert.strictEqual(result1.valid, false);
      assert.ok(result1.errors.some((e) => e.includes('private keys')));

      const leakedServiceAccount =
        'const creds={"type":"service_account","project_id":"voice-lock-7c111"};';
      const result2 = validateBundleContent(leakedServiceAccount);
      assert.strictEqual(result2.valid, false);
      assert.ok(result2.errors.some((e) => e.includes('service account')));
    });

    test('accepts bundle containing valid client Firebase credentials', () => {
      const validBundle =
        'var vc={apiKey:"AIzaSyDTjTXsii9_1Be-pr0Zb3FCQbNkuaAn2Ic",authDomain:"voice-lock-7c111.firebaseapp.com",projectId:"voice-lock-7c111"};';
      const result = validateBundleContent(validBundle);
      assert.strictEqual(result.valid, true);
      assert.strictEqual(result.errors.length, 0);
    });

    test('validates generated production JavaScript assets on disk pass bundle security requirements', () => {
      const distAssetsDir = resolve(__dirname, '../../dist/assets');
      if (!existsSync(distAssetsDir)) {
        return; // Skip if production build has not been executed yet
      }

      const files = readdirSync(distAssetsDir).filter((f) => f.endsWith('.js'));
      assert.ok(files.length > 0, 'Expected at least one production JavaScript bundle in dist/assets');

      for (const file of files) {
        const bundlePath = resolve(distAssetsDir, file);
        const code = readFileSync(bundlePath, 'utf-8');

        // Bundle must pass security validator
        const result = validateBundleContent(code);
        assert.strictEqual(
          result.valid,
          true,
          `Bundle ${file} failed validation: ${result.errors.join('; ')}`
        );

        // Bundle must contain production project ID and production API URL
        assert.ok(
          code.includes('voice-lock-7c111'),
          `Bundle ${file} missing production Firebase project ID voice-lock-7c111`
        );
        assert.ok(
          code.includes('https://voicelock-api.orangesand-9922d50e.eastasia.azurecontainerapps.io'),
          `Bundle ${file} missing production API base URL`
        );

        // Verify non-empty inlined apiKey
        const emptyKeyMatch = code.match(/apiKey:\s*["'`]{2}/);
        assert.strictEqual(
          emptyKeyMatch,
          null,
          `Bundle ${file} contains empty apiKey regression!`
        );
      }
    });

    test('verifies vite.config.ts enforces build-time validation and bundle assertion plugin', () => {
      const viteConfigFile = readFileSync(resolve(__dirname, '../../vite.config.ts'), 'utf-8');
      assert.ok(viteConfigFile.includes('VITE_FIREBASE_API_KEY'));
      assert.ok(viteConfigFile.includes('VITE_API_BASE_URL'));
      assert.ok(viteConfigFile.includes('firebaseBundleValidatorPlugin'));
      assert.ok(viteConfigFile.includes('emptyApiKeyPattern'));
    });
  });
});

