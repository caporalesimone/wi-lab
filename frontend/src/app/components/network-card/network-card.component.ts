import { Component, Input, Output, EventEmitter, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { interval, Subscription } from 'rxjs';
import { WilabApiService } from '../../services/wilab-api.service';
import { ClientInfo, NetworkStatus, ReservationResponse } from '../../models/network.models';
import { environment } from '../../../environments/environment';
import { NetworkFormDialogComponent } from '../network-form-dialog/network-form-dialog.component';

@Component({
  selector: 'app-network-card',
  standalone: true,
  imports: [
    CommonModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatProgressBarModule,
    MatTooltipModule,
    MatDialogModule
  ],
  templateUrl: './network-card.component.html',
  styleUrl: './network-card.component.scss'
})
export class NetworkCardComponent implements OnInit, OnDestroy {
  @Input() reservationId!: string;
  @Input() reservation!: ReservationResponse;
  @Output() released = new EventEmitter<void>();

  status: NetworkStatus | null = null;
  loading = false;
  pollingSubscription?: Subscription;
  countdownSubscription?: Subscription;
  clientsCount = 0;

  /** Remaining seconds from reservation (always visible) */
  remainingSeconds = 0;
  /** Total reservation duration for progress calculation */
  totalDuration = 0;

  public get clients(): ClientInfo[] {
    return this.status?.clients ?? [];
  }

  public get progressPercent(): number {
    if (this.totalDuration <= 0) return 0;
    return Math.max(0, Math.min(100, (this.remainingSeconds / this.totalDuration) * 100));
  }

  public formatCountdown(totalSeconds: number): string {
    const s = Math.max(0, totalSeconds);
    const hours = Math.floor(s / 3600);
    const minutes = Math.floor((s % 3600) / 60);
    const seconds = s % 60;
    return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  }

  public getTxPowerLabel(level?: number): string {
    if (level === undefined || level === null) return 'Unknown';
    if (level === 1) return 'Level 1 (Min)';
    if (level === 4) return 'Level 4 (Max)';
    return `Level ${level}`;
  }

  constructor(
    private wilabApiService: WilabApiService,
    private dialog: MatDialog,
    private snackBar: MatSnackBar
  ) {}

  public ngOnInit(): void {
    this.totalDuration = this.reservation.expires_in;
    this.remainingSeconds = this.reservation.expires_in;
    this.checkStatus(false);
    this.startPolling();
    this.startCountdown();
  }

  public ngOnDestroy(): void {
    this.stopPolling();
    this.stopCountdown();
  }

  private startPolling(): void {
    this.pollingSubscription = interval(environment.pollingInterval).subscribe(() => {
      this.checkStatus(false);
    });
  }

  private stopPolling(): void {
    this.pollingSubscription?.unsubscribe();
  }

  private startCountdown(): void {
    this.countdownSubscription = interval(1000).subscribe(() => {
      if (this.remainingSeconds > 0) {
        this.remainingSeconds--;
      }
      if (this.remainingSeconds <= 0) {
        // Reservation expired — auto-release
        this.released.emit();
      }
    });
  }

  private stopCountdown(): void {
    this.countdownSubscription?.unsubscribe();
  }

  public checkStatus(showNotification: boolean = true): void {
    if (showNotification) this.loading = true;

    this.wilabApiService.getNetworkStatus(this.reservationId).subscribe({
      next: (networkStatus) => {
        this.status = networkStatus;
        this.clientsCount = networkStatus.clients_connected || 0;
        // Resync countdown with server value
        if (networkStatus.expires_in !== undefined && networkStatus.expires_in !== null) {
          this.remainingSeconds = networkStatus.expires_in;
        }
        if (showNotification) {
          this.loading = false;
          this.snackBar.open('Status updated', 'Close', { duration: 2000 });
        }
      },
      error: (err) => {
        if (showNotification) this.loading = false;
        if (err.message?.includes('404')) {
          // Reservation expired or deleted on backend
          this.released.emit();
        } else if (showNotification) {
          this.snackBar.open(`Error: ${err.message}`, 'Close', {
            duration: 5000,
            panelClass: ['error-snackbar']
          });
        }
      }
    });
  }

  public startWiFi(): void {
    const dialogRef = this.dialog.open(NetworkFormDialogComponent, {
      width: '500px',
      data: { netId: this.reservationId }
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        this.loading = true;
        this.wilabApiService.startNetwork(this.reservationId, result).subscribe({
          next: () => {
            this.snackBar.open('WiFi network started successfully', 'Close', { duration: 3000 });
            this.checkStatus(false);
            this.loading = false;
          },
          error: (err) => {
            this.snackBar.open(`Failed to start network: ${err.message}`, 'Close', {
              duration: 5000, panelClass: ['error-snackbar']
            });
            this.loading = false;
          }
        });
      }
    });
  }

  public stopWiFi(): void {
    if (!confirm(`Are you sure you want to stop the WiFi network "${this.status?.ssid}"?`)) return;
    this.loading = true;
    this.wilabApiService.stopNetwork(this.reservationId).subscribe({
      next: () => {
        this.snackBar.open('WiFi network stopped successfully', 'Close', { duration: 3000 });
        this.checkStatus(false);
        this.loading = false;
      },
      error: (err) => {
        this.snackBar.open(`Failed to stop network: ${err.message}`, 'Close', {
          duration: 5000, panelClass: ['error-snackbar']
        });
        this.loading = false;
      }
    });
  }

  public enableInternet(): void {
    this.loading = true;
    this.wilabApiService.enableInternet(this.reservationId).subscribe({
      next: () => {
        this.snackBar.open('Internet access enabled', 'Close', { duration: 3000 });
        this.checkStatus(false);
        this.loading = false;
      },
      error: (err) => {
        this.snackBar.open(`Failed to enable internet: ${err.message}`, 'Close', {
          duration: 5000, panelClass: ['error-snackbar']
        });
        this.loading = false;
      }
    });
  }

  public disableInternet(): void {
    this.loading = true;
    this.wilabApiService.disableInternet(this.reservationId).subscribe({
      next: () => {
        this.snackBar.open('Internet access disabled', 'Close', { duration: 3000 });
        this.checkStatus(false);
        this.loading = false;
      },
      error: (err) => {
        this.snackBar.open(`Failed to disable internet: ${err.message}`, 'Close', {
          duration: 5000, panelClass: ['error-snackbar']
        });
        this.loading = false;
      }
    });
  }

  public releaseReservation(): void {
    if (!confirm('Are you sure you want to release this device reservation?')) return;
    this.loading = true;
    this.wilabApiService.deleteReservation(this.reservationId).subscribe({
      next: () => {
        this.snackBar.open('Reservation released', 'Close', { duration: 3000 });
        this.released.emit();
      },
      error: (err) => {
        // Even if backend returns 404 (already expired), remove card
        if (err.message?.includes('404')) {
          this.released.emit();
        } else {
          this.snackBar.open(`Failed to release: ${err.message}`, 'Close', {
            duration: 5000, panelClass: ['error-snackbar']
          });
          this.loading = false;
        }
      }
    });
  }
}
