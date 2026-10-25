import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import example from "../../examples/basic-lab.json";
import { useProjectFiles } from "../src/composables/useProjectFiles";
import { useLabStore } from "../src/stores/lab";
import { useEditorStore } from "../src/stores/editor";
import { useUiStore } from "../src/stores/ui";
import { parseTopology } from "../src/domain/topology";

beforeEach(() => {
  setActivePinia(createPinia());
  vi.useFakeTimers();
  vi.stubGlobal("window", { confirm: vi.fn(() => true) });
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
const file = (value: unknown) => ({
  size: 200,
  text: async () => JSON.stringify(value),
});
const response = (value: unknown) =>
  new Response(JSON.stringify(value), { status: 200 });

it("opens a topology JSON as an unsaved draft without creating backend files", async () => {
  const lab = useLabStore(),
    fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  await useProjectFiles().importFile(file(example));
  expect(lab.topology.nodes).toHaveLength(5);
  expect(lab.topology.name).toBe(example.name);
  expect(lab.saved).toBe(false);
  expect(lab.dirty).toBe(true);
  expect(fetchMock).not.toHaveBeenCalled();
});

it("keeps the current experiment and inspector draft when import is cancelled", async () => {
  const lab = useLabStore(),
    editor = useEditorStore();
  lab.adopt(parseTopology(example));
  editor.select({ type: "node", id: "r1" });
  editor.draft!.name = "unsaved-device";
  editor.touchDraft();
  const version = lab.documentVersion;
  vi.mocked(window.confirm).mockReturnValue(false);
  await useProjectFiles().importFile(file({ ...example, id: "another-lab" }));
  expect(lab.documentVersion).toBe(version);
  expect(editor.draft!.name).toBe("unsaved-device");
  expect(editor.draftDirty).toBe(true);
});

it("rejects oversized and malformed input before replacing the active experiment", async () => {
  const lab = useLabStore(),
    actions = useProjectFiles(),
    version = lab.documentVersion;
  const text = vi.fn();
  await expect(
    actions.importFile({ size: 1024 * 1024 + 1, text }),
  ).rejects.toThrow("1 MiB");
  expect(text).not.toHaveBeenCalled();
  await expect(
    actions.importFile({ size: 2, text: async () => "{" }),
  ).rejects.toThrow();
  await expect(actions.importFile(file({ version: 99 }))).rejects.toThrow();
  expect(lab.documentVersion).toBe(version);
  expect(window.confirm).not.toHaveBeenCalled();
});

it("does not apply a delayed file read over a newly opened project", async () => {
  const lab = useLabStore(),
    actions = useProjectFiles();
  let finish!: (text: string) => void;
  const pending = actions.importFile({
    size: 200,
    text: () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  });
  lab.newLab("新的实验");
  const id = lab.topology.id;
  finish(JSON.stringify(example));
  await expect(pending).rejects.toThrow("当前实验已变化");
  expect(lab.topology.id).toBe(id);
  expect(lab.topology.name).toBe("新的实验");
});

it("refuses to adopt an imported file if another operation starts during reading", async () => {
  const lab = useLabStore(),
    actions = useProjectFiles();
  let finish!: (text: string) => void;
  const pending = actions.importFile({
    size: 200,
    text: () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  });
  const id = lab.topology.id;
  lab.operation = "save";
  finish(JSON.stringify(example));
  await expect(pending).rejects.toThrow("当前实验已变化");
  expect(lab.topology.id).toBe(id);
});

it("saves pending device properties to the host through the shared menu and toolbar action", async () => {
  const lab = useLabStore(),
    editor = useEditorStore();
  lab.adopt(parseTopology(example));
  editor.select({ type: "node", id: "r1" });
  editor.draft!.name = "R1-edited";
  editor.touchDraft();
  const fetchMock = vi.fn(async (url: string, init: RequestInit) => {
    if (url === "/api/labs") return response([]);
    return response({
      topology: JSON.parse(init.body as string),
      runtime: { phase: "idle", nodes: {}, logs: [] },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  await useProjectFiles().save();
  expect(lab.getNode("r1")?.name).toBe("R1-edited");
  expect(lab.saved).toBe(true);
  expect(editor.unsaved).toBe(false);
  expect(fetchMock.mock.calls[0]![1].method).toBe("PUT");
  expect(useUiStore().notification?.message).toContain("当前宿主机");
});

it("saves only layout for a deployed experiment and preserves its runtime identity", async () => {
  const lab = useLabStore(),
    topology = parseTopology(example);
  lab.adopt(topology, {
    topology,
    runtime: {
      phase: "running",
      deployment: "existing-run",
      nodes: {},
      logs: [],
    },
  });
  lab.moveNode("r1", { x: 700, y: 400 });
  const version = lab.documentVersion,
    fetchMock = vi
      .fn()
      .mockResolvedValue(
        response({ topology: lab.topology, runtime: lab.runtime }),
      );
  vi.stubGlobal("fetch", fetchMock);
  await useProjectFiles().save();
  expect(fetchMock.mock.calls[0][0]).toBe(`/api/labs/${topology.id}`);
  expect(fetchMock.mock.calls[0][1].method).toBe("PUT");
  expect(lab.runtime?.deployment).toBe("existing-run");
  expect(lab.documentVersion).toBe(version);
  expect(lab.dirty).toBe(false);
  expect(useUiStore().notification?.message).toContain("布局");
});

it("exports topology data without pretending to include runtime, images or shared files", async () => {
  const lab = useLabStore();
  lab.adopt(parseTopology(example));
  const anchor = { href: "", download: "", click: vi.fn() };
  vi.stubGlobal("document", { createElement: vi.fn(() => anchor) });
  const create = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test");
  const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  useProjectFiles().exportFile();
  const value = JSON.parse(await (create.mock.calls[0]![0] as Blob).text());
  expect(value.nodes).toHaveLength(5);
  expect(value.runtime).toBeUndefined();
  expect(value.images).toBeUndefined();
  expect(anchor.download).toBe(lab.topology.id + ".json");
  expect(anchor.click).toHaveBeenCalledOnce();
  expect(useUiStore().notification?.message).toContain("共享目录与镜像不包含");
  vi.advanceTimersByTime(1000);
  expect(revoke).toHaveBeenCalledWith("blob:test");
});
