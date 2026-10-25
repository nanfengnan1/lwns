import type { DeviceKind } from "./lab";

export interface DeviceDescriptor extends Record<string, unknown> {
  schema_version: number;
  id: string;
  version: string;
  name: string;
  category: DeviceKind;
  image: string;
}
export interface DevicePackageEntry {
  id: string;
  descriptor_id: string;
  version: string;
  name: string;
  category: DeviceKind;
  image: string;
  image_id: string;
  present?: boolean;
  created_at?: string;
}
export interface DevicePackageJob {
  id: string;
  mode: string;
  label: string;
  state: "queued" | "running" | "success" | "error";
  logs: string;
  error: string;
  created_at: string;
  finished_at?: string | null;
  result?: {
    download_url?: string;
    filename?: string;
    path?: string;
    device?: DevicePackageEntry;
  };
}
export interface DevicePackageInventory {
  devices: DevicePackageEntry[];
  jobs: DevicePackageJob[];
  busy: boolean;
  available: boolean;
  error: string;
  registry_path: string;
  max_upload_bytes: number;
}
export interface DevicePackageInspection {
  descriptor: DeviceDescriptor;
  template_id: string;
  package_sha256: string;
  resources: unknown;
}
export interface DevicePackageSource {
  type: "repository" | "local" | "archive" | "dockerfile";
  reference?: string;
  upload_id?: string;
  dockerfile?: string;
}
