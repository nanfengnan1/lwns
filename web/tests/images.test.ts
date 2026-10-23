import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { filterDevices } from "../src/domain/library";
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
  await expect(images.remove("used")).rejects.toThrow("镜像被容器使用");
  expect(images.submitting).toBe(false);
  expect(images.data.busy).toBe(false);
});
