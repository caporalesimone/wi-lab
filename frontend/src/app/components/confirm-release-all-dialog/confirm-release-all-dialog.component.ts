import { Component } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatDialogRef, MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';

/** Closes with the entered confirmation password, or null when cancelled. */
@Component({
  selector: 'app-confirm-release-all-dialog',
  standalone: true,
  imports: [FormsModule, MatDialogModule, MatButtonModule, MatFormFieldModule, MatIconModule, MatInputModule],
  template: `
    <h2 mat-dialog-title>
      <mat-icon color="warn">warning</mat-icon>
      Release All Reservations
    </h2>
    <mat-dialog-content>
      <p>This is a <strong>destructive operation</strong>.</p>
      <p>All device reservations will be released immediately and any activity
         currently running on reserved devices will be stopped.</p>
      <mat-form-field appearance="outline" class="password-field">
        <mat-label>Protected commands password</mat-label>
        <input matInput type="password" autocomplete="off" [(ngModel)]="password"
               (keyup.enter)="onConfirm()" cdkFocusInitial>
        <mat-hint>Set as protected_commands_password in the server configuration</mat-hint>
      </mat-form-field>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button (click)="onCancel()">Cancel</button>
      <button mat-raised-button color="warn" (click)="onConfirm()" [disabled]="!password">
        <mat-icon>delete_sweep</mat-icon>
        Release All
      </button>
    </mat-dialog-actions>
  `,
  styles: [`
    h2 { display: flex; align-items: center; gap: 8px; }
    p { margin: 8px 0; line-height: 1.5; }
    .password-field { width: 100%; margin-top: 8px; }
    mat-dialog-actions button { margin-left: 8px; }
  `]
})
export class ConfirmReleaseAllDialogComponent {
  password = '';

  constructor(private dialogRef: MatDialogRef<ConfirmReleaseAllDialogComponent>) {}

  onCancel(): void {
    this.dialogRef.close(null);
  }

  onConfirm(): void {
    if (this.password) {
      this.dialogRef.close(this.password);
    }
  }
}
