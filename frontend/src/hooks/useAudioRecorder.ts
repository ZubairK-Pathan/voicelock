/**
 * frontend/src/hooks/useAudioRecorder.ts — Reusable Audio Recording Hook for VoiceLock Enterprise.
 * 
 * Securely captures genuine browser microphone audio via Web Audio / MediaRecorder.
 * Enforces explicit user activation, runtime MIME negotiation, track cleanup,
 * duration limits, error translation, and unmount hygiene.
 * 
 * Never persists audio to disk or localStorage. Never logs audio bytes or biometric embeddings.
 */

import { useState, useCallback, useEffect } from 'react';

export type AudioRecorderState =
  | 'idle'
  | 'requesting'
  | 'recording'
  | 'stopped'
  | 'error';

export interface RecordedAudio {
  blob: Blob;
  mimeType: string;
  extension: string;
  filename: string;
  durationSeconds: number;
  sizeBytes: number;
}

export interface MimeTypeMapping {
  mimeType: string;
  extension: string;
}

export const CANDIDATE_MIME_TYPES: readonly MimeTypeMapping[] = [
  { mimeType: 'audio/webm;codecs=opus', extension: 'webm' },
  { mimeType: 'audio/webm', extension: 'webm' },
  { mimeType: 'audio/ogg;codecs=opus', extension: 'ogg' },
  { mimeType: 'audio/ogg', extension: 'ogg' },
  { mimeType: 'audio/mp4', extension: 'm4a' },
  { mimeType: 'audio/aac', extension: 'aac' },
  { mimeType: 'audio/wav', extension: 'wav' },
] as const;

export function getMimeExtension(mimeType: string): string {
  const normalized = mimeType.toLowerCase();
  if (normalized.includes('webm')) return 'webm';
  if (normalized.includes('ogg')) return 'ogg';
  if (normalized.includes('mp4') || normalized.includes('m4a')) return 'm4a';
  if (normalized.includes('aac')) return 'aac';
  if (normalized.includes('wav')) return 'wav';
  if (normalized.includes('mpeg') || normalized.includes('mp3')) return 'mp3';
  return 'bin';
}

export function resolveSupportedMimeType(): MimeTypeMapping | null {
  if (typeof MediaRecorder === 'undefined') {
    return null;
  }
  if (typeof MediaRecorder.isTypeSupported !== 'function') {
    return { mimeType: '', extension: 'webm' };
  }
  for (const candidate of CANDIDATE_MIME_TYPES) {
    try {
      if (MediaRecorder.isTypeSupported(candidate.mimeType)) {
        return candidate;
      }
    } catch {
      // Continue probing other candidate formats
    }
  }
  return null;
}

export interface UseAudioRecorderOptions {
  /** Maximum recording duration in seconds before auto-stop. Defaults to 10 seconds. */
  maxDurationSeconds?: number;
  /** Custom base filename (without extension). Defaults to 'recording'. */
  baseFilename?: string;
  /** Audio constraints passed to getUserMedia. Defaults to mono 16kHz audio. */
  audioConstraints?: MediaTrackConstraints;
}

export interface UseAudioRecorderResult {
  state: AudioRecorderState;
  isRecording: boolean;
  duration: number; // in seconds (elapsed)
  error: string | null;
  recordedAudio: RecordedAudio | null;
  startRecording: () => Promise<void>;
  stopRecording: () => void;
  cancelRecording: () => void;
  clearRecording: () => void;
}

export interface AudioRecorderCallbacks {
  onStateChange?: (state: AudioRecorderState) => void;
  onDurationChange?: (duration: number) => void;
  onError?: (error: string) => void;
  onComplete?: (recorded: RecordedAudio) => void;
}

export class AudioRecorderController {
  private state: AudioRecorderState = 'idle';
  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private startTime: number = 0;
  private durationSeconds: number = 0;
  private timerId: ReturnType<typeof setInterval> | null = null;
  private maxDurationTimerId: ReturnType<typeof setTimeout> | null = null;
  private cancelled: boolean = false;
  private error: string | null = null;
  private recordedAudio: RecordedAudio | null = null;

  private maxDurationSeconds: number;
  private baseFilename: string;
  private audioConstraints?: MediaTrackConstraints;
  private callbacks: AudioRecorderCallbacks;

  constructor(options: UseAudioRecorderOptions = {}, callbacks: AudioRecorderCallbacks = {}) {
    this.maxDurationSeconds = options.maxDurationSeconds ?? 10;
    this.baseFilename = options.baseFilename ?? 'recording';
    this.audioConstraints = options.audioConstraints;
    this.callbacks = callbacks;
  }

  public getState(): AudioRecorderState {
    return this.state;
  }

  public getDuration(): number {
    return this.durationSeconds;
  }

  public getError(): string | null {
    return this.error;
  }

  public getRecordedAudio(): RecordedAudio | null {
    return this.recordedAudio;
  }

  public async start(): Promise<void> {
    // Prevent duplicate starts or overlapping sessions
    if (this.state === 'requesting' || this.state === 'recording') {
      return;
    }

    this.cleanupActiveSession();
    this.cancelled = false;
    this.error = null;
    this.recordedAudio = null;
    this.chunks = [];
    this.durationSeconds = 0;

    this.setState('requesting');

    // 1. Verify browser audio capture support
    if (
      typeof navigator === 'undefined' ||
      !navigator.mediaDevices ||
      typeof navigator.mediaDevices.getUserMedia !== 'function'
    ) {
      this.fail('Browser does not support microphone audio capture.');
      return;
    }

    if (typeof MediaRecorder === 'undefined') {
      this.fail('Browser does not support MediaRecorder audio recording.');
      return;
    }

    // 2. Resolve supported MIME type
    const mimeMapping = resolveSupportedMimeType();
    if (mimeMapping === null) {
      this.fail('No supported audio recording MIME type found in this browser.');
      return;
    }

    // 3. Request user microphone stream
    let stream: MediaStream;
    try {
      const constraints: MediaStreamConstraints = {
        audio: this.audioConstraints ?? {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
        video: false,
      };
      stream = await navigator.mediaDevices.getUserMedia(constraints);
    } catch (err: unknown) {
      const errName = err instanceof Error ? err.name : '';
      if (errName === 'NotAllowedError' || errName === 'PermissionDeniedError') {
        this.fail('Microphone permission denied. Please allow microphone access in your browser settings.');
      } else if (errName === 'NotFoundError' || errName === 'DevicesNotFoundError') {
        this.fail('No microphone device found. Please connect a microphone and try again.');
      } else if (errName === 'NotReadableError' || errName === 'TrackStartError') {
        this.fail('Microphone is currently in use or unavailable. Please check your system settings.');
      } else {
        const msg = err instanceof Error ? err.message : 'Failed to access microphone.';
        this.fail(`Failed to access microphone: ${msg}`);
      }
      return;
    }

    // If cancelled while awaiting user permission prompt
    if (this.cancelled) {
      this.stopStreamTracks(stream);
      this.setState('idle');
      return;
    }

    this.stream = stream;

    // 4. Instantiate and configure MediaRecorder
    let recorder: MediaRecorder;
    try {
      const recorderOptions: MediaRecorderOptions = {};
      if (mimeMapping.mimeType) {
        recorderOptions.mimeType = mimeMapping.mimeType;
      }
      recorder = new MediaRecorder(stream, recorderOptions);
    } catch (err: unknown) {
      this.stopStreamTracks(stream);
      const msg = err instanceof Error ? err.message : 'Unknown recorder error';
      this.fail(`Failed to initialize audio recorder: ${msg}`);
      return;
    }

    this.recorder = recorder;

    recorder.ondataavailable = (event: BlobEvent) => {
      if (event.data && event.data.size > 0) {
        this.chunks.push(event.data);
      }
    };

    recorder.onerror = () => {
      this.fail('Audio recording failed due to an internal recorder error.');
    };

    recorder.onstop = () => {
      this.handleRecorderStop();
    };

    // 5. Start recording and duration timer
    try {
      recorder.start(250);
      this.startTime = Date.now();
      this.setState('recording');
      this.startDurationTimer();
    } catch (err: unknown) {
      this.stopStreamTracks(stream);
      const msg = err instanceof Error ? err.message : 'Failed to start recording';
      this.fail(`Failed to start recording: ${msg}`);
    }
  }

  public stop(): void {
    if (this.state !== 'recording' && this.state !== 'requesting') {
      return;
    }

    this.stopDurationTimer();

    if (this.recorder && this.recorder.state === 'recording') {
      try {
        this.recorder.stop();
      } catch {
        this.cleanupActiveSession();
        this.fail('Failed to stop recording cleanly.');
      }
    } else {
      this.cleanupActiveSession();
      this.setState('idle');
    }
  }

  public cancel(): void {
    this.cancelled = true;
    this.stopDurationTimer();

    if (this.recorder && this.recorder.state === 'recording') {
      this.recorder.ondataavailable = null;
      this.recorder.onstop = null;
      this.recorder.onerror = null;
      try {
        this.recorder.stop();
      } catch {
        // ignore
      }
    }

    this.cleanupActiveSession();
    this.chunks = [];
    this.durationSeconds = 0;
    this.callbacks.onDurationChange?.(0);
    this.setState('idle');
  }

  public clear(): void {
    this.cancel();
    this.recordedAudio = null;
    this.error = null;
    this.setState('idle');
  }

  public destroy(): void {
    this.cancel();
  }

  private handleRecorderStop(): void {
    this.stopStreamTracks(this.stream);
    this.stream = null;
    const activeRecorder = this.recorder;
    this.recorder = null;

    if (this.cancelled) {
      this.setState('idle');
      return;
    }

    const totalBytes = this.chunks.reduce((acc, chunk) => acc + chunk.size, 0);
    if (this.chunks.length === 0 || totalBytes === 0) {
      this.fail('Recording produced no audio data. Please ensure your microphone is working and speak clearly.');
      return;
    }

    // Determine actual container type and extension
    const mimeMapping = resolveSupportedMimeType();
    const actualMimeType =
      (activeRecorder && activeRecorder.mimeType) ||
      mimeMapping?.mimeType ||
      'audio/webm';
    const extension = getMimeExtension(actualMimeType);
    const filename = `${this.baseFilename}.${extension}`;
    const blob = new Blob(this.chunks, { type: actualMimeType });

    const finalDuration = Math.max(1, Math.round(this.durationSeconds));
    const result: RecordedAudio = {
      blob,
      mimeType: actualMimeType,
      extension,
      filename,
      durationSeconds: finalDuration,
      sizeBytes: blob.size,
    };

    this.recordedAudio = result;
    this.setState('stopped');
    this.callbacks.onComplete?.(result);
  }

  private startDurationTimer(): void {
    this.stopDurationTimer();

    this.timerId = setInterval(() => {
      const elapsedSeconds = (Date.now() - this.startTime) / 1000;
      this.durationSeconds = elapsedSeconds;
      this.callbacks.onDurationChange?.(elapsedSeconds);

      if (elapsedSeconds >= this.maxDurationSeconds) {
        this.stop();
      }
    }, 100);

    this.maxDurationTimerId = setTimeout(() => {
      if (this.state === 'recording') {
        this.stop();
      }
    }, this.maxDurationSeconds * 1000);
  }

  private stopDurationTimer(): void {
    if (this.timerId !== null) {
      clearInterval(this.timerId);
      this.timerId = null;
    }
    if (this.maxDurationTimerId !== null) {
      clearTimeout(this.maxDurationTimerId);
      this.maxDurationTimerId = null;
    }
  }

  private cleanupActiveSession(): void {
    this.stopDurationTimer();
    this.stopStreamTracks(this.stream);
    this.stream = null;
    this.recorder = null;
  }

  private stopStreamTracks(stream: MediaStream | null): void {
    if (!stream) return;
    try {
      const tracks = stream.getTracks();
      for (const track of tracks) {
        try {
          track.stop();
        } catch {
          // ignore
        }
      }
    } catch {
      // ignore
    }
  }

  private fail(errorMessage: string): void {
    this.cleanupActiveSession();
    this.chunks = [];
    this.error = errorMessage;
    this.recordedAudio = null;
    this.setState('error');
    this.callbacks.onError?.(errorMessage);
  }

  private setState(newState: AudioRecorderState): void {
    this.state = newState;
    this.callbacks.onStateChange?.(newState);
  }
}

export function useAudioRecorder(options: UseAudioRecorderOptions = {}): UseAudioRecorderResult {
  const [state, setState] = useState<AudioRecorderState>('idle');
  const [duration, setDuration] = useState<number>(0);
  const [error, setError] = useState<string | null>(null);
  const [recordedAudio, setRecordedAudio] = useState<RecordedAudio | null>(null);

  const [controller] = useState(
    () =>
      new AudioRecorderController(options, {
        onStateChange: setState,
        onDurationChange: (d) => setDuration(Math.floor(d)),
        onError: (err) => setError(err),
        onComplete: (audio) => setRecordedAudio(audio),
      })
  );

  const startRecording = useCallback(async () => {
    setError(null);
    await controller.start();
  }, [controller]);

  const stopRecording = useCallback(() => {
    controller.stop();
  }, [controller]);

  const cancelRecording = useCallback(() => {
    controller.cancel();
    setDuration(0);
    setError(null);
    setRecordedAudio(null);
  }, [controller]);

  const clearRecording = useCallback(() => {
    controller.clear();
    setDuration(0);
    setError(null);
    setRecordedAudio(null);
  }, [controller]);

  useEffect(() => {
    return () => {
      controller.destroy();
    };
  }, [controller]);

  return {
    state,
    isRecording: state === 'recording',
    duration,
    error,
    recordedAudio,
    startRecording,
    stopRecording,
    cancelRecording,
    clearRecording,
  };
}
