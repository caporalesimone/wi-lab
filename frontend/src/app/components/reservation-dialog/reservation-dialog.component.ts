import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { MatDialogRef, MatDialogModule } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { ReservationRequest } from '../../models/network.models';

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
    MatIconModule
  ],
  templateUrl: './reservation-dialog.component.html',
  styleUrl: './reservation-dialog.component.scss'
})
export class ReservationDialogComponent {
  form: FormGroup;

  constructor(
    private formBuilder: FormBuilder,
    private dialogRef: MatDialogRef<ReservationDialogComponent>
  ) {
    this.form = this.formBuilder.group({
      duration_seconds: [3600, [Validators.required, Validators.min(60), Validators.max(86400)]]
    });
  }

  public get durationMinutes(): number {
    return Math.floor((this.form.get('duration_seconds')?.value || 0) / 60);
  }

  public onSubmit(): void {
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
