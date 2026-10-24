import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { deviceCategories, filterDevices } from "../src/domain/library";
import { useImagesStore } from "../src/stores/images";
import { useLabStore } from "../src/stores/lab";
import { parseTopology } from "../src/domain/topology";
import type { DeviceTemplate } from "../src/types/lab";
import type { ImageInventory, ImageJob } from "../src/types/images";

beforeEach(() => setActivePinia(createPinia()));
afterEach(() => vi.unstubAllGlobals());
const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });
const inventory = (): ImageInventory => ({
  images: [],
  jobs: [],
  available: true,
  busy: false,
  error: "",
  registry_path: "/data/images/registry.json",
  max_upload_bytes: 1024,
});
const job: ImageJob = {
  id: "new-job",
  mode: "pull",
  label: "test/router:one",
  state: "queued",
  logs: "",
  images: [],
  error: "",
  created_at: "2026-10-23",
  finished_at: null,
};
const card: DeviceTemplate = {
  id: "img-custom",
  template_id: "frr",
  kind: "router",
  image: "test/frr:one",
  title: "Custom FRR",
  ports: 4,
  prefix: "R",
};

it("filters a large library by category, name and image without changing the catalog", () => {
  const catalog = Array.from({ length: 200 }, (_, i) => ({
    ...card,
    id: `img-${i}`,
    title: `Router ${i}`,
    image: `test/router:${i}`,
  }));
  expect(filterDevices(catalog, "router:199", "router")).toHaveLength(1);
  expect(filterDevices(catalog, "ROUTER 199", "all")[0]?.id).toBe("img-199");
  expect(filterDevices(catalog, "", "host")).toHaveLength(0);
  expect(catalog).toHaveLength(200);
  expect(
    filterDevices(
      [{ ...card, id: "img-199", title: "Router 004" }],
      "Router 199",
      "router",
    ),
  ).toHaveLength(0);
});

it("uses the registered adapter identity when dragging a custom image card", () => {
  const lab = useLabStore();
  lab.catalog = [card];
  const node = lab.addNode("img-custom", { x: 100, y: 100 });
  expect(node.template).toBe("frr");
  expect(node.image).toBe("test/frr:one");
  expect(parseTopology(lab.topology).nodes[0]?.template).toBe("frr");
});

it("does not let an older inventory response erase a newly submitted job", async () => {
  const images = useImagesStore();
  let resolve!: (value: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      url === "/api/images"
        ? new Promise<Response>((r) => {
            resolve = r;
          })
        : Promise.resolve(response(job)),
    ),
  );
  const refreshing = images.refresh();
  await images.start({ mode: "pull", reference: "test/router:one" });
  resolve(response(inventory()));
  await refreshing;
  expect(images.data.busy).toBe(true);
  expect(images.job?.id).toBe(job.id);
});

it("refreshes device choices when a background image job completes", async () => {
  const images = useImagesStore(),
    lab = useLabStore();
  images.data.busy = true;
  const fetchMock = vi.fn((url: string) =>
    Promise.resolve(
      response(
        url === "/api/images"
          ? { ...inventory(), jobs: [{ ...job, state: "success" }] }
          : url === "/api/catalog"
            ? [card]
            : {
                ready: false,
                preview: false,
                errors: [],
                images: [card.image],
              },
      ),
    ),
  );
  vi.stubGlobal("fetch", fetchMock);
  await images.refresh();
  expect(images.data.busy).toBe(false);
  expect(lab.catalog[0]?.image).toBe(card.image);
  expect(lab.environment.images).toContain(card.image);
});

it("retains inventory and clears submission state when delete is rejected", async () => {
  const images = useImagesStore();
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(response({ error: "镜像被容器使用" }, 400)),
  );
  await expect(images.remove("used", true)).rejects.toThrow("镜像被容器使用");
  expect(images.submitting).toBe(false);
  expect(images.data.busy).toBe(false);
});

it("only requests Docker deletion explicitly and otherwise forgets the record", async () => {
  const images = useImagesStore();
  const fetchMock = vi
    .fn()
    .mockImplementation(() => Promise.resolve(response(job)));
  vi.stubGlobal("fetch", fetchMock);
  await images.remove("borrowed");
  expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/images/jobs");
  expect(JSON.parse(fetchMock.mock.calls[0]?.[1].body)).toEqual({
    mode: "forget",
    id: "borrowed",
  });
  images.data.busy = false;
  await images.remove("owned", true);
  expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/images/owned");
  expect(fetchMock.mock.calls[1]?.[1].method).toBe("DELETE");
});

it("rejects compressed image filenames before uploading and releases submission state", async () => {
  const images = useImagesStore();
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  for (const name of [
    "image.tar.gz",
    "image.tar.xz",
    "image.tgz",
    "image.zip",
  ]) {
    await expect(
      images.start({ mode: "archive" }, new File(["archive"], name)),
    ).rejects.toThrow("仅支持未压缩的 .tar");
    expect(images.busy).toBe(false);
    expect(images.uploading).toBe(false);
  }
  expect(fetchMock).not.toHaveBeenCalled();
});

it("supports the four sidebar groups and uses the firewall Linux template", () => {
  expect(deviceCategories.map((item) => item.id)).toEqual([
    "router",
    "switch",
    "host",
    "firewall",
  ]);
  const lab = useLabStore();
  lab.catalog = [
    {
      ...card,
      id: "img-fw",
      kind: "firewall",
      template_id: "linux-firewall",
      prefix: "FW",
    },
  ];
  const node = lab.addNode("img-fw", { x: 10, y: 20 });
  expect(node).toMatchObject({
    id: "fw1",
    name: "FW1",
    kind: "firewall",
    template: "linux-firewall",
  });
  expect(parseTopology(lab.topology).nodes[0]).toEqual(node);
  expect(lab.supportsConfig(node)).toBe(false);
});

it("resolves FRR capabilities from image-derived cards", () => {
  const lab = useLabStore();
  lab.catalog = [
    {
      ...card,
      capabilities: { save_config: true, startup_config: true },
      console: "vtysh",
    },
  ];
  const node = lab.addNode(card.id!, { x: 0, y: 0 });
  expect(lab.getTemplate(node)?.console).toBe("vtysh");
  expect(lab.supportsConfig(node)).toBe(true);
  lab.catalog = [];
  expect(lab.supportsConfig(node)).toBe(true);
});

it("retries failed catalog refresh after a deletion and removes stale cards", async () => {
  const images = useImagesStore(),
    lab = useLabStore();
  images.data.busy = true;
  lab.catalog = [card];
  let attempts = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      if (url === "/api/catalog") {
        attempts++;
        return Promise.resolve(
          attempts === 1 ? response({ error: "temporary" }, 503) : response([]),
        );
      }
      return Promise.resolve(
        response(
          url === "/api/images"
            ? inventory()
            : { ready: false, preview: false, errors: [], images: [] },
        ),
      );
    }),
  );
  await expect(images.refresh()).rejects.toThrow("temporary");
  expect(lab.catalog).toHaveLength(1);
  await images.refresh();
  expect(attempts).toBe(2);
  expect(lab.catalog).toEqual([]);
});

it("does not let a stale catalog response bring deleted cards back", async () => {
  const lab = useLabStore();
  let old!: (value: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            old = resolve;
          }),
      )
      .mockResolvedValueOnce(response([])),
  );
  const stale = lab.refreshCatalog();
  await lab.refreshCatalog();
  old(response([card]));
  await stale;
  expect(lab.catalog).toEqual([]);
});
