import { createPinia, setActivePinia } from "pinia";
import { nextTick } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import example from "../../examples/basic-lab.json";
import { api, ApiError, setToken } from "../src/api/client";
import { clone, parseTopology } from "../src/domain/topology";
import { useLabStore } from "../src/stores/lab";
import { useEditorStore } from "../src/stores/editor";
import { useTerminalsStore } from "../src/stores/terminals";
import type {
  Bootstrap,
  LabRecord,
  LabSummary,
  Runtime,
} from "../src/types/lab";

const idle = (): Runtime => ({ phase: "idle", nodes: {}, logs: [] });
const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });
function setup() {
  const lab = useLabStore(),
    editor = useEditorStore();
  lab.adopt(parseTopology(example));
  return { lab, editor };
}
beforeEach(() => {
  setActivePinia(createPinia());
  setToken("test-token");
});
afterEach(() => vi.unstubAllGlobals());

describe("explicit experiment opening", () => {
  const metadata = (labs: LabSummary[] = []): Bootstrap => ({
    catalog: [
      {
        kind: "router",
        title: "FRR",
        image: "alpine/frr:latest",
        ports: 4,
        prefix: "R",
      },
    ],
    environment: { ready: false, preview: true, errors: [], images: [] },
    labs,
  });

  it.each([false, true])(
    "starts with a clean canvas without opening or creating an experiment (saved experiments: %s)",
    async (hasSavedLabs) => {
      const lab = useLabStore(),
        editor = useEditorStore();
      const data = metadata(
        hasSavedLabs
          ? [
              {
                id: "existing-lab",
                name: "Existing",
                nodes: 5,
                phase: "running",
              },
            ]
          : [],
      );
      const fetchMock = vi.fn().mockResolvedValue(response(data));
      vi.stubGlobal("fetch", fetchMock);

      expect(lab.topology.name).toBe("空白画布");
      expect(editor.unsaved).toBe(false);
      await lab.bootstrap();

      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(fetchMock.mock.calls[0][0]).toBe("/api/bootstrap");
      expect(lab.catalog).toEqual(data.catalog);
      expect(lab.environment).toEqual(data.environment);
      expect(lab.labs).toEqual(data.labs);
      expect(lab.topology.nodes).toEqual([]);
      expect(lab.topology.links).toEqual([]);
      expect(lab.saved).toBe(false);
      expect(editor.unsaved).toBe(false);
      expect(lab.runtime).toBe(null);
      expect(lab.canDeploy).toBe(false);
      expect(lab.operation).toBe("");
    },
  );

  it("opens the chosen saved experiment only after an explicit load", async () => {
    const lab = useLabStore(),
      editor = useEditorStore();
    const record: LabRecord = {
      topology: parseTopology(example),
      runtime: idle(),
    };
    const data = metadata([
      {
        id: record.topology.id,
        name: record.topology.name,
        nodes: record.topology.nodes.length,
        phase: "idle",
      },
    ]);
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response(data))
      .mockResolvedValueOnce(response(record));
    vi.stubGlobal("fetch", fetchMock);

    await lab.bootstrap();
    expect(lab.topology.nodes).toHaveLength(0);
    await lab.load(record.topology.id);

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/bootstrap",
      `/api/labs/${record.topology.id}`,
    ]);
    expect(lab.topology).toEqual(record.topology);
    expect(lab.saved).toBe(true);
    expect(editor.unsaved).toBe(false);
    expect(lab.runtime).toEqual(record.runtime);
  });

  it("preserves unsaved edits and selection when authentication refreshes metadata", async () => {
    const { lab, editor } = setup();
    editor.select({ type: "node", id: "r1" });
    editor.draft!.name = "PENDING";
    editor.touchDraft();
    const topology = lab.topology,
      documentVersion = lab.documentVersion;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(metadata())));

    await lab.bootstrap();

    expect(lab.topology).toBe(topology);
    expect(lab.documentVersion).toBe(documentVersion);
    expect(editor.selected).toEqual({ type: "node", id: "r1" });
    expect(editor.draft!.name).toBe("PENDING");
    expect(editor.draftDirty).toBe(true);
    expect(editor.unsaved).toBe(true);
  });

  it("treats an explicitly created empty experiment as a draft", () => {
    const lab = useLabStore(),
      editor = useEditorStore();
    const placeholderId = lab.topology.id;

    lab.newLab("路由测试");

    expect(lab.topology.id).not.toBe(placeholderId);
    expect(lab.topology.name).toBe("路由测试");
    expect(lab.topology.nodes).toEqual([]);
    expect(lab.saved).toBe(false);
    expect(editor.unsaved).toBe(true);
  });
});

describe("editor and deployment state", () => {
  it("commits pending form input when selecting another device", () => {
    const { lab, editor } = setup();
    editor.select({ type: "node", id: "pc1" });
    editor.draft!.name = "RENAMED";
    editor.touchDraft();
    editor.select({ type: "node", id: "r1" });
    expect(lab.getNode("pc1")?.name).toBe("RENAMED");
    expect(editor.node?.id).toBe("r1");
  });
  it("keeps selection and topology intact when a draft is invalid", () => {
    const { lab, editor } = setup();
    editor.select({ type: "node", id: "r1" });
    editor.portCount = 1;
    editor.touchDraft();
    expect(() => editor.select({ type: "node", id: "pc1" })).toThrow(
      "仍有网线",
    );
    expect(editor.node?.id).toBe("r1");
    expect(lab.getNode("r1")?.ports).toHaveLength(4);
  });
  it("keeps live canvas coordinates when applying an older properties draft", async () => {
    const { lab, editor } = setup();
    editor.select({ type: "node", id: "r1" });
    lab.moveNode("r1", { x: 600, y: 400 });
    await nextTick();
    editor.draft!.name = "ROUTER";
    editor.touchDraft();
    editor.commitDraft();
    expect(lab.getNode("r1")).toMatchObject({ name: "ROUTER", x: 600, y: 400 });
  });
  it("allows deployed topology edits but retains the deployment guard", async () => {
    const { lab } = setup();
    lab.runtime = { ...idle(), phase: "running", deployment: "owned" };
    expect(() => lab.moveNode("r1", { x: 1, y: 1 })).not.toThrow();
    expect(() => lab.autoAlign()).not.toThrow();
    expect(() => lab.addAnnotation({ x: 0, y: 0 })).not.toThrow();
    expect(() => lab.setLinkOptimization(false)).not.toThrow();
    expect(() =>
      lab.updateNode({ ...lab.getNode("r1")!, name: "CHANGED" }),
    ).not.toThrow();
    expect(() =>
      lab.connect({ node: "r1", port: "eth2" }, { node: "sw1", port: "eth2" }),
    ).not.toThrow();
    expect(() => lab.remove("node", "r1")).not.toThrow();
    expect(lab.canDeploy).toBe(false);
    await expect(lab.deleteLab()).rejects.toThrow("清理");
  });
  it("saves deployed layout without replacing devices, runtime, selection or terminal state", async () => {
    const { lab, editor } = setup();
    lab.saved = true;
    lab.runtime = {
      ...idle(),
      phase: "running",
      deployment: "owned",
      nodes: { r1: { id: "container-r1", name: "R1", pid: 123 } },
    };
    lab.environment.ready = true;
    const terminals = useTerminalsStore();
    terminals.open("r1");
    terminals.tabs[0].state = "connected";
    const tab = terminals.tabs[0],
      active = terminals.active;
    editor.select({ type: "node", id: "r1" });
    lab.moveNode("r1", { x: -300, y: 900 });
    const runtime = lab.runtime,
      node = lab.getNode("r1"),
      version = lab.documentVersion;
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        response({ topology: clone(lab.topology), runtime: lab.runtime }),
      );
    vi.stubGlobal("fetch", fetchMock);
    await lab.save();
    await nextTick();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`/api/labs/${lab.topology.id}`);
    expect(init.method).toBe("PUT");
    const payload = JSON.parse(init.body);
    expect(payload).toEqual(lab.topology);
    expect(payload.nodes[0]).toMatchObject({ id: "r1", x: -300, y: 900 });
    expect(lab.getNode("r1")).toEqual(node);
    expect(lab.runtime).toBe(runtime);
    expect(lab.documentVersion).toBe(version);
    expect(terminals.tabs).toHaveLength(1);
    expect(terminals.tabs[0]).toBe(tab);
    expect(terminals.tabs[0].state).toBe("connected");
    expect(terminals.active).toBe(active);
    expect(editor.selected).toEqual({ type: "node", id: "r1" });
    expect(lab.dirty).toBe(false);
    lab.moveNode("r1", { x: 0, y: 0 });
    fetchMock.mockResolvedValueOnce(response({ error: "保存失败" }, 400));
    await expect(lab.save()).rejects.toThrow("保存失败");
    expect(lab.dirty).toBe(true);
    expect(lab.operation).toBe("");
  });
  it("blocks layout changes and saving during deployment, cleanup and pending operations", async () => {
    const { lab } = setup();
    for (const phase of ["deploying", "updating", "destroying"] as const) {
      lab.runtime = { ...idle(), phase, deployment: "owned" };
      expect(() => lab.moveNode("r1", { x: 1, y: 2 })).toThrow();
      expect(() => lab.autoAlign()).toThrow();
      await expect(lab.save()).rejects.toThrow();
    }
    lab.runtime = { ...idle(), phase: "running", deployment: "owned" };
    lab.operation = "save-config";
    expect(() => lab.setLinkOptimization(false)).toThrow();
  });
  it("clears transient selection and pending cable when changing documents", () => {
    const { lab, editor } = setup();
    editor.choosePort({ node: "r1", port: "eth2" });
    editor.draft!.name = "UNSAVED";
    editor.touchDraft();
    lab.newLab();
    expect(editor.selected).toBe(null);
    expect(editor.pending).toBe(null);
    expect(editor.draftDirty).toBe(false);
    expect(lab.topology.nodes).toHaveLength(0);
  });
  it("discards an unsaved imported draft without deleting a same-ID server record", async () => {
    const { lab, editor } = setup();
    const id = lab.topology.id;
    lab.labs = [{ id, name: "Saved original", nodes: 5, phase: "idle" }];
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    editor.choosePort({ node: "r1", port: "eth2" });
    editor.draft!.name = "invalid name!";
    editor.touchDraft();
    await lab.deleteLab();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(lab.labs).toHaveLength(1);
    expect(lab.labs[0].id).toBe(id);
    expect(lab.topology.id).not.toBe(id);
    expect(lab.topology.nodes).toEqual([]);
    expect(lab.topology.links).toEqual([]);
    expect(lab.saved).toBe(false);
    expect(lab.runtime).toBe(null);
    expect(editor.selected).toBe(null);
    expect(editor.pending).toBe(null);
    expect(editor.draft).toBe(null);
    expect(editor.unsaved).toBe(false);
  });
  it("removes only the current saved lab and resets to a clean empty canvas", async () => {
    const { lab, editor } = setup();
    const id = lab.topology.id;
    lab.saved = true;
    lab.labs = [
      { id, name: "Current", nodes: 5, phase: "idle" },
      { id: "other", name: "Other", nodes: 2, phase: "idle" },
    ];
    let release!: (value: Response) => void;
    const fetchMock = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const deleting = lab.deleteLab();
    expect(lab.locked).toBe(true);
    expect(lab.topology.nodes).toHaveLength(5);
    expect(fetchMock.mock.calls[0]).toMatchObject([
      `/api/labs/${id}`,
      { method: "DELETE" },
    ]);
    release(response({}));
    await deleting;
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(lab.labs.map((item) => item.id)).toEqual(["other"]);
    expect(lab.topology.nodes).toEqual([]);
    expect(editor.unsaved).toBe(false);
    expect(lab.saved).toBe(false);
    expect(lab.locked).toBe(false);
  });
  it("preserves the lab and pending properties if deletion fails", async () => {
    const { lab, editor } = setup();
    const original = clone(lab.topology);
    lab.saved = true;
    lab.labs = [
      { id: original.id, name: original.name, nodes: 5, phase: "idle" },
    ];
    editor.select({ type: "node", id: "r1" });
    editor.draft!.name = "PENDING";
    editor.touchDraft();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(response({ error: "删除失败" }, 500)),
    );
    await expect(lab.deleteLab()).rejects.toThrow("删除失败");
    expect(lab.topology).toEqual(original);
    expect(lab.labs).toHaveLength(1);
    expect(lab.saved).toBe(true);
    expect(editor.draft!.name).toBe("PENDING");
    expect(editor.draftDirty).toBe(true);
    expect(lab.locked).toBe(false);
  });
  it("blocks deleting saved or unsaved labs while locked", async () => {
    const { lab } = setup();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    for (const saved of [false, true]) {
      lab.saved = saved;
      lab.runtime = { ...idle(), phase: "running", deployment: "owned" };
      await expect(lab.deleteLab()).rejects.toThrow("清理设备");
      lab.runtime = null;
      lab.busy = true;
      await expect(lab.deleteLab()).rejects.toThrow("等待");
      lab.busy = false;
      lab.operation = "save";
      await expect(lab.deleteLab()).rejects.toThrow("等待");
      lab.operation = "";
    }
    expect(fetchMock).not.toHaveBeenCalled();
    expect(lab.topology.nodes).toHaveLength(5);
  });
  it("serializes a save and includes pending properties in the API payload", async () => {
    const { lab, editor } = setup();
    editor.select({ type: "node", id: "pc1" });
    editor.draft!.name = "SAVED";
    editor.touchDraft();
    editor.commitDraft();
    let release!: (value: Response) => void;
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            release = resolve;
          }),
      )
      .mockResolvedValueOnce(response([]));
    vi.stubGlobal("fetch", fetchMock);
    const pending = lab.save();
    expect(lab.locked).toBe(true);
    await expect(lab.save()).rejects.toThrow("等待");
    const payload = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(payload.nodes.find((n: { id: string }) => n.id === "pc1").name).toBe(
      "SAVED",
    );
    release(response({ topology: payload, runtime: idle() }));
    await pending;
    expect(lab.saved).toBe(true);
    expect(editor.unsaved).toBe(false);
    expect(lab.locked).toBe(false);
  });
  it("ignores a late runtime response after switching experiments", async () => {
    const { lab } = setup();
    lab.saved = true;
    const oldRecord: LabRecord = {
      topology: clone(lab.topology),
      runtime: { ...idle(), phase: "error", error: "old lab" },
    };
    let release!: (value: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>((resolve) => {
            release = resolve;
          }),
      ),
    );
    const pending = lab.refresh();
    lab.newLab();
    release(response(oldRecord));
    await pending;
    expect(lab.runtime).toBe(null);
    expect(lab.topology.nodes).toHaveLength(0);
  });
  it("does not let an old idle response unlock a newly started deployment", async () => {
    const { lab } = setup();
    lab.saved = true;
    lab.dirty = false;
    lab.environment.ready = true;
    let release!: (value: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementationOnce(
          () =>
            new Promise<Response>((resolve) => {
              release = resolve;
            }),
        )
        .mockResolvedValueOnce(
          response({
            runtime: { ...idle(), phase: "deploying", deployment: "new-run" },
          }),
        ),
    );
    const refresh = lab.refresh();
    await lab.startJob("deploy");
    release(
      response({ topology: clone(lab.topology), runtime: idle(), busy: false }),
    );
    await refresh;
    expect(lab.runtime?.deployment).toBe("new-run");
    expect(lab.busy).toBe(true);
    expect(lab.locked).toBe(true);
  });
  it("updates deployment state without overwriting the editor draft", async () => {
    const { lab, editor } = setup();
    lab.saved = true;
    editor.select({ type: "node", id: "r1" });
    editor.draft!.name = "DRAFT";
    editor.touchDraft();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        response({
          topology: clone(lab.topology),
          runtime: idle(),
          busy: false,
        }),
      ),
    );
    await lab.refresh();
    await nextTick();
    expect(editor.draft!.name).toBe("DRAFT");
    expect(editor.draftDirty).toBe(true);
  });
  it("tracks deployment and cleanup jobs through the unchanged API", async () => {
    const { lab } = setup();
    lab.saved = true;
    lab.dirty = false;
    lab.environment.ready = true;
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        response({
          runtime: { ...idle(), phase: "deploying", deployment: "run" },
        }),
      )
      .mockResolvedValueOnce(
        response({
          runtime: { ...idle(), phase: "running", deployment: "run" },
          topology: clone(lab.topology),
          busy: false,
        }),
      )
      .mockResolvedValueOnce(
        response({
          runtime: { ...idle(), phase: "destroying", deployment: "run" },
        }),
      )
      .mockResolvedValueOnce(
        response({
          topology: clone(lab.topology),
          runtime: idle(),
          busy: false,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    await lab.startJob("deploy");
    expect(lab.busy).toBe(true);
    expect(lab.locked).toBe(true);
    await lab.refresh();
    expect(lab.canDestroy).toBe(true);
    await lab.startJob("destroy");
    expect(lab.busy).toBe(true);
    await lab.refresh();
    expect(lab.locked).toBe(false);
    expect(lab.phase).toBe("idle");
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/deploy$/);
    expect(fetchMock.mock.calls[2][0]).toMatch(/\/destroy$/);
  });
});

describe("API authentication", () => {
  it("sends the bearer token and retains unauthorized status for the login dialog", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(response({ error: "请输入令牌" }, 401));
    vi.stubGlobal("fetch", fetchMock);
    await expect(api("/api/bootstrap")).rejects.toMatchObject({
      status: 401,
      message: "请输入令牌",
    });
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe(
      "Bearer test-token",
    );
  });
  it("explains a dev proxy returning HTML instead of silently accepting it", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response("<html>Missing backend</html>", { status: 502 }),
        ),
    );
    await expect(api("/api/bootstrap")).rejects.toBeInstanceOf(ApiError);
  });
});
