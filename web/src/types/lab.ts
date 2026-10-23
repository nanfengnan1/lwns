export type DeviceKind = "router" | "switch" | "host";
export interface Port {
  name: string;
  address: string;
}
export interface Point {
  x: number;
  y: number;
}
export interface Device extends Point {
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
export interface Topology {
  version: 1;
  id: string;
  name: string;
  nodes: Device[];
  links: Link[];
}
export type Phase =
  "idle" | "running" | "deploying" | "destroying" | "error" | "degraded";
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
  example: Topology;
}
export interface CommandResult {
  code: number;
  output: string;
}
export type Selection = { type: "node" | "link"; id: string } | null;
