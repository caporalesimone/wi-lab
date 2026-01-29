import { Injectable } from '@angular/core';
import { HttpClient, HttpHeaders, HttpErrorResponse } from '@angular/common/http';
import { Observable, throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { environment } from '../../environments/environment';
import {
  InterfaceInfo,
  InterfacesResponse,
  NetworkStatus,
  NetworkCreateRequest,
  ClientsResponse
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

  public getInterfaces(): Observable<InterfacesResponse> {
    return this.http.get<InterfacesResponse>(`${this.apiUrl}/interfaces`, {
      headers: this.getHeaders()
    }).pipe(
      catchError(this.handleError)
    );
  }

  public getNetworkStatus(netId: string): Observable<NetworkStatus> {
    return this.http.get<NetworkStatus>(`${this.apiUrl}/interface/${netId}/network`, {
      headers: this.getHeaders()
    }).pipe(
      catchError(this.handleError)
    );
  }

  public startNetwork(netId: string, config: NetworkCreateRequest): Observable<NetworkStatus> {
    return this.http.post<NetworkStatus>(
      `${this.apiUrl}/interface/${netId}/network`,
      config,
      { headers: this.getHeaders() }
    ).pipe(
      catchError(this.handleError)
    );
  }

  public stopNetwork(netId: string): Observable<{ net_id: string }> {
    return this.http.delete<{ net_id: string }>(
      `${this.apiUrl}/interface/${netId}/network`,
      { headers: this.getHeaders() }
    ).pipe(
      catchError(this.handleError)
    );
  }

  public enableInternet(netId: string): Observable<{ net_id: string; internet_enabled: boolean }> {
    return this.http.post<{ net_id: string; internet_enabled: boolean }>(
      `${this.apiUrl}/interface/${netId}/internet/enable`,
      {},
      { headers: this.getHeaders() }
    ).pipe(
      catchError(this.handleError)
    );
  }

  public disableInternet(netId: string): Observable<{ net_id: string; internet_enabled: boolean }> {
    return this.http.post<{ net_id: string; internet_enabled: boolean }>(
      `${this.apiUrl}/interface/${netId}/internet/disable`,
      {},
      { headers: this.getHeaders() }
    ).pipe(
      catchError(this.handleError)
    );
  }

  public getClients(netId: string): Observable<ClientsResponse> {
    return this.http.get<ClientsResponse>(
      `${this.apiUrl}/interface/${netId}/clients`,
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
      errorMessage = `Error Code: ${error.status}\nMessage: ${detail}`;
    }
    
    console.error('API Error:', {
      status: error.status,
      statusText: error.statusText,
      url: error.url,
      error: error.error,
      message: error.message
    });
    
    return throwError(() => new Error(errorMessage));
  };
}
