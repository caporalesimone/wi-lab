import { Injectable } from '@angular/core';
import { HttpClient, HttpHeaders, HttpErrorResponse } from '@angular/common/http';
import { Observable, throwError, timer } from 'rxjs';
import { catchError, retry } from 'rxjs/operators';
import { environment } from '../../environments/environment';
import { AuthService } from './auth.service';
import { ApiError, RecoveryCode, retryAfterSeconds, retryWhenBusy } from './recovery-response';
import {
  AntennaDetails,
  StatusResponse,
  NetworkStatus,
  NetworkCreateRequest,
  ReservationRequest,
  ReservationResponse
} from '../models/network.models';

@Injectable({
  providedIn: 'root'
})
export class WilabApiService {
  private apiUrl = environment.apiUrl;

  private getHeaders(): HttpHeaders {
    return new HttpHeaders({
      'Authorization': `Bearer ${this.authService.getToken() ?? ''}`,
      'Content-Type': 'application/json'
    });
  }

  constructor(private http: HttpClient, private authService: AuthService) {}

  // ---- Status ----

  public getStatus(): Observable<StatusResponse> {
    return this.http.get<StatusResponse>(`${this.apiUrl}/status`, {
      headers: this.getHeaders()
    }).pipe(
      catchError(this.handleError)
    );
  }

  // ---- Antennas ----

  /** What a network on the antenna can use: fills the create form's lists. */
  public getAntenna(iface: string): Observable<AntennaDetails> {
    return this.http.get<AntennaDetails>(`${this.apiUrl}/antennas/${encodeURIComponent(iface)}`, {
      headers: this.getHeaders()
    }).pipe(
      catchError(this.handleError)
    );
  }

  // ---- Reservation ----

  public createReservation(req: ReservationRequest): Observable<ReservationResponse> {
    return this.http.post<ReservationResponse>(
      `${this.apiUrl}/reservations`,
      req,
      { headers: this.getHeaders() }
    ).pipe(
      catchError(this.handleError)
    );
  }

  public getReservation(reservationId: string): Observable<ReservationResponse> {
    return this.http.get<ReservationResponse>(
      `${this.apiUrl}/reservations/${reservationId}`,
      { headers: this.getHeaders() }
    ).pipe(
      catchError(this.handleError)
    );
  }

  public deleteReservation(reservationId: string): Observable<object> {
    return this.http.delete(
      `${this.apiUrl}/reservations/${reservationId}`,
      { headers: this.getHeaders() }
    ).pipe(
      catchError(this.handleError)
    );
  }

  public deleteAllReservations(confirmPassword: string): Observable<object> {
    return this.http.delete(
      `${this.apiUrl}/reservations/all`,
      { headers: this.getHeaders().set('X-Confirm-Password', confirmPassword) }
    ).pipe(
      catchError(this.handleError)
    );
  }

  // ---- Network (keyed by reservation_id) ----

  public getNetworkStatus(reservationId: string): Observable<NetworkStatus> {
    return this.http.get<NetworkStatus>(`${this.apiUrl}/reservations/${reservationId}/network`, {
      headers: this.getHeaders()
    }).pipe(
      retryWhenBusy(),
      catchError(this.handleError)
    );
  }

  public startNetwork(
    reservationId: string, config: NetworkCreateRequest, onRetry: (seconds: number) => void
  ): Observable<NetworkStatus> {
    return this.http.post<NetworkStatus>(
      `${this.apiUrl}/reservations/${reservationId}/network`,
      config,
      { headers: this.getHeaders() }
    ).pipe(
      retry({
        count: 2,
        delay: (error: HttpErrorResponse) => {
          const seconds = retryAfterSeconds(error, 409, RecoveryCode.RetryLater);
          if (seconds === null) return throwError(() => error);
          onRetry(seconds);
          return timer(seconds * 1000);
        }
      }),
      catchError(this.handleError)
    );
  }

  public stopNetwork(reservationId: string): Observable<object> {
    return this.http.delete(
      `${this.apiUrl}/reservations/${reservationId}/network`,
      { headers: this.getHeaders() }
    ).pipe(
      // 1012: the stop did not complete (hostapd stuck a few seconds); repeating it finishes it.
      retryWhenBusy(4, [RecoveryCode.DeviceBusy, RecoveryCode.StopIncomplete]),
      catchError(this.handleError)
    );
  }

  // ---- Internet (keyed by reservation_id) ----

  public enableInternet(reservationId: string): Observable<object> {
    return this.http.post(
      `${this.apiUrl}/reservations/${reservationId}/internet/enable`,
      {},
      { headers: this.getHeaders() }
    ).pipe(
      retryWhenBusy(),
      catchError(this.handleError)
    );
  }

  public disableInternet(reservationId: string): Observable<object> {
    return this.http.post(
      `${this.apiUrl}/reservations/${reservationId}/internet/disable`,
      {},
      { headers: this.getHeaders() }
    ).pipe(
      retryWhenBusy(),
      catchError(this.handleError)
    );
  }

  private handleError = (error: HttpErrorResponse) => {
    let errorMessage = 'Unknown error occurred';
    const detail = error.error?.detail;
    
    // Error status 0 typically indicates CORS, network, or connection issues
    if (error.status === 0) {
      if (error.error instanceof ErrorEvent) {
        // Client-side error (network, CORS, etc.)
        errorMessage = `Connection Error: ${error.error.message}\n\nPossible causes:\n- CORS not configured on backend\n- Network connectivity issue\n- Backend server not running\n\nCheck browser console for details.`;
      } else {
        // No response from server
        errorMessage = `Connection Error: Unable to reach server at ${this.apiUrl}\n\nPossible causes:\n- CORS not configured (add your frontend URL to backend config.yaml cors_origins)\n- Backend server not running\n- Network connectivity issue\n- Firewall blocking the request`;
      }
    } else if (error.error instanceof ErrorEvent) {
      // Client-side error
      errorMessage = `Error: ${error.error.message}`;
    } else {
      // Server-side error
      errorMessage = detail?.message ?? detail?.reason ?? error.message;
    }
    
    console.error('API Error:', {
      status: error.status,
      statusText: error.statusText,
      url: error.url,
      error: error.error,
      message: error.message
    });
    
    const err: ApiError = new Error(errorMessage);
    err.originalError = error;
    if (typeof detail?.code === 'number' && typeof detail?.reason === 'string') {
      err.detail = detail;
    }
    return throwError(() => err);
  };
}
