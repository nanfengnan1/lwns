import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { api, ApiError, getToken } from "../api/client";
import { useLabStore } from "./lab";

export interface CaptureSession {
  id: string;
  lab: string;
  link: string;
  side: "a" | "b";
  label: string;
  state:
    | "waiting"
    | "ready"
    | "starting"
    | "running"
    | "stopped"
    | "error"
    | "expired";
  filter: string;
  snaplen: number;
  bytes: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string;
  logs: string;
  client?: {
    status: "launched" | "error";
    output_file: string;
    manual_auth: boolean;
  } | null;
}
export const captureActive = (session: CaptureSession) =>
  ["waiting", "ready", "starting", "running"].includes(session.state);
export function captureURL(origin: string, ticket: string) {
  return (
    "lwns://capture?" +
    new URLSearchParams({ server: origin, ticket }).toString()
  );
}
export const configureCaptureURL = (origin: string) =>
  "lwns://configure?" + new URLSearchParams({ server: origin }).toString();
export function captureStatus(session: CaptureSession) {
  if (session.state === "ready" && session.client?.manual_auth)
    return "等待在 Wireshark 中认证";
  return {
    waiting: "等待打开本机程序",
    ready: session.client
      ? "Wireshark 已启动，等待 SSH"
      : "启动器已连接，正在打开 Wireshark",
    starting: "SSH 已连接，正在启动抓包",
    running: "抓包中",
    stopped: "已停止",
    error: "失败",
    expired: "连接已过期",
  }[session.state];
}
export const useCapturesStore = defineStore("captures", () => {
  const lab = useLabStore();
  const sessions = ref<CaptureSession[]>([]);
  const capabilities = ref({
    available: false,
    error: "正在检查抓包环境…",
    max_sessions: 8,
    max_duration: 3600,
  });
  const loading = ref(false),
    submitting = ref(false),
    launchURL = ref(""),
    launchId = ref("");
  const active = computed(() => sessions.value.filter(captureActive));
  let revision = 0;
  function reset() {
    revision++;
    sessions.value = [];
    launchURL.value = "";
    launchId.value = "";
  }
  async function refresh(environment = false) {
    if (loading.value || submitting.value) return;
    const id = lab.topology.id,
      current = revision;
    loading.value = true;
    try {
      if (environment)
        capabilities.value = await api<typeof capabilities.value>(
          "/api/capture/capabilities",
        );
      const result = lab.saved
        ? await api<CaptureSession[]>(`/api/labs/${id}/captures`)
        : [];
      if (current !== revision || id !== lab.topology.id) return;
      sessions.value = result;
      if (
        launchId.value &&
        !result.some((s) => s.id === launchId.value && s.state === "waiting")
      )
        launchURL.value = "";
    } finally {
      loading.value = false;
    }
  }
  async function start(
    link: string,
    side: "a" | "b",
    filter: string,
    snaplen: number,
  ) {
    if (submitting.value) throw Error("正在创建抓包会话");
    if (!lab.canCapture(link))
      throw Error("请先应用这条网线，等待设备运行就绪后再抓包");
    const id = lab.topology.id,
      current = ++revision;
    submitting.value = true;
    try {
      const result = await api<{ session: CaptureSession; ticket: string }>(
        `/api/labs/${id}/captures`,
        "POST",
        { link, side, filter, snaplen },
      );
      if (id !== lab.topology.id || current !== revision) {
        await api(`/api/labs/${id}/captures/${result.session.id}`, "DELETE");
        return "";
      }
      sessions.value.unshift(result.session);
      launchId.value = result.session.id;
      launchURL.value = captureURL(location.origin, result.ticket);
      return launchURL.value;
    } finally {
      submitting.value = false;
    }
  }
  async function stop(session: CaptureSession) {
    revision++;
    await api(`/api/labs/${session.lab}/captures/${session.id}`, "DELETE");
    if (launchId.value === session.id) launchURL.value = "";
    await refresh();
  }
  async function downloadClient() {
    const response = await fetch("/api/capture/client", {
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    if (!response.ok)
      throw new ApiError("启动器下载失败，请检查后端", response.status);
    const url = URL.createObjectURL(await response.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = "lwns-capture-client.zip";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return {
    sessions,
    capabilities,
    loading,
    submitting,
    launchURL,
    active,
    reset,
    refresh,
    start,
    stop,
    downloadClient,
  };
});
