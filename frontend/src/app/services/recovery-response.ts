import { HttpErrorResponse } from '@angular/common/http';
import { ApiErrorDetail } from '../models/network.models';

export enum RecoveryCode {
  RetryLater = 1001,
  DeviceRecovering = 1002,
  DeviceUnavailable = 1003,
  NoDeviceAvailable = 1005
}

export interface ApiError extends Error {
  originalError?: HttpErrorResponse;
  detail?: ApiErrorDetail;
}

export function apiErrorToast(title: string, error: ApiError | HttpErrorResponse): string {
  const response = error instanceof HttpErrorResponse ? error : error.originalError;
  if (!response?.status) return `${title}: ${error.message}`;

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
