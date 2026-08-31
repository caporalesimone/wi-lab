/**
 * Unit tests for the reservation dialog's selection logic.
 *
 * The dialog stopped being a thin form when it gained the capability/device modes: it now
 * decides what the request payload contains and whether Reserve is enabled at all. That is
 * the first logic in this frontend worth testing directly.
 *
 * NOTE — not runnable yet. This project has no Angular test infrastructure: angular.json
 * declares no `test` target, there is no tsconfig.spec.json, and karma/jasmine are absent
 * from package.json. Adding them means changing package.json, and the Docker build runs
 * `npm ci`, which fails if package-lock.json is not regenerated in the same commit. Wiring
 * this up is therefore listed as bench work in
 * TODOs/device-capabilities.md §12.9.
 *
 * The component is instantiated directly rather than through TestBed, so these tests need
 * only a test runner and no Angular testing harness.
 */

import { FormBuilder } from '@angular/forms';

import { CapabilityInfo, InterfaceInfo } from '../../models/network.models';
import { ReservationDialogComponent, ReservationDialogData } from './reservation-dialog.component';

const CATALOGUE: CapabilityInfo[] = [
  { id: '2.4ghz', label: '2.4 GHz', kind: 'radio', total_devices: 3, available_devices: 3 },
  { id: '5ghz', label: '5 GHz', kind: 'radio', total_devices: 2, available_devices: 2 }
];

const DEVICES: InterfaceInfo[] = [
  {
    display_name: 'bench-antenna-1', interface: 'wls16', reserved: false,
    reservation_remaining_seconds: null, capabilities: ['2.4ghz', '5ghz']
  },
  {
    display_name: 'bench-antenna-2', interface: 'wls17', reserved: false,
    reservation_remaining_seconds: null, capabilities: ['2.4ghz']
  },
  {
    display_name: 'bench-antenna-3', interface: 'wls18', reserved: true,
    reservation_remaining_seconds: 900, capabilities: ['2.4ghz', '5ghz']
  }
];

function makeDialog(overrides: Partial<ReservationDialogData> = {}) {
  const closed: unknown[] = [];
  const dialogRef = { close: (v?: unknown) => closed.push(v) } as never;
  const data: ReservationDialogData = {
    allowUnlimited: true,
    minSeconds: 60,
    maxSeconds: 86400,
    capabilities: CATALOGUE,
    devices: DEVICES,
    ...overrides
  };
  const component = new ReservationDialogComponent(new FormBuilder(), dialogRef, data);
  return { component, closed };
}

describe('ReservationDialogComponent', () => {
  describe('matchingDeviceCount', () => {
    it('counts every free device when nothing is selected', () => {
      const { component } = makeDialog();
      expect(component.matchingDeviceCount).toBe(2); // wls18 is reserved
    });

    it('counts the free devices offering one selected capability', () => {
      const { component } = makeDialog();
      component.toggleCapability('2.4ghz', true);
      expect(component.matchingDeviceCount).toBe(2);
    });

    it('narrows as capabilities are added', () => {
      const { component } = makeDialog();
      component.toggleCapability('5ghz', true);
      expect(component.matchingDeviceCount).toBe(1); // only wls16 is free and dual-band
    });

    it('is zero when no free device satisfies the selection', () => {
      const { component } = makeDialog({
        devices: DEVICES.map(d => ({ ...d, reserved: true }))
      });
      component.toggleCapability('2.4ghz', true);
      expect(component.matchingDeviceCount).toBe(0);
    });

    it('treats a device with no declared capabilities as matching nothing specific', () => {
      const { component } = makeDialog({
        devices: [{ ...DEVICES[0], capabilities: undefined }]
      });
      expect(component.matchingDeviceCount).toBe(1);
      component.toggleCapability('5ghz', true);
      expect(component.matchingDeviceCount).toBe(0);
    });
  });

  describe('mode switching', () => {
    it('clears the device selection when returning to capability mode', () => {
      const { component } = makeDialog();
      component.form.get('mode')!.setValue('device');
      component.form.get('selectedInterface')!.setValue('wls16');
      component.form.get('mode')!.setValue('capability');
      component.onModeChange();
      expect(component.selectedInterface).toBeNull();
    });

    it('clears the capability selection when switching to device mode', () => {
      const { component } = makeDialog();
      component.toggleCapability('5ghz', true);
      component.form.get('mode')!.setValue('device');
      component.onModeChange();
      expect(component.selectedCapabilities).toEqual([]);
    });
  });

  describe('payload', () => {
    it('omits both fields when nothing is required', () => {
      const { component, closed } = makeDialog();
      component.onSubmit();
      expect(closed[0]).toEqual({ duration_seconds: 3600 });
    });

    it('sends only required_capabilities in capability mode', () => {
      const { component, closed } = makeDialog();
      component.toggleCapability('5ghz', true);
      component.onSubmit();
      expect(closed[0]).toEqual({ duration_seconds: 3600, required_capabilities: ['5ghz'] });
    });

    it('sends only interface in device mode', () => {
      const { component, closed } = makeDialog();
      component.form.get('mode')!.setValue('device');
      component.onModeChange();
      component.form.get('selectedInterface')!.setValue('wls17');
      component.onSubmit();
      expect(closed[0]).toEqual({ duration_seconds: 3600, interface: 'wls17' });
    });

    it('still produces duration_seconds 0 for an unlimited reservation', () => {
      const { component, closed } = makeDialog();
      component.form.get('unlimited')!.setValue(true);
      component.onUnlimitedChange();
      component.onSubmit();
      expect(closed[0]).toEqual({ duration_seconds: 0 });
    });
  });

  describe('canSubmit', () => {
    it('is false when no free device matches', () => {
      const { component } = makeDialog({
        devices: DEVICES.map(d => ({ ...d, reserved: true }))
      });
      expect(component.canSubmit).toBe(false);
    });

    it('is false in device mode until a device is picked', () => {
      const { component } = makeDialog();
      component.form.get('mode')!.setValue('device');
      component.onModeChange();
      expect(component.canSubmit).toBe(false);
      component.form.get('selectedInterface')!.setValue('wls16');
      expect(component.canSubmit).toBe(true);
    });

    it('is false when the duration is out of policy bounds', () => {
      const { component } = makeDialog();
      component.form.get('duration_seconds')!.setValue(5);
      expect(component.canSubmit).toBe(false);
    });
  });

  describe('capability grouping', () => {
    it('groups by kind and hides the heading when there is only one group', () => {
      const { component } = makeDialog();
      expect(component.capabilityGroups.length).toBe(1);
      expect(component.capabilityGroups[0].kind).toBe('radio');
      expect(component.showGroupHeadings).toBe(false);
    });

    it('shows headings once a second kind exists', () => {
      const { component } = makeDialog({
        capabilities: [
          ...CATALOGUE,
          {
            id: 'change-ssid', label: 'SSID change', kind: 'policy',
            total_devices: 1, available_devices: 1
          }
        ]
      });
      expect(component.capabilityGroups.map(g => g.kind)).toEqual(['radio', 'policy']);
      expect(component.showGroupHeadings).toBe(true);
    });
  });
});
