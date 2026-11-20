import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatTooltipModule } from '@angular/material/tooltip';
import { NetworkCardComponent } from './components/network-card/network-card.component';
import { ReservationDialogComponent } from './components/reservation-dialog/reservation-dialog.component';
import { ConfirmReleaseAllDialogComponent } from './components/confirm-release-all-dialog/confirm-release-all-dialog.component';
import { TokenDialogComponent } from './components/token-dialog/token-dialog.component';
import { WilabApiService } from './services/wilab-api.service';
import { AuthService } from './services/auth.service';
import {
  InterfaceInfo,
  RecoveryState,
  RuntimeState,
  ReservationPolicy,
  ReservationRequest,
  ReservationResponse,
  NoDeviceAvailableError
} from './models/network.models';
import { ApiError, RecoveryCode, apiErrorToast, retryAfterSeconds } from './services/recovery-response';

/** Unified view-model for each interface card. */
export interface InterfaceSlot {
  display_name: string;
  interface: string;
  /** True when reserved by another user (regardless of unlimited or timed) */
  occupiedByOther: boolean;
  /** Remaining seconds for other user's timed reservation, null if unlimited or not occupied */
  otherReservationSeconds: number | null;
  recoveryState?: RecoveryState;
  runtimeState?: RuntimeState | null;
  /** Set when this client owns the reservation */
  myReservation: ReservationResponse | null;
}

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [
    CommonModule,
    MatToolbarModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatSnackBarModule,
    MatDialogModule,
    MatTooltipModule,
    NetworkCardComponent
  ],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss'
})
export class AppComponent implements OnInit, OnDestroy {
  title = 'Wi-Lab Network Management';
  version: string | null = null;
  loading = true;
  error: string | null = null;
  lockIcon = 'lock';

  /** All interface slots (one per system interface) */
  slots: InterfaceSlot[] = [];

  /** Whether the server allows unlimited reservations */
  allowUnlimitedReservation = false;
  reservationPolicy: ReservationPolicy = { min_seconds: 60, max_seconds: 86400, allow_unlimited: false };

  /** Error info when all devices are busy */
  capacityError: NoDeviceAvailableError | null = null;
  capacityCountdown = 0;
  reservationPending = false;
  releaseAllPending = false;
  recoveryRequest: ReservationRequest | null = null;
  recoveryCountdown = 0;
  private recoveryTimer: ReturnType<typeof setInterval> | null = null;
  private capacityTimer: ReturnType<typeof setInterval> | null = null;
  private statusTimer: ReturnType<typeof setInterval> | null = null;

  private static readonly STORAGE_KEY = 'wilab_my_reservations';

  /** Keep track of my reservations by interface name */
  private myReservations = new Map<string, ReservationResponse>();

  constructor(
    private apiService: WilabApiService,
    private authService: AuthService,
    private dialog: MatDialog,
    private snackBar: MatSnackBar
  ) {}

  public ngOnInit(): void {
    if (!this.authService.hasToken()) {
      this.promptForToken(true);
    } else {
      this.restoreReservations();
    }
  }

  public ngOnDestroy(): void {
    this.clearCapacityTimer();
    this.cancelRecoveryRetry();
    if (this.statusTimer !== null) {
      clearInterval(this.statusTimer);
      this.statusTimer = null;
    }
  }

  public get availableCount(): number {
    return this.slots.filter(s => s.myReservation === null && !s.occupiedByOther && !s.recoveryState).length;
  }

  public get reservedCount(): number {
    return this.slots.filter(s => s.myReservation !== null || s.occupiedByOther).length;
  }

  public get hasAnyReservation(): boolean {
    return this.myReservations.size > 0;
  }

  /** Restore saved reservations from localStorage, validate each against API. */
  private restoreReservations(): void {
    const saved = localStorage.getItem(AppComponent.STORAGE_KEY);
    if (!saved) {
      this.finishRestore();
      return;
    }

    let entries: Array<{ key: string; value: ReservationResponse }> = [];
    try {
      entries = JSON.parse(saved);
    } catch {
      localStorage.removeItem(AppComponent.STORAGE_KEY);
      this.finishRestore();
      return;
    }

    if (entries.length === 0) {
      this.finishRestore();
      return;
    }

    // Validate each saved reservation against the API
    let pending = entries.length;
    for (const entry of entries) {
      this.apiService.getReservation(entry.value.reservation_id).subscribe({
        next: (res: ReservationResponse) => {
          this.myReservations.set(res.interface, res);
          pending--;
          if (pending === 0) this.finishRestore();
        },
        error: () => {
          // Expired or invalid — skip
          pending--;
          if (pending === 0) this.finishRestore();
        }
      });
    }
  }

  private finishRestore(): void {
    this.persistReservations();
    this.loadStatus();
    this.statusTimer = setInterval(() => this.refreshStatus(), 10000);
  }

  private persistReservations(): void {
    const entries = Array.from(this.myReservations.entries()).map(
      ([key, value]) => ({ key, value })
    );
    if (entries.length > 0) {
      localStorage.setItem(AppComponent.STORAGE_KEY, JSON.stringify(entries));
    } else {
      localStorage.removeItem(AppComponent.STORAGE_KEY);
    }
  }

  public loadStatus(): void {
    this.loading = true;
    this.error = null;
    this.apiService.getStatus().subscribe({
      next: (response) => {
        this.version = response.version;
        this.reservationPolicy = response.reservation_policy ?? this.reservationPolicy;
        this.allowUnlimitedReservation = this.reservationPolicy.allow_unlimited;
        this.title = `Wi-Lab Network Management - ${this.version}`;
        this.buildSlots(response.networks);
        this.loading = false;
      },
      error: (err) => {
        this.error = `Failed to load status: ${err.message}`;
        this.snackBar.open(apiErrorToast('Failed to load status', err), 'Close', {
          duration: 10000, panelClass: ['error-snackbar']
        });
        this.loading = false;
      }
    });
  }

  /** Silent refresh (no loading spinner). */
  private refreshStatus(): void {
    this.apiService.getStatus().subscribe({
      next: (response) => {
        this.reservationPolicy = response.reservation_policy ?? this.reservationPolicy;
        this.allowUnlimitedReservation = this.reservationPolicy.allow_unlimited;
        this.buildSlots(response.networks);
      }
    });
  }

  private buildSlots(networks: InterfaceInfo[]): void {
    this.slots = networks.map(n => {
      const myRes = this.myReservations.get(n.interface) ?? null;
      return {
        display_name: n.display_name,
        interface: n.interface,
        occupiedByOther: !myRes && n.reserved,
        otherReservationSeconds: myRes ? null : n.reservation_remaining_seconds,
        recoveryState: n.recovery_state,
        runtimeState: n.runtime_state ?? null,
        myReservation: myRes,
      };
    });
  }

  public trackSlot(_index: number, slot: InterfaceSlot): string {
    return slot.interface;
  }

  public openReservationDialog(): void {
    this.cancelRecoveryRetry();
    this.capacityError = null;
    this.clearCapacityTimer();
    const dialogRef = this.dialog.open(ReservationDialogComponent, {
      width: '450px',
      data: {
        allowUnlimited: this.allowUnlimitedReservation,
        minSeconds: this.reservationPolicy.min_seconds,
        maxSeconds: this.reservationPolicy.max_seconds
      }
    });

    dialogRef.afterClosed().subscribe((result: ReservationRequest | undefined) => {
      if (result) {
        this.createReservation(result);
      }
    });
  }

  private createReservation(req: ReservationRequest): void {
    if (this.reservationPending) return;
    this.cancelRecoveryRetry();
    this.reservationPending = true;
    this.capacityError = null;
    this.clearCapacityTimer();
    this.apiService.createReservation(req).subscribe({
      next: (res: ReservationResponse) => {
        this.myReservations.set(res.interface, res);
        this.persistReservations();
        this.refreshStatus();
        this.reservationPending = false;
        this.snackBar.open('Device reserved successfully', 'Close', { duration: 3000 });
      },
      error: (err: ApiError) => {
        this.reservationPending = false;
        const raw = err.originalError;
        const detail = raw?.error?.detail;
        const recoveryDelay = raw && retryAfterSeconds(raw, 503, RecoveryCode.DeviceRecovering);
        if (raw?.status === 409 && detail?.code === RecoveryCode.NoDeviceAvailable &&
            (typeof detail.next_available_in === 'number' || detail.next_available_in === null)) {
          this.capacityError = detail as NoDeviceAvailableError;
          if (typeof detail.next_available_in === 'number') {
            this.startCapacityTimer(detail.next_available_in);
          }
        } else if (recoveryDelay) {
          this.waitForRecovery(req, recoveryDelay);
          this.refreshStatus();
        } else {
          const unavailable = raw?.status === 503 && detail?.code === RecoveryCode.DeviceUnavailable;
          if (unavailable) this.refreshStatus();
          const message = unavailable
            ? 'No devices can be reserved: the antennas are unavailable and no recovery is running.'
            : 'Reservation failed';
          this.snackBar.open(apiErrorToast(message, err), 'Close', {
            duration: 10000,
            panelClass: ['error-snackbar']
          });
        }
      }
    });
  }

  public onReservationReleased(interfaceName: string, reservationId: string): void {
    if (this.myReservations.get(interfaceName)?.reservation_id !== reservationId) return;
    this.myReservations.delete(interfaceName);
    this.persistReservations();
    this.slots = this.slots.map(slot => slot.interface === interfaceName
      ? { ...slot, myReservation: null, occupiedByOther: true } : slot);
    this.capacityError = null;
    this.clearCapacityTimer();
    this.refreshStatus();
  }

  private waitForRecovery(req: ReservationRequest, seconds: number): void {
    this.recoveryRequest = req;
    this.recoveryCountdown = seconds;
    const deadline = performance.now() + seconds * 1000;
    this.recoveryTimer = setInterval(() => {
      this.recoveryCountdown = Math.max(0, Math.ceil((deadline - performance.now()) / 1000));
      if (this.recoveryCountdown === 0 && this.recoveryTimer !== null) {
        clearInterval(this.recoveryTimer);
        this.recoveryTimer = null;
      }
    }, 250);
  }

  public retryReservation(): void {
    if (this.recoveryRequest && this.recoveryCountdown === 0) {
      this.createReservation(this.recoveryRequest);
    }
  }

  public cancelRecoveryRetry(): void {
    if (this.recoveryTimer !== null) {
      clearInterval(this.recoveryTimer);
      this.recoveryTimer = null;
    }
    this.recoveryRequest = null;
    this.recoveryCountdown = 0;
  }

  private startCapacityTimer(seconds: number): void {
    this.clearCapacityTimer();
    this.capacityCountdown = Math.max(0, Math.round(seconds));
    this.capacityTimer = setInterval(() => {
      this.capacityCountdown--;
      if (this.capacityCountdown <= 0) {
        this.clearCapacityTimer();
        this.capacityError = null;
      }
    }, 1000);
  }

  private clearCapacityTimer(): void {
    if (this.capacityTimer !== null) {
      clearInterval(this.capacityTimer);
      this.capacityTimer = null;
    }
  }

  public releaseAll(): void {
    const dialogRef = this.dialog.open(ConfirmReleaseAllDialogComponent, {
      width: '450px'
    });

    dialogRef.afterClosed().subscribe((password: string | null | undefined) => {
      if (!password || this.releaseAllPending || this.reservationPending) return;
      this.releaseAllPending = true;
      this.apiService.deleteAllReservations(password).subscribe({
        next: () => {
          this.myReservations.clear();
          this.persistReservations();
          this.slots = this.slots.map(slot => ({ ...slot, myReservation: null }));
          this.capacityError = null;
          this.clearCapacityTimer();
          this.refreshStatus();
          this.releaseAllPending = false;
          this.snackBar.open('All reservations released', 'Close', { duration: 3000 });
        },
        error: (err) => {
          this.releaseAllPending = false;
          this.snackBar.open(apiErrorToast('Failed to release all', err), 'Close', {
            duration: 10000,
            panelClass: ['error-snackbar']
          });
        }
      });
    });
  }

  /** Open the token dialog. When required=true the dialog cannot be dismissed. */
  public promptForToken(required: boolean): void {
    const dialogRef = this.dialog.open(TokenDialogComponent, {
      width: '450px',
      disableClose: required,
      data: { required }
    });

    dialogRef.afterClosed().subscribe((token: string | null) => {
      if (token) {
        this.authService.setToken(token);
        this.snackBar.open('Token saved', 'Close', { duration: 2000 });
        // If this was the initial prompt, start the app
        if (required) {
          this.restoreReservations();
        }
      }
    });
  }

  public openTokenDialog(): void {
    this.promptForToken(false);
  }
}
