import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class AuthService {
  private static readonly STORAGE_KEY = 'wilab_auth_token';

  private tokenSubject = new BehaviorSubject<string | null>(this.loadToken());
  public token$ = this.tokenSubject.asObservable();

  getToken(): string | null {
    return this.tokenSubject.value;
  }

  hasToken(): boolean {
    return !!this.tokenSubject.value;
  }

  setToken(token: string): void {
    localStorage.setItem(AuthService.STORAGE_KEY, token);
    this.tokenSubject.next(token);
  }

  clearToken(): void {
    localStorage.removeItem(AuthService.STORAGE_KEY);
    this.tokenSubject.next(null);
  }

  private loadToken(): string | null {
    return localStorage.getItem(AuthService.STORAGE_KEY);
  }
}
