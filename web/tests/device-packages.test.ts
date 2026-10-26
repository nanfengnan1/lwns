import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { setToken } from "../src/api/client";
import {
  readDeviceDescriptor,
  validatePackageFile,
} from "../src/domain/devicePackages";
import { useDevicePackagesStore } from "../src/stores/devicePackages";
import { useLabStore } from "../src/stores/lab";
import type {
  DeviceDescriptor,
  DevicePackageInventory,
  DevicePackageJob,
} from "../src/types/devicePackages";
import type { DeviceTemplate } from "../src/types/lab";

const base = "/api/device-packages";
const response = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const descriptor: DeviceDescriptor = {
  schema_version: 1,
  id: "generic-router",
  version: "1.0.0",
  name: "自定义路由器",
  category: "router",
  image: "test/router:1",
  actions: { save_config: { exec: ["save-config"] } },
};
const inventory = (): DevicePackageInventory => ({
  devices: [],
  jobs: [],
  busy: false,
  available: true,
  error: "",
  registry_path: "/data/device-library/registry.json",
  max_upload_bytes: 1024,
});
const queued: DevicePackageJob = {
  id: "job1",
  mode: "pack",
  label: "Generic router",
  state: "queued",
  logs: "",
  error: "",
  created_at: "2026-10-25",
};
const template: DeviceTemplate = {
  id: "rov-test",
  template_id: "rov-test",
  managed: true,
  descriptor_id: "generic-router",
  descriptor_version: "1.0.0",
  version: "1.0.0",
  kind: "router",
  title: "自定义路由器",
  image: "sha256:abc123",
  image_reference: "test/router:1",
  ports: 4,
  prefix: "R",
  capabilities: { save_config: true, startup_config: false },
};
const requests: UploadRequest[] = [];
class UploadRequest {
  method = "";
  url = "";
  headers: Record<string, string> = {};
  status = 200;
  responseText = "{}";
  upload: {
    onprogress?: (event: {
      lengthComputable: boolean;
      loaded: number;
      total: number;
    }) => void;
  } = {};
  onload?: () => void;
  onerror?: () => void;
  onabort?: () => void;
  open(method: string, url: string) {
    this.method = method;
    this.url = url;
    requests.push(this);
  }
  setRequestHeader(key: string, value: string) {
    this.headers[key] = value;
  }
  send() {
    queueMicrotask(() => this.onload?.());
  }
  abort() {
    this.onabort?.();
  }
}
beforeEach(() => {
  setActivePinia(createPinia());
  setToken("device-token");
  requests.length = 0;
  vi.stubGlobal("XMLHttpRequest", UploadRequest);
});
afterEach(() => vi.unstubAllGlobals());

it("reads descriptor metadata while preserving native configuration declarations", () => {
  const source = {
    ...descriptor,
    persistent_dirs: [{ id: "startup", target: "/etc/custom" }],
    startup: { service: { exec: ["router", "-c", "/etc/custom/start"] } },
  };
  expect(readDeviceDescriptor(JSON.stringify(source))).toEqual(source);
  expect(() => readDeviceDescriptor('{"schema_version":2}')).toThrow(
    "schema_version",
  );
  expect(() =>
    readDeviceDescriptor(JSON.stringify({ ...source, actions: {} })),
  ).toThrow("save_config");
  expect(() => readDeviceDescriptor("not-json")).toThrow("JSON");
});

it("rejects wrong package and archive types before creating uploads", async () => {
  const packages = useDevicePackagesStore();
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  await expect(
    packages.inspectFile(new File(["x"], "image.tar")),
  ).rejects.toThrow(".lwns");
  await expect(
    packages.pack(
      descriptor,
      "Router",
      { type: "archive" },
      new File(["x"], "image.tar.gz"),
    ),
  ).rejects.toThrow("未压缩");
  expect(fetchMock).not.toHaveBeenCalled();
  expect(packages.busy).toBe(false);
});

it("accepts new and legacy device extensions while keeping image archives separate", () => {
  for (const name of ["device.lwns", "DEVICE.LWNS", "old.rov"])
    expect(() =>
      validatePackageFile(new File(["zip"], name), "package", 1024),
    ).not.toThrow();
  expect(() =>
    validatePackageFile(new File(["zip"], "device.lwns"), "archive", 1024),
  ).toThrow(".tar");
});

it("associates inspected bytes and import using the returned upload ID", async () => {
  const packages = useDevicePackagesStore();
  const inspect = {
    descriptor,
    template_id: template.id,
    package_sha256: "digest",
    resources: [],
  };
  const fetchMock = vi.fn(
    (url: string, _options?: { body?: string; method?: string }) =>
      Promise.resolve(
        response(
          url.endsWith("/uploads")
            ? { id: "uploaded-a" }
            : url.endsWith("/inspect")
              ? inspect
              : queued,
        ),
      ),
  );
  vi.stubGlobal("fetch", fetchMock);
  await packages.inspectFile(new File(["zip"], "device.lwns"));
  expect(requests[0]?.url).toBe(`${base}/uploads/uploaded-a`);
  expect(requests[0]?.headers.Authorization).toBe("Bearer device-token");
  expect(JSON.parse(fetchMock.mock.calls[0]![1]?.body || "")).toEqual({
    name: "device.lwns",
    size: 3,
    kind: "package",
  });
  await packages.importPackage("我的路由器");
  const request = fetchMock.mock.calls.find(([url]) => url.endsWith("/jobs"));
  expect(JSON.parse(request![1]!.body || "")).toEqual({
    mode: "import",
    upload_id: "uploaded-a",
    name: "我的路由器",
  });
  expect(packages.inspection?.template_id).toBe(template.id);
  expect(packages.inspectedUpload).toBe("uploaded-a");
  expect(packages.busy).toBe(true);
});

it("keeps a previously inspected package when a replacement is invalid and cleans only failed upload", async () => {
  const packages = useDevicePackagesStore();
  packages.inspectedUpload = "old-upload";
  packages.inspection = {
    descriptor,
    template_id: "old",
    package_sha256: "old",
    resources: [],
  };
  const fetchMock = vi.fn(
    (url: string, _options?: { body?: string; method?: string }) =>
      Promise.resolve(
        url.endsWith("/inspect")
          ? response({ error: "归档损坏" }, 400)
          : response(url.endsWith("/uploads") ? { id: "bad-upload" } : {}),
      ),
  );
  vi.stubGlobal("fetch", fetchMock);
  await expect(
    packages.inspectFile(new File(["bad"], "bad.lwns")),
  ).rejects.toThrow("归档损坏");
  expect(packages.inspectedUpload).toBe("old-upload");
  expect(packages.inspection?.template_id).toBe("old");
  expect(
    fetchMock.mock.calls.some(
      ([url, options]) =>
        url === `${base}/uploads/bad-upload` && options?.method === "DELETE",
    ),
  ).toBe(true);
  expect(fetchMock.mock.calls.some(([url]) => url.includes("old-upload"))).toBe(
    false,
  );
});

it("attaches archive to one maker request and releases it if job submission fails", async () => {
  const packages = useDevicePackagesStore();
  const fetchMock = vi.fn(
    (url: string, _options?: { body?: string; method?: string }) =>
      Promise.resolve(
        url.endsWith("/jobs")
          ? response({ error: "当前忙" }, 400)
          : response(url.endsWith("/uploads") ? { id: "archive1" } : {}),
      ),
  );
  vi.stubGlobal("fetch", fetchMock);
  await expect(
    packages.pack(
      descriptor,
      "新设备",
      { type: "archive" },
      new File(["tar"], "image.tar"),
    ),
  ).rejects.toThrow("当前忙");
  const submitted = fetchMock.mock.calls.find(([url]) => url.endsWith("/jobs"));
  expect(JSON.parse(submitted![1]!.body || "").source).toEqual({
    type: "archive",
    upload_id: "archive1",
  });
  expect(
    fetchMock.mock.calls.some(
      ([url, options]) =>
        url === `${base}/uploads/archive1` && options?.method === "DELETE",
    ),
  ).toBe(true);
  expect(packages.busy).toBe(false);
});

it("does not let old inventory overwrite a newly queued pack job", async () => {
  const packages = useDevicePackagesStore();
  let resolve!: (response: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      url === base
        ? new Promise<Response>((r) => {
            resolve = r;
          })
        : Promise.resolve(response(queued)),
    ),
  );
  const refreshing = packages.refresh();
  await packages.pack(descriptor, "Router", {
    type: "repository",
    reference: "test/router:1",
  });
  resolve(response(inventory()));
  await refreshing;
  expect(packages.data.busy).toBe(true);
  expect(packages.job?.id).toBe("job1");
});

it("updates sidebar catalog after import and retries a failed catalog refresh", async () => {
  const packages = useDevicePackagesStore(),
    lab = useLabStore();
  packages.data.busy = true;
  let attempts = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      if (url === "/api/catalog")
        return Promise.resolve(
          ++attempts === 1
            ? response({ error: "暂时不可用" }, 503)
            : response([template]),
        );
      return Promise.resolve(
        response(
          url === base
            ? { ...inventory(), jobs: [{ ...queued, state: "success" }] }
            : {
                ready: true,
                preview: false,
                errors: [],
                images: [template.image],
              },
        ),
      );
    }),
  );
  await expect(packages.refresh()).rejects.toThrow("暂时不可用");
  await packages.refresh();
  expect(lab.catalog[0]?.id).toBe("rov-test");
  expect(attempts).toBe(2);
});

it("retains installed entries when deletion is rejected by an existing project", async () => {
  const packages = useDevicePackagesStore();
  packages.data.devices = [
    {
      id: "rov-test",
      descriptor_id: "generic-router",
      version: "1.0.0",
      name: "Router",
      category: "router",
      image: "test/router:1",
      image_id: "sha256:abc",
    },
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(response({ error: "已有项目引用该设备" }, 400)),
  );
  await expect(packages.remove("rov-test")).rejects.toThrow("已有项目引用");
  expect(packages.data.devices).toHaveLength(1);
  expect(packages.busy).toBe(false);
});

it("retains an import upload after a failed job and reuses it for an explicit retry", async () => {
  const packages = useDevicePackagesStore();
  packages.inspectedUpload = "retry-upload";
  packages.inspection = {
    descriptor,
    template_id: "rov-test",
    package_sha256: "digest",
    resources: [],
  };
  let attempts = 0;
  const fetchMock = vi.fn(
    (url: string, _options?: { body?: string; method?: string }) => {
      if (url.endsWith("/jobs"))
        return Promise.resolve(
          response({ ...queued, id: `attempt-${++attempts}`, mode: "import" }),
        );
      if (url === base)
        return Promise.resolve(
          response({
            ...inventory(),
            jobs: [
              {
                ...queued,
                id: `attempt-${attempts}`,
                mode: "import",
                state: attempts === 1 ? "error" : "success",
                error: attempts === 1 ? "拉取失败" : "",
              },
            ],
          }),
        );
      return Promise.resolve(
        response(
          url === "/api/catalog"
            ? []
            : { ready: true, preview: false, errors: [], images: [] },
        ),
      );
    },
  );
  vi.stubGlobal("fetch", fetchMock);
  await packages.importPackage("Router");
  await packages.refresh();
  expect(packages.busy).toBe(false);
  expect(packages.inspectedUpload).toBe("retry-upload");
  await packages.importPackage("Router");
  await packages.refresh();
  expect(packages.inspectedUpload).toBe("");
  expect(packages.inspection).toBe(null);
  expect(
    fetchMock.mock.calls
      .filter(([url]) => url.endsWith("/jobs"))
      .map(([, options]) => JSON.parse(options!.body!).upload_id),
  ).toEqual(["retry-upload", "retry-upload"]);
});

it("downloads only from same-origin artifact path using bearer authorization", async () => {
  const packages = useDevicePackagesStore();
  const fetchMock = vi.fn().mockResolvedValue(new Response("zip"));
  vi.stubGlobal("fetch", fetchMock);
  const result = await packages.download({
    ...queued,
    result: {
      download_url: "https://untrusted.invalid/file",
      filename: "router.lwns",
    },
  });
  expect(fetchMock).toHaveBeenCalledWith(`${base}/artifacts/job1`, {
    headers: { Authorization: "Bearer device-token" },
  });
  expect(result.filename).toBe("router.lwns");
  expect(await result.blob.text()).toBe("zip");
});

it("uses declared save capability without offering FRR startup text for generic routers", () => {
  const lab = useLabStore();
  lab.catalog = [template];
  const node = lab.addNode("rov-test", { x: 0, y: 0 });
  expect(node.template).toBe("rov-test");
  expect(node.image).toBe("sha256:abc123");
  expect(lab.supportsConfig(node)).toBe(true);
  expect(lab.supportsStartupConfig(node)).toBe(false);
  expect(lab.isManagedDevice(node)).toBe(true);
  expect(() => lab.updateNode({ ...node, image: "another:latest" })).toThrow(
    "设备定义管理",
  );
  expect(() => lab.updateNode({ ...node, command: ["sh"] })).toThrow(
    "设备定义管理",
  );
});

it("never reuses deleted instance IDs even when the display name is reused", () => {
  const lab = useLabStore();
  lab.catalog = [template];
  const first = lab.addNode("rov-test", { x: 0, y: 0 });
  lab.remove("node", first.id);
  const second = lab.addNode("rov-test", { x: 0, y: 0 });
  expect(second.name).toBe(first.name);
  expect(second.id).not.toBe(first.id);
  expect(second.id).toMatch(/^[a-f0-9]{32}$/);
});
