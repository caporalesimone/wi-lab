export interface InterfaceInfo {
  net_id: string;
  interface: string;
}

export interface InterfacesResponse {
  version: string;
  networks: InterfaceInfo[];
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
