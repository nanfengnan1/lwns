export interface ImageEntry {
  id: string;
  reference: string;
  title: string;
  template: string;
  source: { type: string; url?: string; filename?: string; reference?: string };
  created_at: string;
  updated_at: string;
  present: boolean;
  image_id: string;
  size: string;
  can_delete: boolean;
}
export interface ImageJob {
  id: string;
  mode: string;
  label: string;
  state: "queued" | "running" | "success" | "error";
  created_at: string;
  finished_at: string | null;
  logs: string;
  error: string;
  images: string[];
}
export interface ImageInventory {
  images: ImageEntry[];
  jobs: ImageJob[];
  busy: boolean;
  available: boolean;
  error: string;
  registry_path: string;
  max_upload_bytes: number;
}
