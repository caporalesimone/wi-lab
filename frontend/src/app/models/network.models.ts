export type RecoveryState = 'recovering' | 'unavailable';
export type RuntimeState = 'restoring_ap' | 'restoring_dhcp' | 'dhcp_failed';

export type ChannelWidth = 20 | 40 | 80;
export type WifiGeneration = 4 | 5 | 6;

/** What an antenna accepts on a create (GET /status, networks[].capabilities). */
export interface AntennaCapabilities {
  encryptions: string[];
  channel_widths: Record<string, ChannelWidth[]>;
  wifi_generations: Record<string, WifiGeneration[]>;
}

export interface InterfaceInfo {
  display_name: string;
  interface: string;
  reserved: boolean;
  reservation_remaining_seconds: number | null;
  recovery_state?: RecoveryState;
  runtime_state?: RuntimeState;
  capabilities?: AntennaCapabilities;
}

export interface ReservationPolicy {
  min_seconds: number;
  max_seconds: number;
  allow_unlimited: boolean;
}

export interface StatusResponse {
  version: string;
  status: string;
  networks: InterfaceInfo[];
  active_networks: number;
  reservation_policy: ReservationPolicy;
  checks: {
    dnsmasq: { running: boolean; instances: number };
    iptables_nat: { configured: boolean; errors: string[] };
    upstream_interface: { name: string; up: boolean; has_ip: boolean; reachable: boolean };
  };
}

export interface ReservationRequest {
  duration_seconds: number;
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
  reservation_invalidated?: boolean;
}

export interface NoDeviceAvailableError extends ApiErrorDetail {
  next_available_at: string | null;
  next_available_in: number | null;
}
