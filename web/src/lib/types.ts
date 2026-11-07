export type DeviceStatus = "online" | "active" | "stale" | "disabled" | "unknown";

export interface Disk {
  device: string;
  mount: string;
  fstype: string;
  kind: string;
  total: number;
  used: number;
  free: number;
  percent: number;
}

export interface Cpu {
  name: string | null;
  cores: number | null;
  threads: number | null;
  mhz: number | null;
}

export interface Device {
  id: string;
  name: string;
  type: string | null;
  host: string | null;
  ipv4: string[];
  description: string | null;
  os: string | null;
  os_version: string | null;
  cpu: Cpu | null;
  ram_total: number | null;
  disks: Disk[] | null;
  status: DeviceStatus;
  status_detail: string | null;
  last_seen: string | null;
  organization: string | null;
  object: string | null;
  department: string | null;
  ou_path: string[];
  hierarchy_source: string | null;
  last_inventory_update: string | null;
  sources: string[];
  inventory_names: string[];
  is_local: boolean;
  domain: string | null;
  system: Record<string, string | null> | null;
  software_count: number | null;
}

export interface Source {
  kind: string;
  label: string;
  path: string;
  exists: boolean;
  updated: string | null;
  records: number;
  error: string | null;
}

export interface Metrics {
  ts: string;
  cpu: number;
  cpu_per_core: number[];
  ram: number;
  ram_used: number;
  ram_total: number;
  swap: number;
  swap_used: number;
  swap_total: number;
  disk: number | null;
  disk_mount: string | null;
  disks: Disk[];
  disk_read_bps: number | null;
  disk_write_bps: number | null;
  uptime_sec: number;
}

export interface HistoryPoint {
  ts: string;
  cpu: number;
  ram: number;
  disk: number | null;
  disk_read_bps: number | null;
  disk_write_bps: number | null;
}

export interface Task {
  id: string;
  ts: string;
  finished: string | null;
  description: string | null;
  model: string | null;
  origin: string;
  status: string;
  steps: number;
  actions: number;
  failed_actions: number;
  devices: string[];
  mutated: boolean | null;
  verified: boolean | null;
  result: string | null;
  error: string | null;
  failures: { ts: string; tool: string; host: string; result: string }[];
}

export interface Action {
  ts: string;
  task: string;
  host: string;
  tool: string;
  level: string;
  success: boolean;
  duration_ms: number | null;
  detail: string;
  result: string;
}

export interface EventItem {
  ts: string;
  type: string;
  error: boolean;
  summary: string;
  fields: Record<string, string>;
}

export interface AgentStatus {
  running: boolean;
  pid: number | null;
  version: string | null;
  started: string | null;
  last_alive: string | null;
  stopped_by_owner: boolean;
  control: {
    model: string | null;
    plan: string | null;
    limits: string | null;
    blocked: string | null;
    busy: boolean;
    tasks: { id: string; elapsed: string; steps: number; last: string; text: string }[];
    pending: { id: string; label: string; task_id: string }[];
  } | null;
  control_error: string | null;
}

export interface Overview {
  devices_total: number;
  device_status: Record<string, number>;
  os: { name: string; count: number }[];
  organizations: number;
  objects: number;
  departments: number;
  unassigned: number;
  local: { name: string | null; os: string | null; id: string | null };
  metrics: Metrics;
  today: { tasks: number; ok: number; failed: number; running: number; actions: number; recent: Task[] };
  agent: AgentStatus;
  sources: Source[];
}

export interface DeptNode {
  name: string | null;
  count: number;
  status: Record<string, number>;
  devices: { id: string; name: string; status: DeviceStatus; os: string | null }[];
}

export interface OrgNode {
  name: string | null;
  count: number;
  objects: { name: string | null; count: number; departments: DeptNode[] }[];
}

export interface LocalSystem {
  computer_name: string | null;
  domain: string | null;
  windows: {
    product: string | null;
    edition: string | null;
    release: string | null;
    build: string | null;
    installed: string | null;
    architecture: string | null;
    label: string | null;
  };
  cpu: Cpu;
  system: Record<string, string | null>;
  ram_total: number;
  disks: Disk[];
  ipv4: { interface: string; address: string }[];
  boot_time: string;
  software_count: number;
  collected_at: string;
}

export interface Software {
  name: string;
  version: string | null;
  publisher: string | null;
  installed: string | null;
  size_mb: number | null;
  scope: string;
  arch: string | null;
}

export interface Report {
  range: { start: string; end: string };
  tasks_total: number;
  tasks_ok: number;
  tasks_failed: number;
  success_rate: number | null;
  changes_made: number;
  changes_verified: number;
  actions_total: number;
  actions_failed: number;
  avg_action_ms: number | null;
  status: Record<string, number>;
  per_day: { day: string; ok: number; failed: number; running: number }[];
  top_devices: { name: string; count: number }[];
  top_tools: { name: string; count: number; failed: number }[];
  quota_events: number;
  agent_restarts: number;
  agent_crashes: number;
  inventory: {
    total: number;
    by_status: { name: string; count: number }[];
    by_os: { name: string; count: number }[];
    by_department: { name: string; count: number }[];
    by_object: { name: string; count: number }[];
    sources: Source[];
  };
}
