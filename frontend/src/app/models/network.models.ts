export interface InterfaceInfo {
  net_id: string;
  interface: string;
}

export interface StatusResponse {
  version: string;
  status: string;
  networks: InterfaceInfo[];
  active_networks: number;
  checks: {
    dnsmasq: { running: boolean; instances: number };
    iptables_nat: { configured: boolean; errors: string[] };
    upstream_interface: { name: string; up: boolean; has_ip: boolean; reachable: boolean };
  };
}

export interface NetworkStatus {
  net_id: string;
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
  tx_power_level?: number;
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
  timeout?: number;
  internet_enabled?: boolean;
  tx_power_level: number;
}

export interface ClientInfo {
  mac: string;
  ip: string;
}

export interface ClientsResponse {
  net_id: string;
  clients: ClientInfo[];
}
