import { HttpErrorResponse } from '@angular/common/http';
import { MonoTypeOperatorFunction, throwError, timer } from 'rxjs';
import { retry } from 'rxjs/operators';
import { ApiErrorDetail } from '../models/network.models';

export enum RecoveryCode {
  /** No longer answered: radio failures are retried by the server inside the create. */
  RetryLater = 1001,
  DeviceRecovering = 1002,
  DeviceUnavailable = 1003,
  NoDeviceAvailable = 1005,
  DeviceBusy = 1006,
  NetworkNotActive = 1007,
  NetworkAlreadyActive = 1008,
  RestorationInProgress = 1009,
  StopIncomplete = 1012
}

/** Readable explanation of domain codes that the raw body does not make obvious. */
const CODE_HINTS: Partial<Record<number, string>> = {
  [RecoveryCode.DeviceBusy]: 'The antenna is busy with another operation. Try again in a few seconds.',
  [RecoveryCode.NetworkNotActive]: 'The network is not running on this antenna. Start WiFi first.',
  [RecoveryCode.NetworkAlreadyActive]: 'A network with different settings is already running or starting on this antenna. Stop it first.',
  [RecoveryCode.RestorationInProgress]: 'The network is being restarted by the watchdog. Wait a few seconds.',
  [RecoveryCode.StopIncomplete]: 'The last stop did not complete. Stop WiFi again, then start it.',
};

/** A sentence for every reason of a 404 on a reservation (REV-13): never the raw JSON. */
const REASON_TEXT: Record<string, string> = {
  reservation_released: 'The reservation was released (from another tab or by Release All).',
  reservation_not_found: 'The reservation is unknown to the server (for example after a server restart).',
  reservation_expired: 'The reservation expired.',
  reservation_invalidated: 'The antenna failed and the reservation was invalidated; reserve a device again.',
};

export function reservationGoneText(error: ApiError | HttpErrorResponse): string | null {
  const response = error instanceof HttpErrorResponse ? error : error.originalError;
  if (response?.status !== 404) return null;
  return REASON_TEXT[response.error?.detail?.reason] ?? null;
}

/** No answer, a proxy or server error, or 503 / 1006: the server may still be working. */
export function isTransient(error: HttpErrorResponse): boolean {
  return error.status === 0 || error.status >= 500;
}

export interface ApiError extends Error {
  originalError?: HttpErrorResponse;
  detail?: ApiErrorDetail;
}

export function apiErrorToast(title: string, error: ApiError | HttpErrorResponse): string {
  const response = error instanceof HttpErrorResponse ? error : error.originalError;
  if (!response?.status) return `${title}: ${error.message}`;

  const hint = CODE_HINTS[response.error?.detail?.code] ?? reservationGoneText(response);
  if (hint) return `${title}\n${hint}`;
  const body: unknown = response.error;
  const text = body == null || body === ''
    ? 'No response body'
    : typeof body === 'string' ? body : JSON.stringify(body, null, 2);
  return `${title}\nHTTP ${response.status}\n${text}`;
}

export function retryAfterSeconds(error: HttpErrorResponse, status: number, code: RecoveryCode): number | null {
  if (error.status !== status || error.error?.detail?.code !== code) return null;
  const header = error.headers.get('Retry-After');
  if (header === null || !/^\d+$/.test(header)) return null;
  const seconds = Number(header);
  return seconds > 0 && seconds <= Math.floor(0x7fffffff / 1000) ? seconds : null;
}

/**
 * Repeat a request answered 503 / 1006 (adapter busy) after its Retry-After,
 * at most `count` times. Every endpoint except the create can return it.
 */
export function retryWhenBusy<T>(count = 3, codes: RecoveryCode[] = [RecoveryCode.DeviceBusy]): MonoTypeOperatorFunction<T> {
  return retry<T>({
    count,
    delay: (error: HttpErrorResponse) => {
      const seconds = codes.map(code => retryAfterSeconds(error, 503, code)).find(s => s !== null) ?? null;
      return seconds === null ? throwError(() => error) : timer(seconds * 1000);
    },
  });
}
