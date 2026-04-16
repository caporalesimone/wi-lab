export interface InterfaceInfo {
  display_name: string;
  interface: string;
  reserved: boolean;
  reservation_remaining_seconds: number | null;
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
  expires_at?: string;
  expires_in?: number;
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
  next_available_at: string;
  next_available_in: number;
}
