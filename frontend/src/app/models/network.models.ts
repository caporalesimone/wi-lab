export type RecoveryState = 'recovering' | 'unavailable';
export type RuntimeState =
  'starting' | 'start_failed' |
  'restoring_ap' | 'restoring_dhcp' | 'dhcp_failed' | 'restore_failed' | 'stop_failed';

/** Why an asynchronous create failed (runtime_state start_failed). */
export interface StartError {
  code: number;
  reason: string;
  message: string;
  stage?: string | null;
}

/** Watchdog repairs over the whole reservation; the counters never decrease. */
export interface Restarts {
  ap: number;
  dhcp: number;
  last_at: string | null;
  last_reason: string | null;
}

export type ChannelWidth = 20 | 40 | 80;
export type WifiGeneration = 4 | 5 | 6;

export type Band = '2.4ghz' | '5ghz';

/** A channel a create can use on an antenna, with the widths it can be the primary of. */
export interface ChannelOption {
  channel: number;
  frequency_mhz: number;
  max_power_dbm: number;
  dfs: boolean;
  channel_widths: ChannelWidth[];
}

export interface BandOptions {
  wifi_generations: { wifi_generation: WifiGeneration; channel_widths: ChannelWidth[] }[];
  channels: ChannelOption[];
}

/** GET /antennas/{interface}: what a network on the antenna can use. */
export interface AntennaDetails {
  display_name: string;
  interface: string;
  device: { bus: string; address: string; driver: string | null } | null;
  encryptions: string[];
  bands: Record<Band, BandOptions>;
}

/** The same reservation object as in the reservation and network answers. */
export interface StatusReservation {
  expires_at: string | null;
  expires_in: number | null;
}

export interface InterfaceInfo {
  display_name: string;
  interface: string;
  /** null: no reservation holds the antenna. Unlimited: both fields null. */
  reservation: StatusReservation | null;
  network_active: boolean;
  recovery_state?: RecoveryState;
  runtime_state?: RuntimeState;
}

export interface ReservationPolicy {
  min_seconds: number;
  max_seconds: number;
  allow_unlimited: boolean;
}

export interface ServiceState {
  /** `degraded`: at least one entry in `degraded_reasons`. */
  health: 'good' | 'degraded';
  /** Antennas a reservation would get now. */
  free_antennas: number;
  /** Why the service is degraded; empty when health is good. */
  degraded_reasons: { code: string; interface: string | null; message: string }[];
  /** Security updates installed on the host that need a restart; never done automatically. */
  restart_required: RestartRequired | null;
}

export interface StatusResponse {
  version: string;
  service: ServiceState;
  antennas: InterfaceInfo[];
  reservation_policy: ReservationPolicy;
}

export interface RestartRequired {
  /** A library Wi-Lab loaded was replaced: `systemctl restart wi-lab`. */
  service: boolean;
  /** An update asks for a reboot of the host. */
  system: boolean;
  since: string | null;
  message: string;
}

export interface ReservationRequest {
  duration_seconds: number;
  /** Reserve this antenna only (from antennas[] of GET /status); omitted: the first free one. */
  interface?: string | null;
}

export interface ReservationResponse {
  reservation_id: string;
  display_name: string;
  interface: string;
  expires_at: string | null;
  expires_in: number | null;
}

/** GET .../network: sections are null while the network is not running. */
export interface NetworkStatus {
  interface: string;
  active: boolean;
  runtime_state?: RuntimeState | null;
  reservation: {
    expires_at: string | null;
    expires_in: number | null;
  };
  restarts?: Restarts;
  error?: StartError | null;
  radio: {
    band: string;
    channel: number;
    channel_width: { requested: ChannelWidth; reported: number | null };
    wifi_generation: WifiGeneration;
    tx_power?: {
      requested_level: number;
      reported_level?: number | null;
      reported_dbm?: number | null;
    } | null;
  } | null;
  wifi: {
    ssid: string;
    hidden: boolean;
    security: { encryption: string; password: string | null };
  } | null;
  ip: {
    subnet: string;
    gateway: string | null;
    dhcp_range: { start: string; end: string } | null;
    dns_server: string | null;
  } | null;
  internet: { enabled: boolean } | null;
  captive_portal: { enabled: boolean; url: string | null } | null;
  clients: ClientInfo[] | null;
}

/** POST .../network body: only radio and wifi are required. */
export interface NetworkCreateRequest {
  radio: {
    band: string;
    channel: number;
    channel_width?: ChannelWidth;
    wifi_generation?: WifiGeneration;
    tx_power_level: number;
  };
  wifi: {
    ssid: string;
    hidden?: boolean;
    security: { encryption: string; password?: string };
  };
  internet?: { enabled?: boolean };
  captive_portal?: { enabled?: boolean };
}

export interface ClientInfo {
  mac: string;
  ip: string;
  captive_authorized?: boolean;
}

export interface ApiErrorDetail {
  code: number;
  reason: string;
  message?: string;
}

export interface NoDeviceAvailableError extends ApiErrorDetail {
  next_available_at: string | null;
  next_available_in: number | null;
}
