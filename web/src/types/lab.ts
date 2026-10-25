export type DeviceKind = "router" | "switch" | "host" | "firewall";
export interface Port {
  name: string;
  address: string;
}
export interface Point {
  x: number;
  y: number;
}
export interface Device extends Point {
  template?: string;
  width?: number;
  height?: number;
  id: string;
  name: string;
  kind: DeviceKind;
  image: string;
  ports: Port[];
  gateway: string;
  command: string[];
  config: string;
}
export interface Endpoint {
  node: string;
  port: string;
}
export interface Link {
  id: string;
  a: Endpoint;
  b: Endpoint;
}
export interface Annotation extends Point {
  id: string;
  text: string;
  color: string;
  background: string;
  fontSize: number;
}
export interface Topology {
  version: 1;
  id: string;
  name: string;
  nodes: Device[];
  links: Link[];
  annotations?: Annotation[];
  optimizeLinks?: boolean;
}
export type Phase =
  | "idle"
  | "running"
  | "deploying"
  | "updating"
  | "destroying"
  | "error"
  | "degraded";
export interface Runtime {
  phase: Phase;
  deployment?: string;
  error?: string;
  nodes: Record<string, { id: string; name: string; pid: number }>;
  logs: { time: string; message: string }[];
}
export interface LabRecord {
  topology: Topology;
  runtime: Runtime;
  busy?: boolean;
}
export interface LabSummary {
  id: string;
  name: string;
  nodes: number;
  phase: Phase;
}
export interface Environment {
  ready: boolean;
  preview: boolean;
  errors: string[];
  images: string[];
}
export interface DeviceTemplate {
  present?: boolean;
  id?: string;
  template_id?: string;
  source?: string;
  version?: number | string;
  managed?: boolean;
  profile?: "generic" | "frr";
  descriptor_id?: string;
  descriptor_version?: string;
  image_reference?: string;
  adapter?: string;
  console?: string;
  capabilities?: { save_config: boolean; startup_config: boolean };
  kind: DeviceKind;
  title: string;
  image: string;
  ports: number;
  prefix: string;
}
export interface Bootstrap {
  catalog: DeviceTemplate[];
  environment: Environment;
  labs: LabSummary[];
}
export interface CommandResult {
  code: number;
  output: string;
}
export interface DeviceConfigStatus {
  supported: boolean;
  persisted?: boolean;
  saved_at?: string | null;
  modified_at?: number | null;
  path?: string;
  content?: string;
  shared?: boolean;
  files?: { path: string; size?: number }[];
  paths?: string[];
}
export interface ConfigSaveResult {
  results: {
    node: string;
    ok: boolean;
    status?: DeviceConfigStatus;
    config?: string;
    error?: string;
  }[];
  runtime: Runtime;
}
export interface ProjectSaveResult {
  record: LabRecord;
  topology_saved: true;
  results: (ConfigSaveResult["results"][number] & { skipped?: boolean })[];
}
export type Selection = {
  type: "node" | "link" | "annotation";
  id: string;
} | null;
