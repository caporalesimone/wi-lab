import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { NetworkCardComponent } from './components/network-card/network-card.component';
import { ReservationDialogComponent } from './components/reservation-dialog/reservation-dialog.component';
import { WilabApiService } from './services/wilab-api.service';
import { ReservationRequest, ReservationResponse, NoDeviceAvailableError } from './models/network.models';
import { HttpErrorResponse } from '@angular/common/http';

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
    NetworkCardComponent
  ],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss'
})
export class AppComponent implements OnInit {
  title = 'Wi-Lab Network Management';
  version: string | null = null;
  loading = true;
  error: string | null = null;

  /** Active reservations (empty = show empty state) */
  reservations: ReservationResponse[] = [];

  /** Error info when all devices are busy */
  capacityError: NoDeviceAvailableError | null = null;

  constructor(
    private apiService: WilabApiService,
    private dialog: MatDialog,
    private snackBar: MatSnackBar
  ) {}

  public ngOnInit(): void {
    this.loadStatus();
  }

  public loadStatus(): void {
    this.loading = true;
    this.error = null;
    this.apiService.getStatus().subscribe({
      next: (response) => {
        this.version = response.version;
        this.title = `Wi-Lab Network Management - ${this.version}`;
        this.loading = false;
      },
      error: (err) => {
        this.error = `Failed to load status: ${err.message}`;
        this.loading = false;
      }
    });
  }

  public openReservationDialog(): void {
    this.capacityError = null;
    const dialogRef = this.dialog.open(ReservationDialogComponent, {
      width: '450px'
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
    this.apiService.createReservation(req).subscribe({
      next: (res: ReservationResponse) => {
        this.reservations = [...this.reservations, res];
        this.loading = false;
        this.snackBar.open('Device reserved successfully', 'Close', { duration: 3000 });
      },
      error: (err) => {
        this.loading = false;
        // Check for 409 capacity error
        const raw = (err as { originalError?: HttpErrorResponse }).originalError;
        const detail = raw?.error?.detail;
        if (raw && raw.status === 409 && detail?.next_available_in !== undefined) {
          this.capacityError = detail as NoDeviceAvailableError;
        } else {
          this.snackBar.open(`Reservation failed: ${err.message}`, 'Close', {
            duration: 5000,
            panelClass: ['error-snackbar']
          });
        }
      }
    });
  }

  public onReservationReleased(reservationId: string): void {
    this.reservations = this.reservations.filter(r => r.reservation_id !== reservationId);
    this.capacityError = null;
  }
}
