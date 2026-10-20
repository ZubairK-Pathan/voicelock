import { initializeApp, getApps, getApp } from 'firebase/app';
import type { FirebaseApp } from 'firebase/app';
import { getAuth, GoogleAuthProvider } from 'firebase/auth';
import type { Auth } from 'firebase/auth';

export interface FirebaseWebConfig {
  apiKey: string;
  authDomain: string;
  projectId: string;
  storageBucket: string;
  messagingSenderId: string;
  appId: string;
}

export const firebaseConfig: FirebaseWebConfig = {
  apiKey: (typeof import.meta !== 'undefined' && import.meta.env ? import.meta.env.VITE_FIREBASE_API_KEY : '') || '',
  authDomain: (typeof import.meta !== 'undefined' && import.meta.env ? import.meta.env.VITE_FIREBASE_AUTH_DOMAIN : '') || '',
  projectId: (typeof import.meta !== 'undefined' && import.meta.env ? import.meta.env.VITE_FIREBASE_PROJECT_ID : '') || '',
  storageBucket: (typeof import.meta !== 'undefined' && import.meta.env ? import.meta.env.VITE_FIREBASE_STORAGE_BUCKET : '') || '',
  messagingSenderId: (typeof import.meta !== 'undefined' && import.meta.env ? import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID : '') || '',
  appId: (typeof import.meta !== 'undefined' && import.meta.env ? import.meta.env.VITE_FIREBASE_APP_ID : '') || '',
};

/**
 * Validates whether client-side Firebase environment variables are provided.
 * Rejects empty or placeholder configuration values.
 */
export function isFirebaseConfigured(config: FirebaseWebConfig = firebaseConfig): boolean {
  const { apiKey, projectId } = config;
  if (!apiKey || !projectId) return false;
  if (apiKey.includes('your_firebase') || apiKey.includes('placeholder')) return false;
  return true;
}

let app: FirebaseApp | null = null;
let auth: Auth | null = null;

export const googleAuthProvider = new GoogleAuthProvider();
googleAuthProvider.setCustomParameters({ prompt: 'select_account' });

if (isFirebaseConfigured()) {
  try {
    app = getApps().length > 0 ? getApp() : initializeApp(firebaseConfig);
    auth = getAuth(app);
  } catch (error) {
    console.warn('[VoiceLock Auth] Firebase initialization failed:', error);
  }
} else {
  console.info(
    '[VoiceLock Auth] Firebase Web environment variables not configured. Operating in development demonstration mode.'
  );
}

export { app, auth };

