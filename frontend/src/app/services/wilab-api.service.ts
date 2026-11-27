import { Injectable } from '@angular/core';
import { HttpClient, HttpHeaders, HttpErrorResponse } from '@angular/common/http';
import { EMPTY, Observable, concat, of, throwError, timer } from 'rxjs';
import { catchError, exhaustMap, first, switchMap, timeout } from 'rxjs/operators';
import { environment } from '../../environments/environment';
import { AuthService } from './auth.service';
import { ApiError, RecoveryCode, isTransient, retryWhenBusy } from './recovery-response';
import {
  AntennaCapabilities,
  AntennaListResponse,
  StatusResponse,
  NetworkStatus,
  NetworkCreateRequest,
  ReservationRequest,
  ReservationResponse
} from '../models/network.models';

/** How often GET /access-point/{reservation_id} is read while a create is starting. */
const CREATE_POLL_MS = 1500;
/**
 * Longest wait for the end of a start (REV-13): a DFS start with the server's
 * retries takes up to about 7 minutes. After it the card falls back to its
 * normal status polling.
 */
const CREATE_POLL_LIMIT_MS = 10 * 60 * 1000;

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

  /** The antennas with their state, how many are free and the reservation limits. */
  public getAntennas(): Observable<AntennaListResponse> {
    return this.http.get<AntennaListResponse>(`${this.apiUrl}/antennas`, {
      headers: this.getHeaders()
    }).pipe(
      catchError(this.handleError)
    );
  }

  /** What a network on the antenna can use: fills the create form's lists. */
  public getCapabilities(iface: string): Observable<AntennaCapabilities> {
    return this.http.get<AntennaCapabilities>(`${this.apiUrl}/antennas/${encodeURIComponent(iface)}/capabilities`, {
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
    return this.http.get<NetworkStatus>(`${this.apiUrl}/access-point/${reservationId}`, {
      headers: this.getHeaders()
    }).pipe(
      retryWhenBusy(),
      catchError(this.handleError)
    );
  }

  /**
   * Asynchronous create: the POST answers 202 with runtime_state "starting", then
   * GET /access-point/{reservation_id} is polled until the start ends (REV-13).
   * Emits the 202 body first (the card shows "starting" at once), then the final
   * network: `active: true` (the AP is up), "start_failed" (see `error`), or
   * `active: false` with runtime_state null (the start was cancelled, e.g. from
   * another tab). A 404 while polling (reservation ended) is an error with
   * detail.reason. A poll without an answer, a 5xx or a 503 / 1006 is skipped:
   * the server is still working. Each poll waits for the previous one
   * (exhaustMap), and polling stops after CREATE_POLL_LIMIT_MS with a timeout
   * error. Radio failures are retried by the server: never repeat the create for them.
   */
  public startNetwork(reservationId: string, config: NetworkCreateRequest): Observable<NetworkStatus> {
    const url = `${this.apiUrl}/access-point/${reservationId}`;
    const poll = timer(CREATE_POLL_MS, CREATE_POLL_MS).pipe(
      exhaustMap(() => this.http.get<NetworkStatus>(url, { headers: this.getHeaders() }).pipe(
        catchError((error: HttpErrorResponse) => isTransient(error) ? EMPTY : throwError(() => error)),
      )),
      first(status => status.runtime_state !== 'starting'),
      timeout({ first: CREATE_POLL_LIMIT_MS }),
    );
    return this.http.post<NetworkStatus>(url, config, { headers: this.getHeaders() }).pipe(
      // The same body on a running network can answer 1006 (REV-11): repeat it.
      retryWhenBusy(),
      switchMap(created => created.runtime_state !== 'starting' ? of(created) : concat(of(created), poll)),
      catchError(this.handleError)
    );
  }

  public stopNetwork(reservationId: string): Observable<object> {
    return this.http.delete(
      `${this.apiUrl}/access-point/${reservationId}`,
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
      `${this.apiUrl}/access-point/${reservationId}/internet/enable`,
      {},
      { headers: this.getHeaders() }
    ).pipe(
      retryWhenBusy(),
      catchError(this.handleError)
    );
  }

  public disableInternet(reservationId: string): Observable<object> {
    return this.http.post(
      `${this.apiUrl}/access-point/${reservationId}/internet/disable`,
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
    
    // Status 0: no answer (the UI and the API share one origin, so not CORS).
    if (error.status === 0) {
      const cause = error.error instanceof ErrorEvent ? `${error.error.message}\n\n` : '';
      errorMessage = `Connection Error: Unable to reach the Wi-Lab server at ${this.apiUrl}\n\n${cause}` +
        `Possible causes:\n- The Wi-Lab service is not running or restarting\n- Network connectivity issue\n- Firewall blocking the request`;
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
