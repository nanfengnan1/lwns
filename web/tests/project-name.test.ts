import { createPinia, setActivePinia } from "pinia";
import { nextTick } from "vue";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import example from "../../examples/basic-lab.json";
import { parseTopology } from "../src/domain/topology";
import { useLabStore } from "../src/stores/lab";
import { useEditorStore } from "../src/stores/editor";
import { useTerminalsStore } from "../src/stores/terminals";
import type { Runtime } from "../src/types/lab";

beforeEach(() => setActivePinia(createPinia()));
afterEach(() => vi.unstubAllGlobals());
const idle = (): Runtime => ({ phase: "idle", nodes: {}, logs: [] });
const response = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status });
function saved() {
  const lab = useLabStore(),
    topology = parseTopology(example);
  lab.adopt(topology, { topology, runtime: idle() });
  lab.labs = [
    { id: topology.id, name: topology.name, nodes: 5, phase: "idle" },
  ];
  return lab;
}
it("creates distinct named drafts and validates before replacing the current project", async () => {
  const lab = useLabStore(),
    fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  lab.newLab("  OSPF 双网段  ");
  const id = lab.topology.id;
  expect(lab.topology.name).toBe("OSPF 双网段");
  expect(lab.saved).toBe(false);
  expect(() => lab.newLab("   ")).toThrow("项目名称");
  expect(lab.topology.id).toBe(id);
  await lab.rename("BGP 实验");
  expect(lab.topology.name).toBe("BGP 实验");
  expect(fetchMock).not.toHaveBeenCalled();
  lab.newLab("BGP 实验");
  expect(lab.topology.id).not.toBe(id);
});
it("persists a renamed project and reloads its name with the same ID", async () => {
  const lab = saved(),
    id = lab.topology.id;
  const topology = { ...lab.topology, name: "中文项目 2" };
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(response({ id, name: topology.name }))
    .mockResolvedValueOnce(response({ topology, runtime: idle() }));
  vi.stubGlobal("fetch", fetchMock);
  await lab.rename(" 中文项目 2 ");
  expect(fetchMock.mock.calls[0]).toMatchObject([
    `/api/labs/${id}/rename`,
    { method: "POST", body: JSON.stringify({ name: topology.name }) },
  ]);
  expect(lab.labs[0].name).toBe(topology.name);
  expect(lab.dirty).toBe(false);
  await lab.load(id);
  expect(lab.topology.name).toBe(topology.name);
  expect(lab.topology.id).toBe(id);
});
it("preserves deployed runtime, selection and terminal tabs during metadata-only rename", async () => {
  const lab = saved(),
    editor = useEditorStore(),
    terminals = useTerminalsStore();
  lab.environment.ready = true;
  lab.runtime = {
    ...idle(),
    phase: "running",
    deployment: "run",
    nodes: { r1: { id: "cid", name: "container", pid: 42 } },
  };
  editor.select({ type: "node", id: "r1" });
  terminals.open("r1");
  const runtime = JSON.stringify(lab.runtime),
    version = lab.documentVersion,
    tab = terminals.active;
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(response({ id: lab.topology.id, name: "运行中改名" })),
  );
  expect(lab.locked).toBe(true);
  expect(lab.canRename).toBe(true);
  await lab.rename("运行中改名");
  await nextTick();
  expect(JSON.stringify(lab.runtime)).toBe(runtime);
  expect(lab.documentVersion).toBe(version);
  expect(editor.node?.id).toBe("r1");
  expect(terminals.active).toBe(tab);
  expect(terminals.tabs).toHaveLength(1);
});
it("keeps other unsaved topology and property changes when saving only the name", async () => {
  const lab = saved(),
    editor = useEditorStore();
  lab.moveNode("r1", { x: 900, y: 600 });
  editor.select({ type: "node", id: "r1" });
  editor.draft!.name = "PENDING";
  editor.touchDraft();
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(response({ id: lab.topology.id, name: "新名称" })),
  );
  await lab.rename("新名称");
  expect(lab.getNode("r1")?.x).toBe(900);
  expect(lab.dirty).toBe(true);
  expect(editor.draft!.name).toBe("PENDING");
  expect(editor.draftDirty).toBe(true);
});
it("keeps the old name and unlocks after a failed request", async () => {
  const lab = saved(),
    old = lab.topology.name;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(response({ error: "保存失败" }, 500)),
  );
  await expect(lab.rename("失败的改名")).rejects.toThrow("保存失败");
  expect(lab.topology.name).toBe(old);
  expect(lab.labs[0].name).toBe(old);
  expect(lab.operation).toBe("");
});
it("rejects invalid names and blocks rename during active operations", async () => {
  const lab = saved(),
    fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  for (const value of ["", "  ", "x".repeat(81), "a\0b"])
    await expect(lab.rename(value)).rejects.toThrow("项目名称");
  lab.busy = true;
  await expect(lab.rename("名称")).rejects.toThrow("等待");
  lab.busy = false;
  lab.operation = "save";
  await expect(lab.rename("名称")).rejects.toThrow("等待");
  expect(fetchMock).not.toHaveBeenCalled();
});
