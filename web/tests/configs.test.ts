import { createPinia, setActivePinia } from "pinia";
import { nextTick } from "vue";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import example from "../../examples/basic-lab.json";
import { parseTopology } from "../src/domain/topology";
import { useLabStore } from "../src/stores/lab";
import { useEditorStore } from "../src/stores/editor";
import { useTerminalsStore } from "../src/stores/terminals";

beforeEach(() => setActivePinia(createPinia()));
afterEach(() => vi.unstubAllGlobals());
async function setup() {
  const lab = useLabStore(),
    editor = useEditorStore();
  const topology = parseTopology(example);
  lab.adopt(topology, {
    topology,
    runtime: {
      phase: "running",
      deployment: "test",
      logs: [],
      nodes: { r1: { id: "cid", name: "R1", pid: 123 } },
    },
  });
  lab.environment.ready = true;
  editor.select({ type: "node", id: "r1" });
  const terminals = useTerminalsStore();
  await nextTick();
  terminals.open("r1");
  return { lab, editor, terminals };
}
const response = (body: unknown) => new Response(JSON.stringify(body));

it("saves configuration without closing terminals or leaving an old inspector draft", async () => {
  const { lab, editor, terminals } = await setup();
  const version = lab.documentVersion;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      response({
        runtime: lab.runtime,
        results: [
          {
            node: "r1",
            ok: true,
            config: "hostname SAVED",
            status: {
              supported: true,
              persisted: true,
              content: "hostname SAVED",
              shared: true,
            },
          },
        ],
      }),
    ),
  );
  expect(lab.locked).toBe(true);
  expect(lab.canSaveConfig("r1")).toBe(true);
  await lab.saveConfigs("r1");
  await nextTick();
  expect(lab.getNode("r1")?.config).toBe("hostname SAVED");
  expect(editor.draft?.config).toBe("hostname SAVED");
  expect(lab.documentVersion).toBe(version);
  expect(terminals.tabs).toHaveLength(1);
  expect(lab.dirty).toBe(false);
  lab.runtime = { phase: "idle", nodes: {}, logs: [] };
  editor.draft!.name = "RENAMED";
  editor.touchDraft();
  editor.commitDraft();
  expect(lab.getNode("r1")?.config).toBe("hostname SAVED");
});

it("preserves successful results when saving other devices fails", async () => {
  const { lab } = await setup();
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      response({
        runtime: lab.runtime,
        results: [
          {
            node: "r1",
            ok: true,
            config: "hostname SAVED",
            status: { supported: true, persisted: true },
          },
          { node: "r2", ok: false, error: "协议进程未运行" },
        ],
      }),
    ),
  );
  await expect(lab.saveConfigs()).rejects.toThrow("r2：协议进程未运行");
  expect(lab.getNode("r1")?.config).toBe("hostname SAVED");
  expect(lab.operation).toBe("");
});

it("rejects stale file previews after changing experiments", async () => {
  const { lab } = await setup();
  let resolve!: (value: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(
      () =>
        new Promise<Response>((r) => {
          resolve = r;
        }),
    ),
  );
  const pending = lab.loadConfig("r1");
  lab.newLab();
  resolve(response({ r1: { supported: true, content: "OLD LAB" } }));
  await pending;
  expect(lab.configs).toEqual({});
});

it("disables saving for unsupported devices and during jobs", async () => {
  const { lab } = await setup();
  expect(lab.canSaveConfig("pc1")).toBe(false);
  lab.busy = true;
  expect(lab.canSaveConfig("r1")).toBe(false);
  await expect(lab.saveConfigs("r1")).rejects.toThrow("等待操作完成");
});

it("preserves template identity through creation and JSON import", () => {
  const lab = useLabStore();
  lab.catalog = [
    {
      id: "frr",
      kind: "router",
      image: "alpine/frr:latest",
      title: "FRR",
      prefix: "R",
      ports: 4,
      capabilities: { save_config: true, startup_config: true },
    },
  ];
  const node = lab.addNode("frr", { x: 200, y: 200 });
  expect(node.template).toBe("frr");
  expect(parseTopology(lab.topology).nodes[0]?.template).toBe("frr");
  expect(lab.supportsConfig(node)).toBe(true);
});
