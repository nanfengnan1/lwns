import { createPinia, setActivePinia } from "pinia";
import { nextTick } from "vue";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import example from "../../examples/basic-lab.json";
import { clone, parseTopology } from "../src/domain/topology";
import { networkSignature } from "../src/domain/deployment";
import { useLabStore } from "../src/stores/lab";
import { useEditorStore } from "../src/stores/editor";
import { useTerminalsStore } from "../src/stores/terminals";
import { useProjectFiles } from "../src/composables/useProjectFiles";
import type { LabRecord, Topology } from "../src/types/lab";

const response = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status });
function setup() {
  const lab = useLabStore(),
    editor = useEditorStore();
  const topology = parseTopology(example);
  const original: LabRecord = {
    topology,
    runtime: {
      phase: "running",
      deployment: "owned",
      logs: [],
      nodes: Object.fromEntries(
        topology.nodes.map((node, i) => [
          node.id,
          { id: `cid-${node.id}`, name: node.name, pid: i + 100 },
        ]),
      ),
    },
    busy: false,
  };
  lab.adopt(topology, original);
  lab.environment.ready = true;
  lab.catalog = [
    {
      kind: "host",
      title: "PC",
      image: "alpine/vpcs:latest",
      ports: 1,
      prefix: "PC",
    },
    {
      kind: "router",
      title: "FRR",
      image: "alpine/frr:latest",
      ports: 4,
      prefix: "R",
    },
  ];
  return { lab, editor, original: clone(original) };
}
function updating(record: LabRecord) {
  return {
    ...clone(record),
    runtime: { ...clone(record.runtime), phase: "updating" },
    busy: true,
  };
}
function complete(record: LabRecord, topology: Topology) {
  return { ...clone(record), topology: clone(topology), busy: false };
}
beforeEach(() => {
  setActivePinia(createPinia());
  vi.useFakeTimers();
  vi.stubGlobal("window", { confirm: vi.fn(() => true) });
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("distinguishes runtime edits from layout and annotation edits independent of JSON key order", () => {
  const { lab, original } = setup();
  lab.moveNode("r1", { x: 700, y: 400 });
  const note = lab.addAnnotation({ x: 0, y: 0 });
  lab.updateAnnotation({ ...note, text: "新网段", color: "#ffffff" });
  lab.setLinkOptimization(false);
  expect(lab.pendingUpdate).toBe(false);
  const reordered = clone(original.topology);
  reordered.nodes.reverse();
  reordered.links.reverse();
  reordered.nodes.forEach((node) => {
    node.ports = node.ports
      .map(({ name, address }) => ({ address, name }))
      .reverse();
  });
  expect(networkSignature(reordered)).toBe(networkSignature(original.topology));
  lab.getNode("pc1")!.ports[0].address = "10.10.1.11/24";
  expect(lab.pendingUpdate).toBe(true);
  lab.getNode("pc1")!.ports[0].address = original.topology.nodes.find(
    (node) => node.id === "pc1",
  )!.ports[0].address;
  expect(lab.pendingUpdate).toBe(false);
});

it("keeps draft additions separate from existing runtime and never reuses a deleted running ID", () => {
  const { lab } = setup();
  lab.remove("node", "pc1");
  const added = lab.addNode("host", { x: 20, y: 20 });
  expect(added.id).toMatch(/^[a-f0-9]{32}$/);
  expect(lab.getRuntimeNode("pc1")?.name).toBe("PC1");
  expect(lab.getRuntimeNode(added.id)).toBeUndefined();
  expect(lab.canOpenTerminal(added.id)).toBe(false);
  expect(lab.canOpenTerminal("pc1")).toBe(true);
  expect(lab.updateChanges.removed.map((node) => node.id)).toEqual(["pc1"]);
});

it("saves full visual changes without sending a runtime update and advances its base", async () => {
  const { lab, original } = setup();
  lab.addAnnotation({ x: 10, y: 20 });
  const visual = clone(lab.topology);
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(response(complete(original, visual)))
    .mockResolvedValueOnce(response(updating(complete(original, visual))));
  vi.stubGlobal("fetch", fetchMock);
  await lab.save();
  expect(fetchMock.mock.calls[0][1].method).toBe("PUT");
  expect(JSON.parse(fetchMock.mock.calls[0][1].body).annotations).toHaveLength(
    1,
  );
  expect(lab.pendingUpdate).toBe(false);
  lab.remove("link", "l4");
  await lab.startJob("update");
  expect(JSON.parse(fetchMock.mock.calls[1][1].body).base).toEqual(visual);
});

it("never silently applies network edits from Save and still blocks deleting the whole deployed project", async () => {
  const { lab } = setup();
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  lab.remove("link", "l1");
  await expect(lab.save()).rejects.toThrow("应用拓扑");
  await expect(lab.deleteLab()).rejects.toThrow("清理");
  expect(fetchMock).not.toHaveBeenCalled();
  expect(lab.dirty).toBe(true);
});

it("confirms concrete rebuild/deletion impact and preserves the draft when cancelled", async () => {
  const { lab, editor } = setup();
  editor.select({ type: "node", id: "r1" });
  editor.draft!.image = "alpine/frr:new";
  editor.touchDraft();
  lab.remove("node", "pc2");
  vi.mocked(window.confirm).mockReturnValue(false);
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  await useProjectFiles().applyTopology();
  expect(window.confirm).toHaveBeenCalledOnce();
  const message = vi.mocked(window.confirm).mock.calls[0][0]!;
  expect(message).toContain("删除 1 台，重建 1 台");
  expect(message).toContain("PC2、R1");
  expect(message).toContain("未保存的终端配置");
  expect(message).toContain("终端与抓包会断开");
  expect(fetchMock).not.toHaveBeenCalled();
  expect(lab.pendingUpdate).toBe(true);
  expect(lab.runtime?.phase).toBe("running");
});

it("sends the original base, locks while applying, closes sessions and clears dirty only after success", async () => {
  const { lab, editor, original } = setup();
  const terminals = useTerminalsStore();
  await nextTick();
  terminals.open("r1");
  lab.remove("link", "l4");
  editor.select({ type: "node", id: "r1" });
  const target = clone(lab.topology),
    view = clone(editor.view),
    version = lab.documentVersion;
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(response(updating(original)))
    .mockResolvedValueOnce(response(complete(original, target)));
  vi.stubGlobal("fetch", fetchMock);
  await useProjectFiles().applyTopology();
  await nextTick();
  expect(fetchMock.mock.calls[0][0]).toBe(`/api/labs/${target.id}/update`);
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
    topology: target,
    base: original.topology,
  });
  expect(lab.dirty).toBe(true);
  expect(lab.locked).toBe(true);
  expect(terminals.tabs).toHaveLength(0);
  expect(() => lab.remove("node", "r1")).toThrow();
  expect(() => lab.moveNode("r1", { x: 0, y: 0 })).toThrow();
  expect(lab.canSaveConfig()).toBe(false);
  expect(lab.canCapture("l1")).toBe(false);
  await lab.refresh();
  await nextTick();
  expect(lab.topology).toEqual(target);
  expect(lab.dirty).toBe(false);
  expect(lab.pendingUpdate).toBe(false);
  expect(lab.locked).toBe(false);
  expect(lab.documentVersion).toBe(version);
  expect(editor.view).toEqual(view);
  expect(editor.selected).toEqual({ type: "node", id: "r1" });
});

it("keeps an unsuccessful draft for cleanup/redeployment and forbids immediate retry", async () => {
  const { lab, original } = setup();
  lab.remove("link", "l4");
  const target = clone(lab.topology);
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(response(updating(original)))
    .mockResolvedValueOnce(
      response({
        ...original,
        runtime: {
          ...original.runtime,
          phase: "error",
          error: "更新失败，请清理",
        },
      }),
    );
  vi.stubGlobal("fetch", fetchMock);
  await lab.startJob("update");
  await lab.refresh();
  expect(lab.topology).toEqual(target);
  expect(lab.dirty).toBe(true);
  expect(lab.canUpdate).toBe(false);
  expect(lab.canDestroy).toBe(true);
  expect(lab.runtime?.error).toContain("更新失败");
  await expect(lab.startJob("update")).rejects.toThrow("不允许");
});

it("keeps the base and draft intact when the server rejects a stale update", async () => {
  const { lab, original } = setup();
  lab.remove("link", "l4");
  const target = clone(lab.topology);
  const fetchMock = vi
    .fn()
    .mockResolvedValue(response({ error: "拓扑已变化，请重新加载" }, 409));
  vi.stubGlobal("fetch", fetchMock);
  await expect(lab.startJob("update")).rejects.toThrow("重新加载");
  expect(lab.topology).toEqual(target);
  expect(lab.runtime).toEqual(original.runtime);
  expect(lab.dirty).toBe(true);
  expect(lab.busy).toBe(false);
  expect(lab.operation).toBe("");
});

it("does not advance the update base on routine polling while an inspector draft is open", async () => {
  const { lab, editor, original } = setup();
  editor.select({ type: "node", id: "r1" });
  editor.draft!.name = "MY-DRAFT";
  editor.touchDraft();
  const external = clone(original);
  external.topology.nodes[0].image = "alpine/frr:external-change";
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(response(external))
    .mockResolvedValueOnce(response({ error: "拓扑已变化，请重新加载" }, 409));
  vi.stubGlobal("fetch", fetchMock);
  await lab.refresh();
  editor.commitDraft();
  await expect(lab.startJob("update")).rejects.toThrow("重新加载");
  expect(JSON.parse(fetchMock.mock.calls[1][1].body).base).toEqual(
    original.topology,
  );
  expect(lab.getNode("r1")?.name).toBe("MY-DRAFT");
});

it("ignores an old refresh that completes after the update was accepted", async () => {
  const { lab, original } = setup();
  lab.remove("link", "l4");
  let release!: (value: Response) => void;
  const fetchMock = vi
    .fn()
    .mockImplementationOnce(
      () =>
        new Promise<Response>((r) => {
          release = r;
        }),
    )
    .mockResolvedValueOnce(response(updating(original)));
  vi.stubGlobal("fetch", fetchMock);
  const refresh = lab.refresh();
  await lab.startJob("update");
  release(response(original));
  await refresh;
  expect(lab.phase).toBe("updating");
  expect(lab.busy).toBe(true);
  expect(lab.dirty).toBe(true);
});

it("allows applying an empty topology after removing all deployed devices", async () => {
  const { lab, original } = setup();
  for (const node of [...lab.topology.nodes]) lab.remove("node", node.id);
  const target = clone(lab.topology);
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(response(updating(original)))
    .mockResolvedValueOnce(
      response({
        ...complete(original, target),
        runtime: { ...original.runtime, nodes: {} },
      }),
    );
  vi.stubGlobal("fetch", fetchMock);
  expect(lab.canUpdate).toBe(true);
  await lab.startJob("update");
  await lab.refresh();
  expect(lab.runningNodes).toEqual([]);
  expect(lab.pendingUpdate).toBe(false);
  expect(lab.dirty).toBe(false);
});

it("uses the applied device identity for terminals and config saves despite pending edits or deletion", async () => {
  const { lab } = setup();
  const terminals = useTerminalsStore();
  await nextTick();
  lab.updateNode({
    ...lab.getNode("r1")!,
    name: "RENAMED",
    kind: "host",
    image: "alpine/vpcs:latest",
  });
  terminals.open("r1");
  expect(terminals.tabs[0]).toMatchObject({ name: "R1", mode: "default" });
  expect(lab.canSaveConfig("r1")).toBe(true);
  lab.remove("node", "r1");
  expect(lab.canSaveConfig("r1")).toBe(true);
  const added = lab.addNode("router", { x: 0, y: 0 });
  expect(lab.canSaveConfig(added.id)).toBe(false);
  expect(() => terminals.open(added.id)).toThrow("部署");
});

it("captures only a link whose endpoints still match the running link", () => {
  const { lab } = setup();
  expect(lab.canCapture("l1")).toBe(true);
  lab.connect({ node: "r1", port: "eth2" }, { node: "sw1", port: "eth2" });
  expect(lab.canCapture(lab.topology.links.at(-1)!.id)).toBe(false);
  lab.topology.links.find((link) => link.id === "l1")!.a.port = "eth3";
  expect(lab.canCapture("l1")).toBe(false);
});

it("updates the base after saving running config while retaining an explicitly edited startup config", async () => {
  const { lab, original } = setup();
  lab.updateNode({ ...lab.getNode("r1")!, config: "hostname MANUAL" });
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(
      response({
        runtime: original.runtime,
        results: [{ node: "r1", ok: true, config: "hostname RUNTIME" }],
      }),
    )
    .mockResolvedValueOnce(response(updating(original)));
  vi.stubGlobal("fetch", fetchMock);
  await lab.saveConfigs("r1");
  expect(lab.getNode("r1")?.config).toBe("hostname MANUAL");
  await lab.startJob("update");
  const payload = JSON.parse(fetchMock.mock.calls[1][1].body);
  expect(payload.base.nodes[0].config).toBe("hostname RUNTIME");
  expect(payload.topology.nodes[0].config).toBe("hostname MANUAL");
});

it("merges a freshly saved config into an inspector draft that changed only another property", async () => {
  const { lab, editor, original } = setup();
  editor.select({ type: "node", id: "r1" });
  editor.draft!.name = "RENAMED";
  editor.touchDraft();
  const fetchMock = vi.fn().mockResolvedValue(
    response({
      runtime: original.runtime,
      results: [{ node: "r1", ok: true, config: "hostname RUNTIME" }],
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  await lab.saveConfigs("r1");
  await nextTick();
  expect(editor.draft!.config).toBe("hostname RUNTIME");
  editor.commitDraft();
  expect(lab.getNode("r1")).toMatchObject({
    name: "RENAMED",
    config: "hostname RUNTIME",
  });
});
