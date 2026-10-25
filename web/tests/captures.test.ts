import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import {
  captureURL,
  captureStatus,
  configureCaptureURL,
  useCapturesStore,
  type CaptureSession,
} from "../src/stores/captures";
import { useLabStore } from "../src/stores/lab";
import { api } from "../src/api/client";
import example from "../../examples/basic-lab.json";
import { parseTopology } from "../src/domain/topology";
vi.mock("../src/api/client", () => ({
  api: vi.fn(),
  getToken: () => "token",
  ApiError: class extends Error {},
}));
const session = {
  id: "capture1",
  lab: "lab1",
  link: "l1",
  side: "a",
  label: "R1 / eth0",
  state: "waiting",
  bytes: 0,
  error: "",
  logs: "",
};
describe("capture sessions", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.mocked(api).mockReset();
    const lab = useLabStore(),
      topology = parseTopology({ ...example, id: "lab1" });
    lab.adopt(topology, {
      topology,
      runtime: {
        phase: "running",
        deployment: "run",
        logs: [],
        nodes: Object.fromEntries(
          topology.nodes.map((node, i) => [
            node.id,
            { id: "container-" + node.id, name: node.name, pid: i + 1 },
          ]),
        ),
      },
    });
    lab.environment.ready = true;
    vi.stubGlobal("location", { origin: "http://host:8090" });
  });
  it("launch URL contains only the origin and a short-lived ticket", () => {
    const url = new URL(captureURL("http://host:8090", "ticket"));
    expect(url.protocol).toBe("lwns:");
    expect([...url.searchParams.keys()]).toEqual(["server", "ticket"]);
  });
  it("distinguishes manual authentication from a running capture", () => {
    const pending = {
      ...session,
      state: "ready",
      client: {
        status: "launched",
        output_file: "C:/capture.pcapng",
        manual_auth: true,
      },
    } as CaptureSession;
    expect(captureStatus(pending)).toBe("等待在 Wireshark 中认证");
    expect(captureStatus({ ...pending, state: "running" })).toBe("抓包中");
    const setup = new URL(configureCaptureURL("http://host:8090"));
    expect(setup.hostname).toBe("configure");
    expect([...setup.searchParams.keys()]).toEqual(["server"]);
  });
  it("does not mark a launch attempt as a running capture", async () => {
    const lab = useLabStore(),
      captures = useCapturesStore();
    lab.topology.id = "lab1";
    vi.mocked(api).mockResolvedValueOnce({ session, ticket: "test-ticket" });
    expect(await captures.start("l1", "a", "icmp", 128)).toContain("lwns:");
    expect(captures.sessions[0]?.state).toBe("waiting");
    expect(api).toHaveBeenCalledWith("/api/labs/lab1/captures", "POST", {
      link: "l1",
      side: "a",
      filter: "icmp",
      snaplen: 128,
    });
  });
  it("stops a late-created session after switching laboratories", async () => {
    const lab = useLabStore(),
      captures = useCapturesStore();
    lab.topology.id = "lab1";
    let resolve!: (value: unknown) => void;
    vi.mocked(api).mockImplementationOnce(
      () =>
        new Promise((r) => {
          resolve = r;
        }),
    );
    const pending = captures.start("l1", "a", "", 0);
    lab.topology.id = "lab2";
    captures.reset();
    resolve({ session, ticket: "old" });
    await pending;
    expect(api).toHaveBeenCalledWith(
      "/api/labs/lab1/captures/capture1",
      "DELETE",
    );
    expect(captures.launchURL).toBe("");
    expect(captures.sessions).toEqual([]);
  });
  it("does not let an earlier refresh overwrite a newly created session", async () => {
    const lab = useLabStore(),
      captures = useCapturesStore();
    lab.topology.id = "lab1";
    lab.saved = true;
    let resolve!: (value: unknown) => void;
    vi.mocked(api).mockImplementationOnce(
      () =>
        new Promise((r) => {
          resolve = r;
        }),
    );
    const refresh = captures.refresh();
    vi.mocked(api).mockResolvedValueOnce({ session, ticket: "new" });
    await captures.start("l1", "a", "", 0);
    resolve([]);
    await refresh;
    expect(captures.sessions[0]?.id).toBe("capture1");
  });
});
