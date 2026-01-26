import { Component, Inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { MatDialogRef, MAT_DIALOG_DATA, MatDialogModule } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { NetworkCreateRequest } from '../../models/network.models';

@Component({
  selector: 'app-network-form-dialog',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatCheckboxModule,
    MatButtonModule,
    MatIconModule
  ],
  templateUrl: './network-form-dialog.component.html',
  styleUrl: './network-form-dialog.component.scss'
})
export class NetworkFormDialogComponent {
  form: FormGroup;
  bands = ['2.4ghz', '5ghz', 'dual'];
  encryptionTypes = ['open', 'wpa', 'wpa2', 'wpa3', 'wpa2-wpa3'];
  txPowerLevels = [1, 2, 3, 4];

  constructor(
    private formBuilder: FormBuilder,
    private dialogRef: MatDialogRef<NetworkFormDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: { netId: string }
  ) {
    this.form = this.formBuilder.group({
      ssid: ['test1', [Validators.required, Validators.maxLength(32)]],
      channel: [6, [Validators.required, Validators.min(1), Validators.max(165)]],
      band: ['2.4ghz', Validators.required],
      encryption: ['wpa2', Validators.required],
      password: ['12345678', [Validators.minLength(8), Validators.maxLength(63)]],
      hidden: [false],
      timeout: [3600, [Validators.min(60), Validators.max(86400)]],
      internet_enabled: [true],
      tx_power_level: [4, [Validators.required, Validators.min(1), Validators.max(4)]]
    });

    // Update validators based on encryption type
    this.form.get('encryption')?.valueChanges.subscribe(encryption => {
      const passwordControl = this.form.get('password');
      if (encryption === 'open') {
        passwordControl?.clearValidators();
      } else {
        passwordControl?.setValidators([Validators.required, Validators.minLength(8), Validators.maxLength(63)]);
      }
      passwordControl?.updateValueAndValidity();
    });

    // Update channel validators based on band
    this.form.get('band')?.valueChanges.subscribe(band => {
      const channelControl = this.form.get('channel');
      if (band === '2.4ghz') {
        channelControl?.setValidators([Validators.required, Validators.min(1), Validators.max(14)]);
        if ((channelControl?.value || 0) > 14) {
          channelControl?.setValue(6);
        }
      } else if (band === '5ghz') {
        channelControl?.setValidators([Validators.required, Validators.min(36), Validators.max(165)]);
        if ((channelControl?.value || 0) < 36) {
          channelControl?.setValue(36);
        }
      } else {
        channelControl?.setValidators([Validators.required, Validators.min(1), Validators.max(165)]);
      }
      channelControl?.updateValueAndValidity();
    });
  }

  public onSubmit() {
    if (this.form.valid) {
      const value = this.form.value;
      const request: NetworkCreateRequest = {
        ssid: value.ssid,
        channel: value.channel,
        band: value.band,
        encryption: value.encryption,
        password: value.encryption !== 'open' ? value.password : undefined,
        hidden: value.hidden,
        timeout: value.timeout,
        internet_enabled: value.internet_enabled,
        tx_power_level: value.tx_power_level
      };
      this.dialogRef.close(request);
    }
  }

  public onCancel() {
    this.dialogRef.close();
  }
}
