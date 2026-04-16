import { Component, Inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogRef, MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatIconModule } from '@angular/material/icon';

export interface TokenDialogData {
  /** When true the dialog cannot be dismissed without entering a token */
  required: boolean;
}

@Component({
  selector: 'app-token-dialog',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatDialogModule,
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
    MatIconModule
  ],
  template: `
    <h2 mat-dialog-title>
      <mat-icon>lock</mat-icon>
      Authentication Token
    </h2>
    <mat-dialog-content>
      <p>Enter the token configured in <code>config.yaml</code>.</p>
      <mat-form-field appearance="outline" style="width: 100%">
        <mat-label>Auth Token</mat-label>
        <input matInput
               [(ngModel)]="token"
               placeholder="e.g. secret-token-12345"
               autocomplete="off">
      </mat-form-field>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button (click)="onCancel()" *ngIf="!data.required">Cancel</button>
      <button mat-raised-button color="primary" (click)="onSave()" [disabled]="!token.trim()">
        <mat-icon>save</mat-icon>
        Save
      </button>
    </mat-dialog-actions>
  `,
  styles: [`
    h2 { display: flex; align-items: center; gap: 8px; }
    p { margin: 8px 0; line-height: 1.5; }
    code { background: rgba(0,0,0,0.06); padding: 2px 6px; border-radius: 4px; }
    mat-dialog-actions button { margin-left: 8px; }
  `]
})
export class TokenDialogComponent {
  token = '';

  constructor(
    private dialogRef: MatDialogRef<TokenDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: TokenDialogData
  ) {}

  onCancel(): void {
    this.dialogRef.close(null);
  }

  onSave(): void {
    const trimmed = this.token.trim();
    if (trimmed) {
      this.dialogRef.close(trimmed);
    }
  }
}
