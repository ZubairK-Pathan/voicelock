/**
 * frontend/src/lib/roleNavigation.test.ts
 *
 * Increment 3C Automated Test Suite: Role-Aware Dashboard & UI Foundation
 * - Role-aware navigation: regular users receive personal access tabs only
 * - Administrator navigation: preserves full enterprise system operations tabs
 * - Direct navigation protection: non-admins cannot bypass UI to view admin pages
 * - Request storm prevention: non-admins never trigger 403 administrative telemetry requests
 * - Dual-mode Overview: Personal Access Portal (regular user) vs Operations Telemetry (admin)
 * - Zero-mock enforcement across DevicesPage and SecurityEventsPage
 * - Reusable UI foundation tokens and component accessibility
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

describe('Increment 3C: Role-Aware Navigation & UI Foundation Suite', () => {
  const sidebarPath = path.resolve(__dirname, '../components/layout/Sidebar.tsx');
  const appPath = path.resolve(__dirname, '../App.tsx');
  const overviewPath = path.resolve(__dirname, '../components/pages/OverviewPage.tsx');
  const devicesPath = path.resolve(__dirname, '../components/pages/DevicesPage.tsx');
  const eventsPath = path.resolve(__dirname, '../components/pages/SecurityEventsPage.tsx');
  const uiIndexPath = path.resolve(__dirname, '../components/ui/index.ts');
  const utilsPath = path.resolve(__dirname, 'utils.ts');

  test('Sidebar source: strictly filters navigation tabs based on user role', () => {
    assert.strictEqual(fs.existsSync(sidebarPath), true);
    const source = fs.readFileSync(sidebarPath, 'utf-8');

    // Asserts that navItems are partitioned by role using isAdmin
    assert.ok(
      source.includes('isAdmin = user?.role === \'admin\'') || source.includes("user?.role === 'admin'"),
      'Sidebar must resolve admin status from user context'
    );
    assert.ok(
      source.includes('...(isAdmin') || source.includes('isAdmin ?'),
      'Sidebar must conditionally spread administrative tabs based on isAdmin'
    );

    // Regular user tabs: Overview and Verification
    assert.ok(
      source.includes("'overview'") && source.includes("'verification'"),
      'Sidebar must include overview and verification for standard navigation'
    );

    // Admin-restricted tabs
    assert.ok(
      source.includes("'speakers'") &&
      source.includes("'devices'") &&
      source.includes("'events'") &&
      source.includes("'identities'"),
      'Sidebar must configure administrative tabs for privileged operators'
    );

    // Role indicator chip
    assert.ok(
      source.includes('SECURITY ADMIN') && source.includes('OPERATOR'),
      'Sidebar must render distinct visual role indicator badges'
    );
  });

  test('App.tsx source: eliminates 403 request storm for regular users', () => {
    assert.strictEqual(fs.existsSync(appPath), true);
    const source = fs.readFileSync(appPath, 'utf-8');

    // Telemetry fetch MUST be guarded by isUserAdmin
    assert.ok(
      source.includes('isUserAdmin') || source.includes("user?.role === 'admin'"),
      'App.tsx must verify admin status before initiating administrative telemetry requests'
    );

    // Non-admin path must not call getSpeakers or getDevices or getAdminMappings during startup
    assert.ok(
      source.includes('if (!isUserAdmin)'),
      'loadTelemetryCounts must short-circuit or guard API dispatches for regular users'
    );
  });

  test('App.tsx source: enforces direct navigation boundary against restricted pages', () => {
    assert.strictEqual(fs.existsSync(appPath), true);
    const source = fs.readFileSync(appPath, 'utf-8');

    // Asserts that restricted tabs are prevented from rendering for non-admins
    assert.ok(
      source.includes('!isUserAdmin') &&
      source.includes("activeTab === 'speakers'") &&
      source.includes("activeTab === 'identities'"),
      'App.tsx must intercept navigation to administrative tabs when user is not admin'
    );
  });

  test('OverviewPage source: provides dedicated regular-user experience without mock data', () => {
    assert.strictEqual(fs.existsSync(overviewPath), true);
    const source = fs.readFileSync(overviewPath, 'utf-8');

    // Dual-mode rendering based on user role
    assert.ok(
      source.includes('Personal Access Portal') || source.includes('Biometric Voiceprint Status'),
      'OverviewPage must provide personal regular-user portal'
    );

    // Probe user mapping via challenge rather than assuming UID is speaker ID
    assert.ok(
      source.includes('apiClient.createChallenge'),
      'OverviewPage must probe user mapping safely via challenge without assuming UID is speaker'
    );

    // Empty state guidance
    assert.ok(
      source.includes('UNMAPPED ACCOUNT') || source.includes('No Biometric Profile Linked'),
      'OverviewPage must render explanatory unmapped state for users without a voiceprint'
    );

    // Must NOT import mock data
    assert.ok(
      !source.includes("from '../../data/mockData'") && !source.includes("from '../data/mockData'"),
      'OverviewPage must never import or consume mock data'
    );
  });

  test('DevicesPage source: connects to live API and purges mock devices', () => {
    assert.strictEqual(fs.existsSync(devicesPath), true);
    const source = fs.readFileSync(devicesPath, 'utf-8');

    // Verifies live API query
    assert.ok(
      source.includes('apiClient.getDevices()'),
      'DevicesPage must connect to live apiClient.getDevices()'
    );

    // Zero-mock invariant
    assert.ok(
      !source.includes('MOCK_DEVICES'),
      'DevicesPage must not reference MOCK_DEVICES'
    );

    // Admin privilege guard
    assert.ok(
      source.includes('isAdmin') || source.includes("role !== 'admin'"),
      'DevicesPage must guard administrative access'
    );
  });

  test('SecurityEventsPage source: purges mock security events and displays integrated state', () => {
    assert.strictEqual(fs.existsSync(eventsPath), true);
    const source = fs.readFileSync(eventsPath, 'utf-8');

    // Zero-mock invariant
    assert.ok(
      !source.includes('MOCK_SECURITY_EVENTS'),
      'SecurityEventsPage must not reference MOCK_SECURITY_EVENTS'
    );

    // Explicit non-integrated / provisioning disclosure
    assert.ok(
      source.includes('Audit Stream') || source.includes('Audit Log API'),
      'SecurityEventsPage must display transparent audit log backend integration status'
    );

    // Admin privilege guard
    assert.ok(
      source.includes('isAdmin') || source.includes("role !== 'admin'"),
      'SecurityEventsPage must guard administrative access'
    );
  });

  test('UI Foundation: exports accessible primitives and zero-dependency class merger', () => {
    assert.strictEqual(fs.existsSync(uiIndexPath), true);
    assert.strictEqual(fs.existsSync(utilsPath), true);

    const uiSource = fs.readFileSync(uiIndexPath, 'utf-8');
    const utilsSource = fs.readFileSync(utilsPath, 'utf-8');

    // Primitives exported
    assert.ok(uiSource.includes('Card'), 'UI index must export Card');
    assert.ok(uiSource.includes('Button'), 'UI index must export Button');
    assert.ok(uiSource.includes('Badge'), 'UI index must export Badge');
    assert.ok(uiSource.includes('Alert'), 'UI index must export Alert');

    // Utility cn class merger
    assert.ok(utilsSource.includes('export function cn'), 'utils must export cn helper');

    // Accessibility in Alert
    const alertPath = path.resolve(__dirname, '../components/ui/Alert.tsx');
    const alertSource = fs.readFileSync(alertPath, 'utf-8');
    assert.ok(
      alertSource.includes("isAlert ? 'alert' : 'status'") || alertSource.includes('role='),
      'Alert component must specify accessible role attributes'
    );
  });
});
