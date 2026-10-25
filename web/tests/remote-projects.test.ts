import { createPinia, setActivePinia } from "pinia";
import { nextTick } from "vue";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import example from "../../examples/basic-lab.json";
import { useProjectFiles } from "../src/composables/useProjectFiles";
import { parseTopology } from "../src/domain/topology";
import { useLabStore } from "../src/stores/lab";
import { useEditorStore } from "../src/stores/editor";
import { useTerminalsStore } from "../src/stores/terminals";
import { useUiStore } from "../src/stores/ui";
import type { LabRecord } from "../src/types/lab";

const response = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const record = (id = "remote-project"): LabRecord => ({
  topology: { ...parseTopology(example), id },
  runtime: { phase: "idle", nodes: {}, logs: [] },
});

beforeEach(() => {
  setActivePinia(createPinia());
  vi.useFakeTimers();
  vi.stubGlobal("window", {
    confirm: vi.fn(() => true),
    location: { host: "10.8.126.103:5173" },
  });
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function running() {
  const lab = useLabStore(),
    editor = useEditorStore(),
    saved = record();
  saved.runtime = {
    phase: "running",
    deployment: "existing-deployment",
    nodes: { r1: { id: "existing-container", name: "router", pid: 42 } },
    logs: [],
  };
  lab.adopt(saved.topology, saved);
  lab.environment.ready = true;
  editor.select({ type: "node", id: "r1" });
  const terminals = useTerminalsStore();
  terminals.open("r1");
  return { lab, editor, terminals };
}

it("creates the project on the connected server before replacing the draft", async () => {
  const lab = useLabStore(),
    editor = useEditorStore(),
    created = record("server-generated-id");
  lab.adopt(parseTopology(example));
  editor.select({ type: "node", id: "r1" });
  editor.draft!.name = "unsaved-property";
  editor.touchDraft();
  created.topology.name = "远程 OSPF";
  let finish!: (value: Response) => void;
  const fetchMock = vi.fn(
    () => new Promise<Response>((resolve) => (finish = resolve)),
  );
  vi.stubGlobal("fetch", fetchMock);
  const previous = lab.topology.id,
    pending = lab.createProject(" 远程 OSPF ");
  expect(lab.topology.id).toBe(previous);
  expect(editor.draft!.name).toBe("unsaved-property");
  expect(lab.layoutLocked).toBe(true);
  expect(fetchMock.mock.calls[0]).toMatchObject([
    "/api/labs",
    { method: "POST", body: JSON.stringify({ name: "远程 OSPF" }) },
  ]);
  finish(response(created, 201));
  await pending;
  expect(lab.topology.id).toBe("server-generated-id");
  expect(lab.saved).toBe(true);
  expect(lab.dirty).toBe(false);
  expect(lab.labs[0]!.id).toBe("server-generated-id");
  expect(lab.serverHost).toBe("10.8.126.103:5173");
});

it("keeps the active project and properties if remote creation fails", async () => {
  const { lab, editor, terminals } = running();
  await nextTick();
  editor.draft!.name = "未保存名称";
  editor.touchDraft();
  const version = lab.documentVersion;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(response({ error: "创建失败" }, 500)),
  );
  await expect(lab.createProject("新项目")).rejects.toThrow("创建失败");
  expect(lab.documentVersion).toBe(version);
  expect(editor.draft!.name).toBe("未保存名称");
  expect(terminals.tabs).toHaveLength(1);
  expect(lab.operation).toBe("");
});

it("validates new names and blocks concurrent project operations before requests", async () => {
  const lab = useLabStore(),
    fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  await expect(lab.createProject("  ")).rejects.toThrow("项目名称");
  lab.busy = true;
  await expect(lab.createProject("新项目")).rejects.toThrow("等待");
  await expect(lab.load("another")).rejects.toThrow("等待");
  await expect(lab.closeProject()).rejects.toThrow("等待");
  expect(fetchMock).not.toHaveBeenCalled();
});

it("opens a saved server project through its lifecycle endpoint", async () => {
  const lab = useLabStore(),
    saved = record(),
    fetchMock = vi.fn().mockResolvedValue(response(saved));
  vi.stubGlobal("fetch", fetchMock);
  await lab.load(saved.topology.id);
  expect(fetchMock).toHaveBeenCalledWith(
    `/api/labs/${saved.topology.id}/open`,
    expect.objectContaining({ method: "POST", body: "{}" }),
  );
  expect(lab.topology.id).toBe(saved.topology.id);
  expect(lab.saved).toBe(true);
});

it("does not replace an active document when opening fails or returns late", async () => {
  const lab = useLabStore();
  lab.adopt(parseTopology(example));
  const current = lab.topology.id;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(response({ error: "打开失败" }, 500)),
  );
  await expect(lab.load("missing")).rejects.toThrow("打开失败");
  expect(lab.topology.id).toBe(current);
  let finish!: (value: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn(() => new Promise<Response>((resolve) => (finish = resolve))),
  );
  const pending = lab.load("remote-project");
  lab.adopt(record("new-current").topology);
  finish(response(record()));
  await expect(pending).rejects.toThrow("当前项目已变化");
  expect(lab.topology.id).toBe("new-current");
});

it("closes server sessions and clears the page without deleting or destroying the project", async () => {
  const { lab, terminals } = running();
  await nextTick();
  const fetchMock = vi
    .fn()
    .mockResolvedValue(response({ ok: true, id: lab.topology.id }));
  vi.stubGlobal("fetch", fetchMock);
  await useProjectFiles().closeProject();
  await nextTick();
  expect(fetchMock).toHaveBeenCalledOnce();
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/labs/remote-project/close",
    expect.objectContaining({ method: "POST", body: "{}" }),
  );
  expect(lab.topology.name).toBe("空白画布");
  expect(lab.topology.nodes).toHaveLength(0);
  expect(lab.saved).toBe(false);
  expect(lab.dirty).toBe(false);
  expect(terminals.tabs).toHaveLength(0);
  expect(useUiStore().notification?.message).toContain("运行设备已保留");
});

it("keeps unsaved properties and terminal tabs when close fails or is cancelled", async () => {
  const { lab, editor, terminals } = running();
  await nextTick();
  editor.draft!.name = "未保存设备";
  editor.touchDraft();
  const fetchMock = vi
    .fn()
    .mockResolvedValue(response({ error: "关闭失败" }, 500));
  vi.stubGlobal("fetch", fetchMock);
  vi.mocked(window.confirm).mockReturnValue(false);
  await useProjectFiles().closeProject();
  expect(fetchMock).not.toHaveBeenCalled();
  vi.mocked(window.confirm).mockReturnValue(true);
  await expect(useProjectFiles().closeProject()).rejects.toThrow("关闭失败");
  expect(editor.draft!.name).toBe("未保存设备");
  expect(editor.draftDirty).toBe(true);
  expect(lab.topology.id).toBe("remote-project");
  expect(terminals.tabs).toHaveLength(1);
});

it("ignores a late close response after the active document changes", async () => {
  const lab = useLabStore(),
    saved = record();
  lab.adopt(saved.topology, saved);
  let finish!: (value: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn(() => new Promise<Response>((resolve) => (finish = resolve))),
  );
  const pending = lab.closeProject();
  lab.adopt(record("new-current").topology);
  finish(response({ ok: true }));
  await expect(pending).rejects.toThrow("当前项目已变化");
  expect(lab.topology.id).toBe("new-current");
});

it("reports partial project saves while retaining topology success and active terminals", async () => {
  const { lab, editor, terminals } = running();
  await nextTick();
  lab.moveNode("r1", { x: 780, y: 240 });
  const version = lab.documentVersion,
    saved = record();
  saved.topology = parseTopology(lab.topology);
  saved.topology.nodes[0]!.config = "hostname SAVED";
  saved.runtime = lab.runtime!;
  const fetchMock = vi.fn().mockResolvedValue(
    response({
      record: saved,
      topology_saved: true,
      results: [
        {
          node: "r1",
          ok: true,
          config: "hostname SAVED",
          status: { supported: true, persisted: true },
        },
        { node: "r2", ok: false, error: "配置写入失败" },
        { node: "pc1", ok: false, skipped: true, error: "不支持运行配置保存" },
      ],
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  await useProjectFiles().save();
  await nextTick();
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/labs/remote-project/save",
    expect.objectContaining({ method: "POST" }),
  );
  expect(lab.getNode("r1")?.x).toBe(780);
  expect(lab.getNode("r1")?.config).toBe("hostname SAVED");
  expect(lab.dirty).toBe(false);
  expect(lab.saveWarning).toBe("部分设备配置未保存");
  expect(lab.documentVersion).toBe(version);
  expect(editor.node?.id).toBe("r1");
  expect(terminals.tabs).toHaveLength(1);
  const message = useUiStore().notification!;
  expect(message.error).toBe(true);
  expect(message.message).toContain("项目拓扑已保存到 10.8.126.103:5173");
  expect(message.message).toContain("1 台设备配置已保存");
  expect(message.message).toContain("不支持运行配置保存");
  expect(message.message).toContain("配置写入失败");
});

it("does not report unsupported runtime configuration as fully saved", async () => {
  const lab = useLabStore(),
    saved = record();
  lab.adopt(saved.topology, saved);
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      response({
        record: saved,
        topology_saved: true,
        results: [{ node: "pc1", ok: false, skipped: true, error: "不支持" }],
      }),
    ),
  );
  await useProjectFiles().save();
  expect(lab.saveWarning).toBe("部分设备仅保存拓扑");
  expect(useUiStore().notification?.message).toContain("仅保存拓扑");
});

it("retains edits after a failed save and rejects unapplied network changes", async () => {
  const { lab } = running();
  lab.moveNode("r1", { x: 900, y: 300 });
  const fetchMock = vi
    .fn()
    .mockResolvedValue(response({ error: "保存失败" }, 500));
  vi.stubGlobal("fetch", fetchMock);
  await expect(lab.saveProject()).rejects.toThrow("保存失败");
  expect(lab.getNode("r1")?.x).toBe(900);
  expect(lab.dirty).toBe(true);
  expect(lab.operation).toBe("");
  lab.topology.nodes[0]!.ports[0]!.address = "192.0.2.1/24";
  await expect(lab.saveProject()).rejects.toThrow("应用拓扑");
  expect(fetchMock).toHaveBeenCalledOnce();
});
