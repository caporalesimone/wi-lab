import { Component, Inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { MatDialogRef, MatDialogModule, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { ReservationRequest } from '../../models/network.models';

export interface ReservationDialogData {
  allowUnlimited: boolean;
}

@Component({
  selector: 'app-reservation-dialog',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
    MatCheckboxModule
  ],
  templateUrl: './reservation-dialog.component.html',
  styleUrl: './reservation-dialog.component.scss'
})
export class ReservationDialogComponent {
  form: FormGroup;
  allowUnlimited: boolean;

  constructor(
    private formBuilder: FormBuilder,
    private dialogRef: MatDialogRef<ReservationDialogComponent>,
    @Inject(MAT_DIALOG_DATA) data: ReservationDialogData | null
  ) {
    this.allowUnlimited = data?.allowUnlimited ?? false;
    this.form = this.formBuilder.group({
      unlimited: [false],
      duration_seconds: [3600, [Validators.required, Validators.min(10), Validators.max(86400)]]
    });
  }

  public get durationMinutes(): number {
    return Math.floor((this.form.get('duration_seconds')?.value || 0) / 60);
  }

  public get isUnlimited(): boolean {
    return this.form.get('unlimited')?.value === true;
  }

  public onUnlimitedChange(): void {
    const ctrl = this.form.get('duration_seconds')!;
    if (this.isUnlimited) {
      ctrl.disable();
    } else {
      ctrl.enable();
    }
  }

  public onSubmit(): void {
    if (this.isUnlimited) {
      this.dialogRef.close({ duration_seconds: 0 } as ReservationRequest);
      return;
    }
    if (this.form.valid) {
      const request: ReservationRequest = {
        duration_seconds: this.form.value.duration_seconds
      };
      this.dialogRef.close(request);
    }
  }

  public onCancel(): void {
    this.dialogRef.close();
  }
}
