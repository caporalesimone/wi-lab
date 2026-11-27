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
import { AntennaCapabilities, ClientInfo, NetworkCreateRequest, NetworkStatus } from '../../models/network.models';
import { ApiError, apiErrorToast, reservationGoneText } from '../../services/recovery-response';
import { environment } from '../../../environments/environment';
import { GENERATION_LABELS, NetworkFormDialogComponent } from '../network-form-dialog/network-form-dialog.component';
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
  generationLabels = GENERATION_LABELS;
  @Input() slot!: InterfaceSlot;
  @Output() released = new EventEmitter<string>();

  status: NetworkStatus | null = null;
  loading = false;
  createMessage: string | null = null;
  private creation?: Subscription;
  /** GET /antennas/{interface} is running for the start dialog: a second click opens nothing (REV-14). */
  private openingForm = false;
  pollingSubscription?: Subscription;
  countdownSubscription?: Subscription;

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
    return !this.isMine && !this.slot.recoveryState && this.slot.occupiedByOther;
  }

  public get isAvailable(): boolean {
    return !this.isMine && !this.slot.recoveryState && !this.slot.occupiedByOther;
  }

  public get reservationId(): string {
    return this.slot.myReservation?.reservation_id ?? '';
  }

  /** GET /access-point/{reservation_id} when read; /status (every 10 s) only before the first read (REV-13). */
  public get runtimeState() {
    return this.status === null ? this.slot.runtimeState : this.status.runtime_state;
  }

  /** A start runs, launched here or elsewhere (reload, another tab). */
  public get starting(): boolean {
    return this.runtimeState === 'starting';
  }

  /**
   * DELETE /access-point/{reservation_id} answers 200 also with no running network in these states:
   * it cancels the start, clears start_failed or gives up the watchdog's retries (REV-14).
   */
  public get canStop(): boolean {
    return !!this.status?.active
      || this.runtimeState === 'starting'
      || this.runtimeState === 'start_failed'
      || this.runtimeState === 'restore_failed'
      || this.runtimeState === 'stop_failed';
  }

  /** A sentence for every runtime_state of GET /access-point/{reservation_id} or /status. */
  public get runtimeStateLabel(): string | null {
    switch (this.runtimeState) {
      case 'starting': return 'Starting the access point...';
      case 'start_failed': {
        const error = this.status?.error;
        const stage = error?.stage ? ` (${error.stage})` : '';
        return `The last start failed${stage}: ${error?.message ?? 'unknown error'}. Start WiFi again or stop to clear it.`;
      }
      case 'restoring_ap': return 'Restoring the access point. Clients may need to reconnect.';
      case 'restoring_dhcp': return 'Restarting DHCP.';
      case 'dhcp_failed': return 'DHCP is unavailable; the whole network is being restarted.';
      case 'restore_failed': return 'The access point is down; Wi-Lab keeps retrying. Stop WiFi to give up.';
      case 'stop_failed': return 'The last stop did not complete. Stop WiFi again.';
      default: return null;
    }
  }

  public get restoring(): boolean {
    return this.runtimeState === 'restoring_ap' || this.runtimeState === 'restoring_dhcp';
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

  /** True when occupied by another user with an unlimited reservation. */
  public get isOccupiedUnlimited(): boolean {
    return this.isOccupied && this.slot.otherReservationSeconds === null;
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
      if (this.slot.otherReservationSeconds !== null) {
        this.startOccupiedCountdown(this.slot.otherReservationSeconds);
      }
    }
  }

  public ngOnChanges(changes: SimpleChanges): void {
    if (changes['slot'] && !changes['slot'].firstChange) {
      const previousId = changes['slot'].previousValue?.myReservation?.reservation_id ?? '';
      if (previousId !== this.reservationId) {
        this.stopOwned();
        this.stopOccupiedCountdown();
        if (this.isMine) this.startOwned();
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
    this.checkStatus();
    this.startPolling();
    if (this.slot.myReservation.expires_in !== null) {
      this.totalDuration = this.slot.myReservation.expires_in;
      this.remainingSeconds = this.slot.myReservation.expires_in;
      this.startCountdown();
    }
  }

  private stopOwned(): void {
    this.creation?.unsubscribe();
    this.createMessage = null;
    this.loading = false;
    this.stopPolling();
    this.stopCountdown();
    this.status = null;
    this.remainingSeconds = 0;
    this.totalDuration = 0;
  }

  private startPolling(): void {
    this.stopPolling();
    this.pollingSubscription = interval(environment.pollingInterval).subscribe(() => {
      this.checkStatus();
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
        this.stopCountdown();
        this.creation?.unsubscribe();
        this.released.emit(this.reservationId);
      }
    });
  }

  private stopCountdown(): void {
    this.countdownSubscription?.unsubscribe();
  }

  public checkStatus(): void {
    if (!this.isMine || this.createMessage !== null) return;
    const reservationId = this.reservationId;

    this.wilabApiService.getNetworkStatus(reservationId).subscribe({
      next: (networkStatus) => {
        if (this.reservationId !== reservationId || this.createMessage !== null) return;
        this.status = networkStatus;
        if (networkStatus.reservation?.expires_in !== undefined && networkStatus.reservation?.expires_in !== null) {
          this.remainingSeconds = networkStatus.reservation.expires_in;
        }
      },
      error: (err: ApiError) => {
        if (this.reservationId !== reservationId || this.createMessage !== null) return;
        if (err.originalError?.status === 404) {
          const why = reservationGoneText(err);
          if (why) this.snackBar.open(why, 'Close', { duration: 8000 });
          this.released.emit(reservationId);
        }
      }
    });
  }

  public startWiFi(): void {
    if (!this.isMine || this.loading || this.restoring || this.starting || this.openingForm || this.createMessage !== null) return;
    this.openingForm = true;
    // The form lists only what this antenna can use (GET /antennas/{interface}).
    this.wilabApiService.getCapabilities(this.slot.interface).subscribe({
      next: antenna => this.openNetworkForm(antenna),
      error: (err: ApiError) => {
        this.openingForm = false;
        this.snackBar.open(
          apiErrorToast('Failed to read the antenna options', err), 'Close',
          { duration: 10000, panelClass: ['error-snackbar'] },
        );
      },
    });
  }

  private openNetworkForm(antenna: AntennaCapabilities): void {
    if (!this.isMine || this.loading || this.restoring) return;
    const reservationId = this.reservationId;
    const dialogRef = this.dialog.open(NetworkFormDialogComponent, {
      width: '500px',
      data: { netId: reservationId, antenna }
    });

    dialogRef.afterClosed().subscribe((result: NetworkCreateRequest | undefined) => {
      this.openingForm = false;
      if (result && this.reservationId === reservationId && !this.loading && !this.restoring && !this.starting) {
        // Not `loading`: Stop (cancels the start) and Release stay usable while it runs (REV-13).
        this.createMessage = 'Starting WiFi... If the radio needs restarting this can take up to a minute.';
        this.creation = this.wilabApiService.startNetwork(reservationId, result).subscribe({
          next: (network) => {
            if (this.reservationId !== reservationId) return;
            // The 202 body first: the card shows "starting" at once, no stale label (REV-13).
            this.status = network;
            if (network.runtime_state === 'starting') return;
            this.createMessage = null;
            if (network.runtime_state === 'start_failed') {
              // Non-radio failure, rolled back; the reservation is still valid. The card shows the error.
              const stage = network.error?.stage ? ` (${network.error.stage})` : '';
              this.snackBar.open(`Failed to start network${stage}: ${network.error?.message ?? 'unknown error'}`,
                'Close', { duration: 10000, panelClass: ['error-snackbar'] });
            } else if (network.active) {
              this.snackBar.open('WiFi network started successfully', 'Close', { duration: 3000 });
            } else {
              // Not active and no start running: cancelled (a stop or release from another tab).
              this.snackBar.open('The start was cancelled; the network is not running.', 'Close', { duration: 5000 });
            }
            this.checkStatus();
          },
          error: (err: ApiError) => {
            this.createMessage = null;
            const raw = err.originalError;
            if (raw?.status === 404) {
              // The reservation ended while starting: detail.reason says why.
              this.released.emit(reservationId);
              this.snackBar.open(`WiFi did not start. ${reservationGoneText(err) ?? ''}`.trim(), 'Close', {
                duration: 10000, panelClass: ['error-snackbar']
              });
              return;
            }
            // No final answer (timeout, connection lost): the normal polling shows the real state.
            this.checkStatus();
            const stillRunning = (err.originalError as unknown as Error | undefined)?.name === 'TimeoutError';
            this.snackBar.open(stillRunning
              ? 'The start is taking longer than expected; the card updates when it ends.'
              : apiErrorToast('Failed to start network', err), 'Close', {
              duration: 10000, panelClass: ['error-snackbar']
            });
          }
        });
      }
    });
  }

  public stopWiFi(): void {
    const what = this.status?.active ? `the WiFi network "${this.status?.wifi?.ssid}"` : 'the start or the retries on this antenna';
    if (!confirm(`Are you sure you want to stop ${what}?`)) return;
    this.loading = true;
    this.wilabApiService.stopNetwork(this.reservationId).subscribe({
      next: () => {
        this.snackBar.open('WiFi network stopped successfully', 'Close', { duration: 3000 });
        this.checkStatus();
        this.loading = false;
      },
      error: (err) => {
        this.snackBar.open(apiErrorToast('Failed to stop network', err), 'Close', {
          duration: 10000, panelClass: ['error-snackbar']
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
        this.checkStatus();
        this.loading = false;
      },
      error: (err) => {
        this.snackBar.open(apiErrorToast('Failed to enable internet', err), 'Close', {
          duration: 10000, panelClass: ['error-snackbar']
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
        this.checkStatus();
        this.loading = false;
      },
      error: (err) => {
        this.snackBar.open(apiErrorToast('Failed to disable internet', err), 'Close', {
          duration: 10000, panelClass: ['error-snackbar']
        });
        this.loading = false;
      }
    });
  }

  public releaseReservation(): void {
    if (!this.isMine || this.loading) return;
    if (!confirm('Are you sure you want to release this device reservation?')) return;
    const reservationId = this.reservationId;
    this.loading = true;
    this.wilabApiService.deleteReservation(reservationId).subscribe({
      next: () => {
        this.snackBar.open('Reservation released', 'Close', { duration: 3000 });
        this.released.emit(reservationId);
      },
      error: (err: ApiError) => {
        if (err.originalError?.status === 404) {
          this.released.emit(reservationId);
        } else {
          this.snackBar.open(apiErrorToast('Failed to release', err), 'Close', {
            duration: 10000, panelClass: ['error-snackbar']
          });
          this.loading = false;
        }
      }
    });
  }
}
