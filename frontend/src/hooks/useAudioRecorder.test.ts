/**
 * frontend/src/hooks/useAudioRecorder.test.ts
 * 
 * Comprehensive automated test suite for useAudioRecorder hook and AudioRecorderController.
 * Verifies all 11 security, privacy, and functional requirements:
 * 1. Permission request occurs only on explicit user action
 * 2. Successful recording returns non-empty Blob with accurate MIME type & extension
 * 3. Start/stop state transitions
 * 4. Permission denied (NotAllowedError / PermissionDeniedError)
 * 5. No microphone (NotFoundError) & unsupported browser APIs
 * 6. Unsupported recording MIME types
 * 7. Empty recording rejection (0-byte payloads fail closed)
 * 8. Recorder errors (onerror handling and cleanup)
 * 9. Maximum duration enforcement (auto-stop on timeout)
 * 10. Track stopping on stop, cancellation, and unmount/destroy
 * 11. Concurrency safety (no stream leaks or duplicate recorders on rapid start calls)
 */

import { test, describe, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  AudioRecorderController,
  getMimeExtension,
  resolveSupportedMimeType,
  CANDIDATE_MIME_TYPES,
  useAudioRecorder,
} from './useAudioRecorder.ts';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// ─── Browser API Mock Fixtures ───────────────────────────────────────────────

class MockMediaStreamTrack {
  public kind: string = 'audio';
  public enabled: boolean = true;
  public readyState: 'live' | 'ended' = 'live';
  public stopped: boolean = false;

  public stop(): void {
    this.readyState = 'ended';
    this.stopped = true;
  }
}

class MockMediaStream {
  public tracks: MockMediaStreamTrack[];

  constructor(tracks: MockMediaStreamTrack[] = [new MockMediaStreamTrack()]) {
    this.tracks = tracks;
  }

  public getTracks(): MockMediaStreamTrack[] {
    return this.tracks;
  }

  public getAudioTracks(): MockMediaStreamTrack[] {
    return this.tracks.filter((t) => t.kind === 'audio');
  }
}

class MockMediaRecorder {
  public static supportedMimes: Set<string> = new Set([
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/ogg',
  ]);

  public static isTypeSupported(mime: string): boolean {
    return MockMediaRecorder.supportedMimes.has(mime);
  }

  public stream: MockMediaStream;
  public mimeType: string;
  public state: 'inactive' | 'recording' | 'paused' = 'inactive';
  public ondataavailable: ((event: { data: Blob }) => void) | null = null;
  public onstop: (() => void) | null = null;
  public onerror: ((err: unknown) => void) | null = null;

  public emitEmptyChunkOnStop: boolean = false;

  constructor(stream: MockMediaStream, options?: { mimeType?: string }) {
    this.stream = stream;
    this.mimeType = options?.mimeType || 'audio/webm;codecs=opus';
  }

  public start(_timeslice?: number): void {
    this.state = 'recording';
  }

  public stop(): void {
    this.state = 'inactive';
    if (this.ondataavailable) {
      if (this.emitEmptyChunkOnStop) {
        this.ondataavailable({ data: new Blob([]) });
      } else {
        const dummyAudio = new Uint8Array([0x1a, 0x45, 0xdf, 0xa3, 0x01, 0x02]);
        this.ondataavailable({ data: new Blob([dummyAudio], { type: this.mimeType }) });
      }
    }
    if (this.onstop) {
      this.onstop();
    }
  }
}

// ─── Test Suite ──────────────────────────────────────────────────────────────

describe('Audio Recording Lifecycle & Security Suite (useAudioRecorder)', () => {
  let originalNavigator: unknown;
  let originalMediaRecorder: unknown;
  let getUserMediaCallCount: number;
  let lastMockStream: MockMediaStream | null;

  beforeEach(() => {
    getUserMediaCallCount = 0;
    lastMockStream = null;

    originalNavigator = globalThis.navigator;
    originalMediaRecorder = globalThis.MediaRecorder;

    // Reset default supported MIME types
    MockMediaRecorder.supportedMimes = new Set([
      'audio/webm;codecs=opus',
      'audio/webm',
      'audio/ogg',
    ]);

    // Install mock navigator.mediaDevices
    const mockGetUserMedia = async () => {
      getUserMediaCallCount++;
      const stream = new MockMediaStream([new MockMediaStreamTrack()]);
      lastMockStream = stream;
      return stream;
    };

    Object.defineProperty(globalThis, 'navigator', {
      value: {
        mediaDevices: {
          getUserMedia: mockGetUserMedia,
        },
      },
      configurable: true,
      writable: true,
    });

    Object.defineProperty(globalThis, 'MediaRecorder', {
      value: MockMediaRecorder,
      configurable: true,
      writable: true,
    });
  });

  afterEach(() => {
    Object.defineProperty(globalThis, 'navigator', {
      value: originalNavigator,
      configurable: true,
      writable: true,
    });
    Object.defineProperty(globalThis, 'MediaRecorder', {
      value: originalMediaRecorder,
      configurable: true,
      writable: true,
    });
  });

  // ─── 1. Explicit User Action Only ──────────────────────────────────────────

  test('permission request occurs only when recording starts, never on instantiation', () => {
    const controller = new AudioRecorderController();
    assert.strictEqual(controller.getState(), 'idle');
    assert.strictEqual(getUserMediaCallCount, 0, 'getUserMedia must NOT be called before start()');
  });

  // ─── 2. Successful Recording & Real MIME Resolution ─────────────────────────

  test('successful recording produces non-empty Blob with accurate MIME type and extension', async () => {
    const controller = new AudioRecorderController({
      baseFilename: 'biometric_sample',
    });

    assert.strictEqual(controller.getState(), 'idle');
    const startPromise = controller.start();
    await startPromise;

    assert.strictEqual(controller.getState(), 'recording');
    assert.strictEqual(getUserMediaCallCount, 1);

    // Stop recording
    controller.stop();

    assert.strictEqual(controller.getState(), 'stopped');
    const recorded = controller.getRecordedAudio();
    assert.ok(recorded !== null, 'recordedAudio must be populated');
    assert.ok(recorded.blob.size > 0, 'audio blob must be non-empty');
    assert.strictEqual(recorded.mimeType, 'audio/webm;codecs=opus');
    assert.strictEqual(recorded.extension, 'webm');
    assert.strictEqual(recorded.filename, 'biometric_sample.webm');
    assert.strictEqual(controller.getError(), null);
  });

  test('resolves OGG MIME type and extension when OGG is supported in browser', async () => {
    // Simulate browser that only supports audio/ogg (e.g. Firefox default)
    MockMediaRecorder.supportedMimes = new Set(['audio/ogg;codecs=opus', 'audio/ogg']);

    const controller = new AudioRecorderController({ baseFilename: 'test_voice' });
    await controller.start();
    controller.stop();

    const recorded = controller.getRecordedAudio();
    assert.ok(recorded !== null);
    assert.strictEqual(recorded.extension, 'ogg');
    assert.strictEqual(recorded.filename, 'test_voice.ogg');
    assert.match(recorded.mimeType, /audio\/ogg/);
  });

  // ─── 3. State Transitions ──────────────────────────────────────────────────

  test('tracks start and stop state transitions accurately', async () => {
    const states: string[] = [];
    const controller = new AudioRecorderController(
      {},
      {
        onStateChange: (s) => states.push(s),
      }
    );

    assert.strictEqual(controller.getState(), 'idle');
    await controller.start();
    assert.strictEqual(controller.getState(), 'recording');

    controller.stop();
    assert.strictEqual(controller.getState(), 'stopped');

    assert.deepStrictEqual(states, ['requesting', 'recording', 'stopped']);
  });

  // ─── 4. Permission Denied ──────────────────────────────────────────────────

  test('handles NotAllowedError permission rejection safely', async () => {
    (navigator.mediaDevices.getUserMedia as unknown) = async () => {
      const err = new Error('Permission denied by user');
      err.name = 'NotAllowedError';
      throw err;
    };

    const controller = new AudioRecorderController();
    await controller.start();

    assert.strictEqual(controller.getState(), 'error');
    assert.match(controller.getError() || '', /Microphone permission denied/i);
    assert.strictEqual(controller.getRecordedAudio(), null);
  });

  // ─── 5. No Microphone & Missing Browser APIs ────────────────────────────────

  test('handles NotFoundError when no microphone hardware is connected', async () => {
    (navigator.mediaDevices.getUserMedia as unknown) = async () => {
      const err = new Error('No audio input devices');
      err.name = 'NotFoundError';
      throw err;
    };

    const controller = new AudioRecorderController();
    await controller.start();

    assert.strictEqual(controller.getState(), 'error');
    assert.match(controller.getError() || '', /No microphone device found/i);
  });

  test('handles unsupported browser without getUserMedia safely', async () => {
    Object.defineProperty(globalThis, 'navigator', {
      value: {},
      configurable: true,
      writable: true,
    });

    const controller = new AudioRecorderController();
    await controller.start();

    assert.strictEqual(controller.getState(), 'error');
    assert.match(controller.getError() || '', /Browser does not support microphone/i);
  });

  test('handles unsupported browser without MediaRecorder safely', async () => {
    Object.defineProperty(globalThis, 'MediaRecorder', {
      value: undefined,
      configurable: true,
      writable: true,
    });

    const controller = new AudioRecorderController();
    await controller.start();

    assert.strictEqual(controller.getState(), 'error');
    assert.match(controller.getError() || '', /Browser does not support MediaRecorder/i);
  });

  // ─── 6. Unsupported Recording MIME Types ───────────────────────────────────

  test('rejects browser when no candidate MIME type is supported', async () => {
    MockMediaRecorder.supportedMimes = new Set(); // Zero supported formats

    const controller = new AudioRecorderController();
    await controller.start();

    assert.strictEqual(controller.getState(), 'error');
    assert.match(controller.getError() || '', /No supported audio recording MIME type/i);
    assert.strictEqual(getUserMediaCallCount, 0, 'Must not request mic stream if formats unsupported');
  });

  // ─── 7. Empty Recording Rejection ──────────────────────────────────────────

  test('rejects 0-byte recording and fails closed', async () => {
    // Custom recorder that emits zero bytes
    class ZeroByteRecorder extends MockMediaRecorder {
      constructor(stream: MockMediaStream, options?: { mimeType?: string }) {
        super(stream, options);
        this.emitEmptyChunkOnStop = true;
      }
    }
    Object.defineProperty(globalThis, 'MediaRecorder', {
      value: ZeroByteRecorder,
      configurable: true,
      writable: true,
    });

    const controller = new AudioRecorderController();
    await controller.start();
    controller.stop();

    assert.strictEqual(controller.getState(), 'error');
    assert.match(controller.getError() || '', /Recording produced no audio data/i);
    assert.strictEqual(controller.getRecordedAudio(), null);
  });

  // ─── 8. Recorder Error Handling ────────────────────────────────────────────

  test('handles MediaRecorder internal errors gracefully', async () => {
    const controller = new AudioRecorderController();
    await controller.start();

    assert.strictEqual(controller.getState(), 'recording');

    // Simulate recorder error
    // @ts-expect-error accessing private recorder for error injection
    const recorder = controller.recorder as MockMediaRecorder;
    assert.ok(recorder);
    recorder.onerror?.(new Event('error'));

    assert.strictEqual(controller.getState(), 'error');
    assert.match(controller.getError() || '', /internal recorder error/i);
    assert.strictEqual(lastMockStream?.tracks[0].stopped, true);
  });

  // ─── 9. Maximum Duration Enforcement ───────────────────────────────────────

  test('enforces maximum duration auto-stop', async () => {
    const controller = new AudioRecorderController({
      maxDurationSeconds: 0.1, // 100ms max duration
    });

    await controller.start();
    assert.strictEqual(controller.getState(), 'recording');

    // Wait 250ms to exceed max duration
    await new Promise((r) => setTimeout(r, 250));

    assert.strictEqual(controller.getState(), 'stopped');
    assert.ok(controller.getRecordedAudio() !== null);
  });

  // ─── 10. Track Stopping on Stop, Cancellation, and Destroy ──────────────────

  test('stops media stream tracks when recording finishes normally', async () => {
    const controller = new AudioRecorderController();
    await controller.start();

    assert.ok(lastMockStream);
    assert.strictEqual(lastMockStream.tracks[0].stopped, false);

    controller.stop();
    assert.strictEqual(lastMockStream.tracks[0].stopped, true);
  });

  test('stops media stream tracks immediately on cancellation', async () => {
    const controller = new AudioRecorderController();
    await controller.start();

    assert.ok(lastMockStream);
    assert.strictEqual(lastMockStream.tracks[0].stopped, false);

    controller.cancel();
    assert.strictEqual(lastMockStream.tracks[0].stopped, true);
    assert.strictEqual(controller.getState(), 'idle');
    assert.strictEqual(controller.getRecordedAudio(), null);
  });

  test('stops media stream tracks immediately on destroy / unmount', async () => {
    const controller = new AudioRecorderController();
    await controller.start();

    assert.ok(lastMockStream);
    assert.strictEqual(lastMockStream.tracks[0].stopped, false);

    controller.destroy();
    assert.strictEqual(lastMockStream.tracks[0].stopped, true);
  });

  // ─── 11. Concurrency & Stream Leak Prevention ──────────────────────────────

  test('repeated start calls while recording do not leak streams or duplicate recorders', async () => {
    const controller = new AudioRecorderController();
    await controller.start();
    assert.strictEqual(getUserMediaCallCount, 1);

    // Call start() second time while recording
    await controller.start();
    assert.strictEqual(getUserMediaCallCount, 1, 'getUserMedia must NOT be called again if already active');

    controller.stop();
    assert.strictEqual(controller.getState(), 'stopped');

    // Now clear and start new recording
    controller.clear();
    assert.strictEqual(controller.getState(), 'idle');

    await controller.start();
    assert.strictEqual(getUserMediaCallCount, 2, 'New session can be started after clearing');
    controller.stop();
  });

  // ─── 12. Format & Helper Functions ─────────────────────────────────────────

  test('getMimeExtension resolves correct extensions for standard audio MIME types', () => {
    assert.strictEqual(getMimeExtension('audio/webm;codecs=opus'), 'webm');
    assert.strictEqual(getMimeExtension('audio/webm'), 'webm');
    assert.strictEqual(getMimeExtension('audio/ogg;codecs=opus'), 'ogg');
    assert.strictEqual(getMimeExtension('audio/ogg'), 'ogg');
    assert.strictEqual(getMimeExtension('audio/mp4'), 'm4a');
    assert.strictEqual(getMimeExtension('audio/aac'), 'aac');
    assert.strictEqual(getMimeExtension('audio/wav'), 'wav');
    assert.strictEqual(getMimeExtension('audio/mpeg'), 'mp3');
  });

  test('resolveSupportedMimeType prioritizes opus webm when available', () => {
    MockMediaRecorder.supportedMimes = new Set(['audio/webm;codecs=opus', 'audio/wav']);
    const resolved = resolveSupportedMimeType();
    assert.strictEqual(resolved?.mimeType, 'audio/webm;codecs=opus');
    assert.strictEqual(resolved?.extension, 'webm');
  });

  // ─── 13. Static Verification of React Hook File ─────────────────────────────

  test('useAudioRecorder source code preserves clean lifecycle and exports', () => {
    assert.strictEqual(typeof useAudioRecorder, 'function');
    assert.ok(Array.isArray(CANDIDATE_MIME_TYPES) && CANDIDATE_MIME_TYPES.length > 0);

    const hookSource = fs.readFileSync(
      path.resolve(__dirname, 'useAudioRecorder.ts'),
      'utf8'
    );

    assert.ok(hookSource.includes('export function useAudioRecorder'));
    assert.ok(hookSource.includes('export class AudioRecorderController'));
    assert.ok(hookSource.includes('controller.destroy()'));
    assert.ok(hookSource.includes('maxDurationSeconds'));
    assert.ok(hookSource.includes('clearRecording'));
    assert.ok(hookSource.includes('cancelRecording'));

    // Verify privacy: no localStorage, IndexedDB, or disk persistence
    assert.ok(!hookSource.includes('localStorage.setItem'));
    assert.ok(!hookSource.includes('sessionStorage.setItem'));
    assert.ok(!hookSource.includes('indexedDB'));
  });
});
