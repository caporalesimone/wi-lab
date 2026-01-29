import { Component, Input, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { interval, Subscription } from 'rxjs';
import { WilabApiService } from '../../services/wilab-api.service';
import { NetworkStatus } from '../../models/network.models';
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
    MatChipsModule,
    MatProgressSpinnerModule,
    MatDialogModule
  ],
  templateUrl: './network-card.component.html',
  styleUrl: './network-card.component.scss'
})
export class NetworkCardComponent implements OnInit, OnDestroy {
  @Input() netId!: string;
  @Input() interface!: string;

  status: NetworkStatus | null = null;
  loading = false;
  pollingSubscription?: Subscription;
  clientsCount = 0;

  constructor(
    private wilabApiService: WilabApiService,
    private dialog: MatDialog,
    private snackBar: MatSnackBar
  ) {}

  public ngOnInit() {
    this.checkStatus(false); // Silent check on init
    this.startPolling();
  }

  public ngOnDestroy() {
    this.stopPolling();
  }

  public startPolling() {
    this.pollingSubscription = interval(environment.pollingInterval).subscribe(() => {
      this.checkStatus(false); // Silent check for polling
    });
  }

  public stopPolling() {
    if (this.pollingSubscription) {
      this.pollingSubscription.unsubscribe();
    }
  }

  public checkStatus(showNotification: boolean = true) {
    // Only set loading for manual actions (not for automatic polling)
    if (showNotification) {
      this.loading = true;
    }
    
    this.wilabApiService.getNetworkStatus(this.netId).subscribe({
      next: (status) => {
        this.status = status;
        this.clientsCount = status.clients_connected || 0;
        if (showNotification) {
          this.loading = false;
          this.snackBar.open('Status updated', 'Close', {
            duration: 2000
          });
        }
      },
      error: (err) => {
        if (showNotification) {
          this.loading = false;
        }
        // If network doesn't exist (404), it means it's not active
        if (err.message.includes('404')) {
          this.status = {
            net_id: this.netId,
            interface: this.interface,
            active: false,
            internet_enabled: false
          };
          this.clientsCount = 0;
          if (showNotification) {
            this.snackBar.open('Network is not active', 'Close', {
              duration: 2000
            });
          }
        } else {
          console.error('Error checking status:', err);
          if (showNotification) {
            this.snackBar.open(`Error: ${err.message}`, 'Close', {
              duration: 5000,
              panelClass: ['error-snackbar']
            });
          }
        }
      }
    });
  }

  public startWiFi() {
    const dialogRef = this.dialog.open(NetworkFormDialogComponent, {
      width: '500px',
      data: { netId: this.netId }
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        this.loading = true;
        this.wilabApiService.startNetwork(this.netId, result).subscribe({
          next: () => {
            this.snackBar.open('WiFi network started successfully', 'Close', {
              duration: 3000
            });
            this.checkStatus(false); // Silent update, we already showed the notification
            this.loading = false;
          },
          error: (err) => {
            this.snackBar.open(`Failed to start network: ${err.message}`, 'Close', {
              duration: 5000,
              panelClass: ['error-snackbar']
            });
            this.loading = false;
          }
        });
      }
    });
  }

  public stopWiFi() {
    if (!confirm(`Are you sure you want to stop the WiFi network "${this.status?.ssid}"?`)) {
      return;
    }

    this.loading = true;
    this.wilabApiService.stopNetwork(this.netId).subscribe({
      next: () => {
        this.snackBar.open('WiFi network stopped successfully', 'Close', {
          duration: 3000
        });
        this.checkStatus(false); // Silent update, we already showed the notification
        this.loading = false;
      },
      error: (err) => {
        this.snackBar.open(`Failed to stop network: ${err.message}`, 'Close', {
          duration: 5000,
          panelClass: ['error-snackbar']
        });
        this.loading = false;
      }
    });
  }

  public enableInternet() {
    this.loading = true;
    this.wilabApiService.enableInternet(this.netId).subscribe({
      next: () => {
        this.snackBar.open('Internet access enabled', 'Close', {
          duration: 3000
        });
        this.checkStatus(false); // Silent update, we already showed the notification
        this.loading = false;
      },
      error: (err) => {
        this.snackBar.open(`Failed to enable internet: ${err.message}`, 'Close', {
          duration: 5000,
          panelClass: ['error-snackbar']
        });
        this.loading = false;
      }
    });
  }

  public disableInternet() {
    this.loading = true;
    this.wilabApiService.disableInternet(this.netId).subscribe({
      next: () => {
        this.snackBar.open('Internet access disabled', 'Close', {
          duration: 3000
        });
        this.checkStatus(false); // Silent update, we already showed the notification
        this.loading = false;
      },
      error: (err) => {
        this.snackBar.open(`Failed to disable internet: ${err.message}`, 'Close', {
          duration: 5000,
          panelClass: ['error-snackbar']
        });
        this.loading = false;
      }
    });
  }
}
