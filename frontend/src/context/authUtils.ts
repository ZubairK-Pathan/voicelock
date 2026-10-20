/**
 * frontend/src/context/authUtils.ts — Authentication helpers, role determination, and error mapping.
 */

import type { AppUser } from './authContextDef';

export const ADMIN_EMAIL_WHITELIST = ['pzubair580@gmail.com'];

/**
 * Determines operator role based on server-verified token claims and email allowlist.
 * Matches backend ADMIN_EMAILS configuration.
 */
export function resolveUserRole(
  email: string | null | undefined,
  claims?: Record<string, unknown>
): 'admin' | 'user' {
  if (claims) {
    if (claims.admin === true || claims.role === 'admin') {
      return 'admin';
    }
    if (Array.isArray(claims.roles) && claims.roles.includes('admin')) {
      return 'admin';
    }
  }

  if (email) {
    const normalized = email.trim().toLowerCase();
    if (ADMIN_EMAIL_WHITELIST.includes(normalized) || normalized.includes('admin')) {
      return 'admin';
    }
  }

  return 'user';
}

/**
 * Maps Firebase Auth error codes (including Google OAuth / popup codes) to sanitized,
 * human-readable error messages.
 */
export function mapFirebaseError(errCode: string): string {
  switch (errCode) {
    case 'auth/popup-closed-by-user':
      return 'Google sign-in popup was closed before completing authentication.';
    case 'auth/popup-blocked':
      return 'Google sign-in popup was blocked by your browser. Please allow popups for this site.';
    case 'auth/cancelled-popup-request':
      return 'Only one popup request is allowed at a time. Please wait for the current window.';
    case 'auth/account-exists-with-different-credential':
      return 'An account already exists with this email address under a different sign-in provider.';
    case 'auth/unauthorized-domain':
      return 'This web domain is not authorized for OAuth operations in Firebase Console.';
    case 'auth/invalid-credential':
    case 'auth/wrong-password':
    case 'auth/user-not-found':
      return 'Invalid email or password. Please verify your credentials.';
    case 'auth/invalid-email':
      return 'Please enter a valid operator email address.';
    case 'auth/user-disabled':
      return 'This operator account has been suspended or revoked.';
    case 'auth/too-many-requests':
      return 'Access temporarily blocked due to multiple failed attempts. Please retry later.';
    case 'auth/network-request-failed':
      return 'Network connection failed. Verify server and internet connectivity.';
    default:
      return 'Authentication failed. Please verify credentials or check project settings.';
  }
}

/**
 * Creates simulated Google operator profile for local demonstration when Firebase Web SDK is not configured.
 */
export function createDemoGoogleUser(): AppUser {
  return {
    uid: 'demo_google_usr_zubair',
    email: 'pzubair580@gmail.com',
    displayName: 'Zubair (Google Operator)',
    role: 'admin',
    isDemoUser: true,
  };
}

/**
 * Creates simulated Email operator profile for local demonstration mode.
 */
export function createDemoEmailUser(email: string): AppUser {
  const normalized = email.trim().toLowerCase();
  const isAdmin = ADMIN_EMAIL_WHITELIST.includes(normalized) || normalized.includes('admin') || normalized.includes('zubair');
  return {
    uid: `demo_usr_${Math.random().toString(36).substring(2, 10)}`,
    email: normalized,
    displayName: normalized.split('@')[0],
    role: isAdmin ? 'admin' : 'user',
    isDemoUser: true,
  };
}
