import { Component, Input, Output, EventEmitter, OnInit, OnDestroy, OnChanges, SimpleChanges } from '@angular/core';
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
import { ClientInfo, NetworkStatus } from '../../models/network.models';
import { environment } from '../../../environments/environment';
import { NetworkFormDialogComponent } from '../network-form-dialog/network-form-dialog.component';
import { InterfaceSlot } from '../../app.component';

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
export class NetworkCardComponent implements OnInit, OnDestroy, OnChanges {
  @Input() slot!: InterfaceSlot;
  @Output() released = new EventEmitter<void>();

  status: NetworkStatus | null = null;
  loading = false;
  pollingSubscription?: Subscription;
  countdownSubscription?: Subscription;
  clientsCount = 0;

  /** Remaining seconds from reservation (always visible when mine) */
  remainingSeconds = 0;
  /** Total reservation duration for progress calculation */
  totalDuration = 0;
  /** Local countdown for occupied cards (ticks every second) */
  occupiedCountdown = 0;
  private occupiedTimer: ReturnType<typeof setInterval> | null = null;

  public get isMine(): boolean {
    return this.slot.myReservation !== null;
  }

  public get isOccupied(): boolean {
    return !this.isMine && this.slot.otherReservationSeconds !== null;
  }

  public get isAvailable(): boolean {
    return !this.isMine && this.slot.otherReservationSeconds === null;
  }

  public get reservationId(): string {
    return this.slot.myReservation?.reservation_id ?? '';
  }

  public get clients(): ClientInfo[] {
    return this.status?.clients ?? [];
  }

  public get progressPercent(): number {
    if (this.isUnlimited || this.totalDuration <= 0) return 0;
    return Math.max(0, Math.min(100, (this.remainingSeconds / this.totalDuration) * 100));
  }

  /** True when the current reservation has no expiry. */
  public get isUnlimited(): boolean {
    return this.isMine && this.slot.myReservation?.expires_in === null;
  }

  public formatCountdown(totalSeconds: number): string {
    const s = Math.max(0, totalSeconds);
    const hours = Math.floor(s / 3600);
    const minutes = Math.floor((s % 3600) / 60);
    const seconds = s % 60;
    return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  }

  constructor(
    private wilabApiService: WilabApiService,
    private dialog: MatDialog,
    private snackBar: MatSnackBar
  ) {}

  public ngOnInit(): void {
    if (this.isMine) {
      this.startOwned();
    }
    if (this.isOccupied) {
      this.startOccupiedCountdown(this.slot.otherReservationSeconds!);
    }
  }

  public ngOnChanges(changes: SimpleChanges): void {
    if (changes['slot'] && !changes['slot'].firstChange) {
      const wasMine = changes['slot'].previousValue?.myReservation !== null;
      if (this.isMine && !wasMine) {
        this.stopOccupiedCountdown();
        this.startOwned();
      } else if (!this.isMine && wasMine) {
        this.stopOwned();
      }
      // Sync occupied countdown from API without recreating timer
      if (this.isOccupied && this.slot.otherReservationSeconds !== null) {
        if (this.occupiedTimer === null) {
          this.startOccupiedCountdown(this.slot.otherReservationSeconds);
        } else {
          this.occupiedCountdown = this.slot.otherReservationSeconds;
        }
      } else if (!this.isOccupied) {
        this.stopOccupiedCountdown();
      }
    }
  }

  public ngOnDestroy(): void {
    this.stopOwned();
    this.stopOccupiedCountdown();
  }

  private startOccupiedCountdown(seconds: number): void {
    this.occupiedCountdown = Math.max(0, Math.round(seconds));
    this.occupiedTimer = setInterval(() => {
      if (this.occupiedCountdown > 0) {
        this.occupiedCountdown--;
      }
    }, 1000);
  }

  private stopOccupiedCountdown(): void {
    if (this.occupiedTimer !== null) {
      clearInterval(this.occupiedTimer);
      this.occupiedTimer = null;
    }
  }

  private startOwned(): void {
    if (!this.slot.myReservation) return;
    this.checkStatus(false);
    this.startPolling();
    if (this.slot.myReservation.expires_in !== null) {
      this.totalDuration = this.slot.myReservation.expires_in;
      this.remainingSeconds = this.slot.myReservation.expires_in;
      this.startCountdown();
    }
  }

  private stopOwned(): void {
    this.stopPolling();
    this.stopCountdown();
    this.status = null;
    this.remainingSeconds = 0;
    this.totalDuration = 0;
  }

  private startPolling(): void {
    this.stopPolling();
    this.pollingSubscription = interval(environment.pollingInterval).subscribe(() => {
      this.checkStatus(false);
    });
  }

  private stopPolling(): void {
    this.pollingSubscription?.unsubscribe();
  }

  private startCountdown(): void {
    this.stopCountdown();
    this.countdownSubscription = interval(1000).subscribe(() => {
      if (this.remainingSeconds > 0) {
        this.remainingSeconds--;
      }
      if (this.remainingSeconds <= 0) {
        this.released.emit();
      }
    });
  }

  private stopCountdown(): void {
    this.countdownSubscription?.unsubscribe();
  }

  public checkStatus(showNotification: boolean = true): void {
    if (!this.isMine) return;
    if (showNotification) this.loading = true;

    this.wilabApiService.getNetworkStatus(this.reservationId).subscribe({
      next: (networkStatus) => {
        this.status = networkStatus;
        this.clientsCount = networkStatus.clients_connected || 0;
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
