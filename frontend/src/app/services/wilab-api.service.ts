import { Injectable } from '@angular/core';
import { HttpClient, HttpHeaders, HttpErrorResponse } from '@angular/common/http';
import { Observable, throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { environment } from '../../environments/environment';
import {
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
  private authToken = environment.authToken;

  private getHeaders(): HttpHeaders {
    return new HttpHeaders({
      'Authorization': `Bearer ${this.authToken}`,
      'Content-Type': 'application/json'
    });
  }

  constructor(private http: HttpClient) {}

  // ---- Status ----

  public getStatus(): Observable<StatusResponse> {
    return this.http.get<StatusResponse>(`${this.apiUrl}/status`, {
      headers: this.getHeaders()
    }).pipe(
      catchError(this.handleError)
    );
  }

  // ---- Reservation ----

  public createReservation(req: ReservationRequest): Observable<ReservationResponse> {
    return this.http.post<ReservationResponse>(
      `${this.apiUrl}/device-reservation`,
      req,
      { headers: this.getHeaders() }
    ).pipe(
      catchError(this.handleError)
    );
  }

  public getReservation(reservationId: string): Observable<ReservationResponse> {
    return this.http.get<ReservationResponse>(
      `${this.apiUrl}/device-reservation/${reservationId}`,
      { headers: this.getHeaders() }
    ).pipe(
      catchError(this.handleError)
    );
  }

  public deleteReservation(reservationId: string): Observable<object> {
    return this.http.delete(
      `${this.apiUrl}/device-reservation/${reservationId}`,
      { headers: this.getHeaders() }
    ).pipe(
      catchError(this.handleError)
    );
  }

  public deleteAllReservations(): Observable<object> {
    return this.http.delete(
      `${this.apiUrl}/device-reservation`,
      { headers: this.getHeaders() }
    ).pipe(
      catchError(this.handleError)
    );
  }

  // ---- Network (keyed by reservation_id) ----

  public getNetworkStatus(reservationId: string): Observable<NetworkStatus> {
    return this.http.get<NetworkStatus>(`${this.apiUrl}/interface/${reservationId}/network`, {
      headers: this.getHeaders()
    }).pipe(
      catchError(this.handleError)
    );
  }

  public startNetwork(reservationId: string, config: NetworkCreateRequest): Observable<NetworkStatus> {
    return this.http.post<NetworkStatus>(
      `${this.apiUrl}/interface/${reservationId}/network`,
      config,
      { headers: this.getHeaders() }
    ).pipe(
      catchError(this.handleError)
    );
  }

  public stopNetwork(reservationId: string): Observable<object> {
    return this.http.delete(
      `${this.apiUrl}/interface/${reservationId}/network`,
      { headers: this.getHeaders() }
    ).pipe(
      catchError(this.handleError)
    );
  }

  // ---- Internet (keyed by reservation_id) ----

  public enableInternet(reservationId: string): Observable<object> {
    return this.http.post(
      `${this.apiUrl}/interface/${reservationId}/internet/enable`,
      {},
      { headers: this.getHeaders() }
    ).pipe(
      catchError(this.handleError)
    );
  }

  public disableInternet(reservationId: string): Observable<object> {
    return this.http.post(
      `${this.apiUrl}/interface/${reservationId}/internet/disable`,
      {},
      { headers: this.getHeaders() }
    ).pipe(
      catchError(this.handleError)
    );
  }

  private handleError = (error: HttpErrorResponse) => {
    let errorMessage = 'Unknown error occurred';
    
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
      const detail = error.error?.detail || error.error?.message || error.message;
      if (typeof detail === 'object' && detail !== null) {
        errorMessage = detail.error || detail.message || JSON.stringify(detail);
      } else {
        errorMessage = String(detail);
      }
    }
    
    console.error('API Error:', {
      status: error.status,
      statusText: error.statusText,
      url: error.url,
      error: error.error,
      message: error.message
    });
    
    const err = new Error(errorMessage);
    (err as Error & { originalError: HttpErrorResponse }).originalError = error;
    return throwError(() => err);
  };
}
