import { Component } from '@angular/core';
import { MatDialogRef, MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

@Component({
  selector: 'app-confirm-release-all-dialog',
  standalone: true,
  imports: [MatDialogModule, MatButtonModule, MatIconModule],
  template: `
    <h2 mat-dialog-title>
      <mat-icon color="warn">warning</mat-icon>
      Release All Reservations
    </h2>
    <mat-dialog-content>
      <p>This is a <strong>destructive operation</strong>.</p>
      <p>All device reservations will be released immediately and any activity
         currently running on reserved devices will be stopped.</p>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button (click)="onCancel()">Cancel</button>
      <button mat-raised-button color="warn" (click)="onConfirm()">
        <mat-icon>delete_sweep</mat-icon>
        Release All
      </button>
    </mat-dialog-actions>
  `,
  styles: [`
    h2 { display: flex; align-items: center; gap: 8px; }
    p { margin: 8px 0; line-height: 1.5; }
    mat-dialog-actions button { margin-left: 8px; }
  `]
})
export class ConfirmReleaseAllDialogComponent {
  constructor(private dialogRef: MatDialogRef<ConfirmReleaseAllDialogComponent>) {}

  onCancel(): void {
    this.dialogRef.close(false);
  }

  onConfirm(): void {
    this.dialogRef.close(true);
  }
}
