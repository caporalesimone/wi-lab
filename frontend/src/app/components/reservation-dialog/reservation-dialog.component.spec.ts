/**
 * Unit tests for the reservation dialog's selection logic.
 *
 * The dialog stopped being a thin form when it gained the capability/device modes: it now
 * decides what the request payload contains and whether Reserve is enabled at all. That is
 * the first logic in this frontend worth testing directly.
 *
 * Run with `npm test` (Karma + Jasmine; set CHROME_BIN, or pass
 * `--browsers=ChromeHeadlessCI --watch=false` for a headless run).
 *
 * The component is instantiated directly rather than through TestBed, so these tests need
 * only a test runner and no Angular testing harness.
 */

import { FormBuilder } from '@angular/forms';
import { NetworkFormDialogComponent } from '../network-form-dialog/network-form-dialog.component';

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
  });

  describe('payload', () => {
    it('always sends required_capabilities, empty meaning "any device"', () => {
      const { component, closed } = makeDialog();
      component.onSubmit();
      expect(closed[0]).toEqual({ duration_seconds: 3600, required_capabilities: [] });
    });

    it('sends the selected capabilities and nothing else to choose a device', () => {
      const { component, closed } = makeDialog();
      component.toggleCapability('5ghz', true);
      component.onSubmit();
      expect(closed[0]).toEqual({ duration_seconds: 3600, required_capabilities: ['5ghz'] });
    });

    it('still produces duration_seconds 0 for an unlimited reservation', () => {
      const { component, closed } = makeDialog();
      component.form.get('unlimited')!.setValue(true);
      component.onUnlimitedChange();
      component.onSubmit();
      expect(closed[0]).toEqual({ duration_seconds: 0, required_capabilities: [] });
    });
  });

  describe('canSubmit', () => {
    it('is false when no free device matches', () => {
      const { component } = makeDialog({
        devices: DEVICES.map(d => ({ ...d, reserved: true }))
      });
      expect(component.canSubmit).toBe(false);
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

describe('NetworkFormDialogComponent.bandsFor', () => {
  it('offers dual only when the device declares both bands', () => {
    expect(NetworkFormDialogComponent.bandsFor(['2.4ghz', '5ghz'])).toEqual(['2.4ghz', '5ghz', 'dual']);
  });

  it('limits a single-band device to that band', () => {
    expect(NetworkFormDialogComponent.bandsFor(['2.4ghz'])).toEqual(['2.4ghz']);
    expect(NetworkFormDialogComponent.bandsFor(['5ghz'])).toEqual(['5ghz']);
  });
});
