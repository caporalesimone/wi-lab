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
import { CapabilityId, NetworkCreateRequest } from '../../models/network.models';

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
  /**
   * Bands the reserved device may actually operate, derived from its declared
   * capabilities. Offering a band the antenna cannot serve turns a clear pre-submit
   * choice into a confusing hostapd failure.
   */
  bands: string[];
  encryptionTypes = ['open', 'wpa', 'wpa2', 'wpa3', 'wpa2-wpa3'];
  txPowerLevels = [1, 2, 3, 4];

  constructor(
    private formBuilder: FormBuilder,
    private dialogRef: MatDialogRef<NetworkFormDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: { netId: string; capabilities?: CapabilityId[] }
  ) {
    // Generate dynamic SSID based on AP ID (e.g., "test-network-ap-01")
    const defaultSsid = `test-network-${this.data.netId}`;
    this.bands = NetworkFormDialogComponent.bandsFor(this.data.capabilities);
    // Not the literal '2.4ghz': that would be invalid on a 5 GHz-only device.
    const defaultBand = this.bands[0] ?? '2.4ghz';

    this.form = this.formBuilder.group({
      ssid: [defaultSsid, [Validators.required, Validators.maxLength(32)]],
      channel: [defaultBand === '5ghz' ? 36 : 6, [Validators.required, Validators.min(1), Validators.max(165)]],
      band: [defaultBand, Validators.required],
      encryption: ['wpa2', Validators.required],
      password: ['12345678', [Validators.minLength(8), Validators.maxLength(63)]],
      hidden: [false],
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
        internet_enabled: value.internet_enabled,
        tx_power_level: value.tx_power_level
      };
      this.dialogRef.close(request);
    }
  }

  public onCancel() {
    this.dialogRef.close();
  }

  /**
   * Map declared capabilities onto selectable bands.
   *
   * 'dual' is offered only when the device declares both, since hostapd would otherwise
   * be asked for a band the radio may not use. An empty or absent capability list falls
   * back to the full set, so a pre-3.1 backend keeps working.
   */
  public static bandsFor(capabilities?: CapabilityId[]): string[] {
    const caps = capabilities ?? [];
    if (caps.length === 0) {
      return ['2.4ghz', '5ghz', 'dual'];
    }
    const bands = caps.filter(c => c === '2.4ghz' || c === '5ghz');
    if (bands.includes('2.4ghz') && bands.includes('5ghz')) {
      bands.push('dual');
    }
    return bands;
  }
}
