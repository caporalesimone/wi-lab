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

export function retryAfterSeconds(error: HttpErrorResponse, status: number, code: RecoveryCode): number | null {
  if (error.status !== status || error.error?.detail?.code !== code) return null;
  const header = error.headers.get('Retry-After');
  if (header === null || !/^\d+$/.test(header)) return null;
  const seconds = Number(header);
  return seconds > 0 && seconds <= Math.floor(0x7fffffff / 1000) ? seconds : null;
}
