/**
 * A capability id, e.g. '2.4ghz'.
 *
 * Deliberately a string alias and not a '2.4ghz' | '5ghz' union: the backend owns the
 * registry, and a union would force a frontend release every time it gains an entry,
 * defeating the point of the server-provided catalogue.
 */
export type CapabilityId = string;

export interface CapabilityInfo {
  id: CapabilityId;
  /** Human label owned by the backend, so a new capability needs no frontend change. */
  label: string;
  /** 'radio' | 'policy' | future kinds. Used to group the picker. */
  kind: string;
  total_devices: number;
  available_devices: number;
}

export interface InterfaceInfo {
  display_name: string;
  interface: string;
  reserved: boolean;
  reservation_remaining_seconds: number | null;
  /** Enabled capabilities only. Absent on responses from a pre-3.1 backend. */
  capabilities?: CapabilityId[];
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
  /** Capabilities at least one device provides, in backend registry order. */
  capabilities_catalogue?: CapabilityInfo[];
  checks: {
    dnsmasq: { running: boolean; instances: number };
    iptables_nat: { configured: boolean; errors: string[] };
    upstream_interface: { name: string; up: boolean; has_ip: boolean; reachable: boolean };
  };
}

export interface ReservationRequest {
  duration_seconds: number;
  /** Capabilities the assigned device must provide. Omitted or empty means "any device". */
  required_capabilities?: CapabilityId[];
  /** Pin a specific device by interface name. Omitted means "let Wi-Lab choose". */
  interface?: string;
}

export interface ReservationResponse {
  reservation_id: string;
  display_name: string;
  interface: string;
  expires_at: string | null;
  expires_in: number | null;
  /** What the assigned device provides. Absent on reservations restored from a
   *  localStorage entry written by an older frontend. */
  capabilities?: CapabilityId[];
}

export interface NetworkStatus {
  interface: string;
  active: boolean;
  ssid?: string;
  channel?: number;
  password?: string;
  encryption?: string;
  band?: string;
  hidden?: boolean;
  subnet?: string;
  internet_enabled: boolean;
  tx_power?: {
    requested_level: number;
    reported_level?: number;
    reported_dbm?: number;
  };
  expires_at?: string | null;
  expires_in?: number | null;
  dhcp?: {
    interface: string;
    subnet: string;
    gateway: string;
    config_file: string;
    pid_file: string;
    lease_file: string;
    network_addr: string;
    dhcp_range: string;
  };
  clients_connected?: number;
  clients?: ClientInfo[];
}

export interface NetworkCreateRequest {
  ssid: string;
  channel: number;
  password?: string;
  encryption: string;
  band: string;
  hidden?: boolean;
  internet_enabled?: boolean;
  tx_power_level: number;
}

export interface ClientInfo {
  mac: string;
  ip: string;
}

export interface NoDeviceAvailableError {
  detail: string;
  /** Null when every busy device is held by an unlimited reservation: no scheduled release. */
  next_available_at: string | null;
  next_available_in: number | null;
}
