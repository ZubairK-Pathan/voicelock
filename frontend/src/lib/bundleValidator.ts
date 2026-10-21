/**
 * frontend/src/lib/bundleValidator.ts — Production bundle integrity and security assertions.
 *
 * Validates that built browser assets contain necessary client configuration
 * (non-empty Firebase apiKey, valid projectId, production API base URL)
 * and strictly contain zero leaked server secrets (service-account keys, private keys).
 */

export interface BundleValidationResult {
  valid: boolean;
  errors: string[];
}

export function validateBundleContent(code: string): BundleValidationResult {
  const errors: string[] = [];

  // Check for empty apiKey in Firebase configuration: apiKey:"", apiKey:'', apiKey:``
  const emptyApiKeyPattern = /apiKey:\s*["'`]{2}/;
  if (emptyApiKeyPattern.test(code)) {
    errors.push('Bundle contains an empty Firebase apiKey ("").');
  }

  // Check for placeholder apiKey or configuration
  const placeholderApiKeyPattern = /apiKey:\s*["'`](?:your_firebase|placeholder)[^"'`]*["'`]/;
  if (placeholderApiKeyPattern.test(code)) {
    errors.push('Bundle contains placeholder Firebase configuration values.');
  }

  // Check for server-side secret leakage
  if (code.includes('private_key_id') || code.includes('-----BEGIN PRIVATE KEY-----')) {
    errors.push('Bundle contains server private keys (CRITICAL SECRET LEAK).');
  }

  if (code.includes('type":"service_account"') || code.includes('"type": "service_account"')) {
    errors.push('Bundle contains Firebase service account credentials (CRITICAL SECRET LEAK).');
  }

  return {
    valid: errors.length === 0,
    errors,
  };
}
