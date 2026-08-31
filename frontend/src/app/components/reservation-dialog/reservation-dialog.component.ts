import { Component, Inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { MatDialogRef, MatDialogModule, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatIconModule } from '@angular/material/icon';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatRadioModule } from '@angular/material/radio';
import { MatChipsModule } from '@angular/material/chips';
import {
  CapabilityId,
  CapabilityInfo,
  InterfaceInfo,
  ReservationRequest
} from '../../models/network.models';

export type SelectionMode = 'capability' | 'device';

export interface ReservationDialogData {
  allowUnlimited: boolean;
  minSeconds: number;
  maxSeconds: number;
  /** From status.capabilities_catalogue — labels and counts are owned by the backend. */
  capabilities: CapabilityInfo[];
  /** From status.networks — used for the device list and the live match count. */
  devices: InterfaceInfo[];
}

/** A capability group as rendered in the picker, e.g. all the 'radio' ones. */
export interface CapabilityGroup {
  kind: string;
  label: string;
  items: CapabilityInfo[];
}

const KIND_LABELS: Record<string, string> = {
  radio: 'Radio',
  policy: 'Policy'
};

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
    MatButtonToggleModule,
    MatIconModule,
    MatCheckboxModule,
    MatRadioModule,
    MatChipsModule
  ],
  templateUrl: './reservation-dialog.component.html',
  styleUrl: './reservation-dialog.component.scss'
})
export class ReservationDialogComponent {
  form: FormGroup;
  allowUnlimited: boolean;
  minSeconds: number;
  maxSeconds: number;
  capabilities: CapabilityInfo[];
  devices: InterfaceInfo[];

  constructor(
    private formBuilder: FormBuilder,
    private dialogRef: MatDialogRef<ReservationDialogComponent>,
    @Inject(MAT_DIALOG_DATA) data: ReservationDialogData | null
  ) {
    this.allowUnlimited = data?.allowUnlimited ?? false;
    this.minSeconds = data?.minSeconds ?? 60;
    this.maxSeconds = data?.maxSeconds ?? 86400;
    this.capabilities = data?.capabilities ?? [];
    this.devices = data?.devices ?? [];
    this.form = this.formBuilder.group({
      mode: ['capability' as SelectionMode],
      selectedCapabilities: [[] as CapabilityId[]],
      selectedInterface: [null as string | null],
      unlimited: [false],
      duration_seconds: [3600, [Validators.required, Validators.min(this.minSeconds), Validators.max(this.maxSeconds)]]
    });
  }

  // ---- Selection mode ----

  public get mode(): SelectionMode {
    return this.form.get('mode')?.value as SelectionMode;
  }

  /**
   * Clear the other mode's control on every switch, so the emitted request can never
   * carry both required_capabilities and interface.
   */
  public onModeChange(): void {
    if (this.mode === 'capability') {
      this.form.get('selectedInterface')?.setValue(null);
    } else {
      this.form.get('selectedCapabilities')?.setValue([]);
    }
  }

  // ---- Capability picker ----

  /**
   * Capabilities grouped by kind. Only populated groups are returned, so the template
   * never renders an empty heading.
   */
  public get capabilityGroups(): CapabilityGroup[] {
    const order: string[] = [];
    const byKind = new Map<string, CapabilityInfo[]>();
    for (const cap of this.capabilities) {
      if (!byKind.has(cap.kind)) {
        byKind.set(cap.kind, []);
        order.push(cap.kind);
      }
      byKind.get(cap.kind)!.push(cap);
    }
    return order.map(kind => ({
      kind,
      label: KIND_LABELS[kind] ?? kind,
      items: byKind.get(kind)!
    }));
  }

  /** With a single group the heading adds nothing, so it is hidden. */
  public get showGroupHeadings(): boolean {
    return this.capabilityGroups.length > 1;
  }

  public get selectedCapabilities(): CapabilityId[] {
    return (this.form.get('selectedCapabilities')?.value ?? []) as CapabilityId[];
  }

  public isCapabilitySelected(id: CapabilityId): boolean {
    return this.selectedCapabilities.includes(id);
  }

  public toggleCapability(id: CapabilityId, checked: boolean): void {
    const current = this.selectedCapabilities.filter(c => c !== id);
    this.form.get('selectedCapabilities')?.setValue(checked ? [...current, id] : current);
  }

  /**
   * How many free devices satisfy the current selection.
   *
   * Feasibility only: this deliberately does NOT predict which device will be assigned.
   * Reimplementing the backend's minimality tie-break here would create a second copy of
   * the allocation rule, and the two would drift.
   */
  public get matchingDeviceCount(): number {
    const required = this.selectedCapabilities;
    return this.devices.filter(
      d => !d.reserved && required.every(c => (d.capabilities ?? []).includes(c))
    ).length;
  }

  public get matchSummary(): string {
    const n = this.matchingDeviceCount;
    if (n === 0) {
      return this.selectedCapabilities.length
        ? 'No free device provides all the selected capabilities'
        : 'No device is currently free';
    }
    return `${n} device${n === 1 ? '' : 's'} match${n === 1 ? 'es' : ''} your selection`;
  }

  // ---- Device picker ----

  public capabilitiesOf(device: InterfaceInfo): CapabilityId[] {
    return device.capabilities ?? [];
  }

  public labelFor(id: CapabilityId): string {
    return this.capabilities.find(c => c.id === id)?.label ?? id;
  }

  public get selectedInterface(): string | null {
    return this.form.get('selectedInterface')?.value ?? null;
  }

  // ---- Duration (unchanged behaviour) ----

  public get durationMinutes(): number {
    return Math.floor((this.form.get('duration_seconds')?.value || 0) / 60);
  }

  public formatDuration(totalSeconds: number): string {
    const h = Math.floor(totalSeconds / 3600);
    const m = Math.floor((totalSeconds % 3600) / 60);
    const s = totalSeconds % 60;
    const pad = (n: number) => n.toString().padStart(2, '0');
    return `${pad(h)}h ${pad(m)}m ${pad(s)}s`;
  }

  public get currentDurationFormatted(): string {
    const val = this.form.get('duration_seconds')?.value || 0;
    return this.formatDuration(Math.max(0, Math.floor(val)));
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

  // ---- Submit ----

  public get canSubmit(): boolean {
    const durationOk = this.isUnlimited || this.form.get('duration_seconds')!.valid;
    if (!durationOk) {
      return false;
    }
    return this.mode === 'capability'
      ? this.matchingDeviceCount > 0
      : this.selectedInterface !== null;
  }

  public onSubmit(): void {
    if (!this.canSubmit) {
      return;
    }
    const request: ReservationRequest = {
      duration_seconds: this.isUnlimited ? 0 : this.form.get('duration_seconds')!.value
    };
    // Emit only the field belonging to the active mode. An empty capability list is
    // omitted entirely: it means "no requirement", which is what leaving the field out
    // already means to the API.
    if (this.mode === 'capability') {
      if (this.selectedCapabilities.length) {
        request.required_capabilities = this.selectedCapabilities;
      }
    } else if (this.selectedInterface) {
      request.interface = this.selectedInterface;
    }
    this.dialogRef.close(request);
  }

  public onCancel(): void {
    this.dialogRef.close();
  }
}
