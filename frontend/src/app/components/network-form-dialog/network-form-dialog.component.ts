import { Component, Inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { MatDialogRef, MAT_DIALOG_DATA, MatDialogModule } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
  AntennaDetails,
  Band,
  BandOptions,
  ChannelOption,
  ChannelWidth,
  NetworkCreateRequest,
  WifiGeneration,
} from '../../models/network.models';

export const ENCRYPTION_LABELS: Record<string, string> = {
  'open': 'Open',
  'wpa1': 'WPA1 (TKIP, legacy - insecure)',
  'wpa2': 'WPA2',
  'wpa3': 'WPA3',
  'wpa2-wpa3': 'WPA2/WPA3 mixed',
};

export const GENERATION_LABELS: Record<number, string> = {
  4: 'Wi-Fi 4 (802.11n)',
  5: 'Wi-Fi 5 (802.11ac)',
  6: 'Wi-Fi 6 (802.11ax)',
};

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
    MatSlideToggleModule,
    MatButtonModule,
    MatIconModule,
    MatTooltipModule
  ],
  templateUrl: './network-form-dialog.component.html',
  styleUrl: './network-form-dialog.component.scss'
})
export class NetworkFormDialogComponent {
  form: FormGroup;
  bands: Band[];
  encryptionTypes: string[];
  txPowerLevels = [1, 2, 3, 4];
  encryptionLabels = ENCRYPTION_LABELS;
  generationLabels = GENERATION_LABELS;

  constructor(
    private formBuilder: FormBuilder,
    private dialogRef: MatDialogRef<NetworkFormDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: {
      netId: string; captivePortal?: boolean; antenna: AntennaDetails;
    }
  ) {
    // Every list comes from GET /antennas/{interface}: band, then generation,
    // then width, then a channel usable at that width.
    this.encryptionTypes = this.data.antenna.encryptions.filter(enc => enc in ENCRYPTION_LABELS);
    this.bands = (['2.4ghz', '5ghz'] as Band[]).filter(b => this.data.antenna.bands[b].channels.length > 0);
    const band = this.bands[0] ?? '2.4ghz';
    const firstChannels = this.data.antenna.bands[band].channels.map(c => c.channel);
    // Generate dynamic SSID based on AP ID (e.g., "test-network-ap-01")
    const defaultSsid = `test-network-${this.data.netId}`;
    
    this.form = this.formBuilder.group({
      ssid: [defaultSsid, [Validators.required, Validators.maxLength(32)]],
      channel: [firstChannels.includes(6) ? 6 : firstChannels[0], Validators.required],
      band: [band, Validators.required],
      encryption: ['wpa2', Validators.required],
      password: ['12345678', [Validators.minLength(8), Validators.maxLength(63)]],
      hidden: [false],
      internet_enabled: [true],
      captive_portal: [this.data.captivePortal ?? false],
      tx_power_level: [4, [Validators.required, Validators.min(1), Validators.max(4)]],
      channel_width: [20 as ChannelWidth, Validators.required],
      wifi_generation: [4 as WifiGeneration, Validators.required]
    });

    // Keep generation, width and channel within what the antenna offers.
    for (const name of ['band', 'encryption', 'wifi_generation', 'channel_width']) {
      this.form.get(name)?.valueChanges.subscribe(() => setTimeout(() => this.fitMode()));
    }

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
  }

  private get bandOptions(): BandOptions {
    return this.data.antenna.bands[this.form.get('band')?.value as Band];
  }

  /** Wi-Fi generations offered for the selected band and encryption. */
  public get wifiGenerations(): WifiGeneration[] {
    if (this.form.get('encryption')?.value === 'wpa1') return [4];
    return this.bandOptions.wifi_generations.map(g => g.wifi_generation);
  }

  /** Channel widths offered for the selected band, encryption and generation. */
  public get channelWidths(): ChannelWidth[] {
    if (this.form.get('encryption')?.value === 'wpa1') return [20];
    const generation = this.form.get('wifi_generation')?.value;
    return this.bandOptions.wifi_generations.find(g => g.wifi_generation === generation)?.channel_widths ?? [20];
  }

  /** Channels of the selected band usable at the selected width. */
  public get channels(): ChannelOption[] {
    const width = this.form.get('channel_width')?.value;
    return this.bandOptions.channels.filter(c => c.channel_widths.includes(width));
  }

  public isDfs(channel: number): boolean {
    return this.bandOptions.channels.some(c => c.channel === channel && c.dfs);
  }

  public get mayFallBackTo20(): boolean {
    return this.form.get('band')?.value === '2.4ghz' && this.form.get('channel_width')?.value === 40;
  }

  private fitMode(): void {
    const generation = this.form.get('wifi_generation');
    if (!this.wifiGenerations.includes(generation?.value)) {
      generation?.setValue(4, { emitEvent: false });
    }
    const width = this.form.get('channel_width');
    if (!this.channelWidths.includes(width?.value)) {
      width?.setValue(20, { emitEvent: false });
    }
    const channel = this.form.get('channel');
    const usable = this.channels.map(c => c.channel);
    if (!usable.includes(channel?.value)) {
      channel?.setValue(usable[0] ?? null, { emitEvent: false });
    }
  }

  public onSubmit() {
    if (this.form.valid) {
      const value = this.form.value;
      const request: NetworkCreateRequest = {
        radio: {
          band: value.band,
          channel: value.channel,
          channel_width: value.channel_width,
          wifi_generation: value.wifi_generation,
          tx_power_level: value.tx_power_level
        },
        wifi: {
          ssid: value.ssid,
          hidden: value.hidden,
          security: {
            encryption: value.encryption,
            password: value.encryption !== 'open' ? value.password : undefined
          }
        },
        internet: { enabled: value.internet_enabled },
        captive_portal: { enabled: value.captive_portal }
      };
      this.dialogRef.close(request);
    }
  }

  public onCancel() {
    this.dialogRef.close();
  }
}
