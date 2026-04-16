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
  ReservationRequest,
  ReservationResponse,
  NoDeviceAvailableError
} from './models/network.models';
import { HttpErrorResponse } from '@angular/common/http';

/** Unified view-model for each interface card. */
export interface InterfaceSlot {
  display_name: string;
  interface: string;
  /** True when reserved by another user (regardless of unlimited or timed) */
  occupiedByOther: boolean;
  /** Remaining seconds for other user's timed reservation, null if unlimited or not occupied */
  otherReservationSeconds: number | null;
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

  /** All interface slots (one per system interface) */
  slots: InterfaceSlot[] = [];

  /** Whether the server allows unlimited reservations */
  allowUnlimitedReservation = false;

  /** Error info when all devices are busy */
  capacityError: NoDeviceAvailableError | null = null;
  capacityCountdown = 0;
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
    if (this.statusTimer !== null) {
      clearInterval(this.statusTimer);
      this.statusTimer = null;
    }
  }

  public get availableCount(): number {
    return this.slots.filter(s => s.myReservation === null && !s.occupiedByOther).length;
  }

  public get reservedCount(): number {
    return this.slots.length - this.availableCount;
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
        this.allowUnlimitedReservation = response.allow_unlimited_reservation ?? false;
        this.title = `Wi-Lab Network Management - ${this.version}`;
        this.buildSlots(response.networks);
        this.loading = false;
      },
      error: (err) => {
        this.error = `Failed to load status: ${err.message}`;
        this.loading = false;
      }
    });
  }

  /** Silent refresh (no loading spinner). */
  private refreshStatus(): void {
    this.apiService.getStatus().subscribe({
      next: (response) => {
        this.allowUnlimitedReservation = response.allow_unlimited_reservation ?? false;
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
        myReservation: myRes,
      };
    });
  }

  public openReservationDialog(): void {
    this.capacityError = null;
    this.clearCapacityTimer();
    const dialogRef = this.dialog.open(ReservationDialogComponent, {
      width: '450px',
      data: { allowUnlimited: this.allowUnlimitedReservation }
    });

    dialogRef.afterClosed().subscribe((result: ReservationRequest | undefined) => {
      if (result) {
        this.createReservation(result);
      }
    });
  }

  private createReservation(req: ReservationRequest): void {
    this.loading = true;
    this.capacityError = null;
    this.clearCapacityTimer();
    this.apiService.createReservation(req).subscribe({
      next: (res: ReservationResponse) => {
        this.myReservations.set(res.interface, res);
        this.persistReservations();
        this.refreshStatus();
        this.loading = false;
        this.snackBar.open('Device reserved successfully', 'Close', { duration: 3000 });
      },
      error: (err) => {
        this.loading = false;
        const raw = (err as { originalError?: HttpErrorResponse }).originalError;
        const detail = raw?.error?.detail;
        if (raw && raw.status === 409 && detail?.next_available_in !== undefined) {
          this.capacityError = detail as NoDeviceAvailableError;
          this.startCapacityTimer(detail.next_available_in);
        } else {
          this.snackBar.open(`Reservation failed: ${err.message}`, 'Close', {
            duration: 5000,
            panelClass: ['error-snackbar']
          });
        }
      }
    });
  }

  public onReservationReleased(interfaceName: string): void {
    this.myReservations.delete(interfaceName);
    this.persistReservations();
    this.capacityError = null;
    this.clearCapacityTimer();
    this.refreshStatus();
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

    dialogRef.afterClosed().subscribe((confirmed: boolean) => {
      if (!confirmed) return;
      this.loading = true;
      this.apiService.deleteAllReservations().subscribe({
        next: () => {
          this.myReservations.clear();
          this.persistReservations();
          this.capacityError = null;
          this.clearCapacityTimer();
          this.refreshStatus();
          this.loading = false;
          this.snackBar.open('All reservations released', 'Close', { duration: 3000 });
        },
        error: (err) => {
          this.loading = false;
          this.snackBar.open(`Failed to release all: ${err.message}`, 'Close', {
            duration: 5000,
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
