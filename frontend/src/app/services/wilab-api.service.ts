import { Injectable } from '@angular/core';
import { HttpClient, HttpHeaders, HttpErrorResponse } from '@angular/common/http';
import { Observable, throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { environment } from '../../environments/environment';
import {
  InterfaceInfo,
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

  public getInterfaces(): Observable<InterfaceInfo[]> {
    return this.http.get<InterfaceInfo[]>(`${this.apiUrl}/interfaces`, {
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
    if (error.error instanceof ErrorEvent) {
      errorMessage = `Error: ${error.error.message}`;
    } else {
      errorMessage = `Error Code: ${error.status}\nMessage: ${error.error?.detail || error.message}`;
    }
    return throwError(() => new Error(errorMessage));
  };
}
