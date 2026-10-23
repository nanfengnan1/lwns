<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import { api } from "../api/client";
import { useUiStore } from "../stores/ui";
import type { TerminalTab } from "../stores/terminals";

const props = defineProps<{ tab: TerminalTab; active: boolean }>();
const emit = defineEmits<{ state: [value: TerminalTab["state"]] }>();
const host = ref<HTMLElement>();
const ui = useUiStore();
let terminal: Terminal | undefined,
  fit: FitAddon | undefined,
  socket: WebSocket | undefined;
let observer: ResizeObserver | undefined,
  generation = 0,
  disposed = false;
let fitFrame = 0,
  connectTimer: ReturnType<typeof setTimeout> | undefined;
let connected = false;

function send(message: object) {
  if (socket?.readyState === WebSocket.OPEN)
    socket.send(JSON.stringify(message));
}
function resize() {
  if (
    !host.value ||
    !terminal ||
    !fit ||
    host.value.clientWidth < 20 ||
    host.value.clientHeight < 20
  )
    return;
  fit.fit();
  if (connected)
    send({ type: "resize", cols: terminal.cols, rows: terminal.rows });
}
function scheduleResize() {
  cancelAnimationFrame(fitFrame);
  fitFrame = requestAnimationFrame(resize);
}
function disconnect() {
  generation++;
  clearTimeout(connectTimer);
  connected = false;
  const previous = socket;
  socket = undefined;
  if (previous) {
    previous.onopen =
      previous.onmessage =
      previous.onclose =
      previous.onerror =
        null;
    previous.close();
  }
}
async function connect() {
  disconnect();
  const version = generation;
  terminal?.reset();
  terminal?.writeln("\x1b[90m正在连接设备…\x1b[0m");
  emit("state", "connecting");
  try {
    const { ticket } = await api<{ ticket: string }>(
      `/api/labs/${props.tab.lab}/terminals`,
      "POST",
      { node: props.tab.node, mode: props.tab.mode },
    );
    if (disposed || version !== generation) return;
    const url = new URL("/api/terminal", location.href);
    url.protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(url);
    socket = ws;
    ws.binaryType = "arraybuffer";
    connectTimer = setTimeout(() => {
      if (version !== generation) return;
      terminal?.writeln("\r\n连接超时，请检查后端或代理是否支持 WebSocket。");
      ws.close();
    }, 12000);
    ws.onopen = () => {
      resize();
      send({
        type: "connect",
        ticket,
        cols: terminal?.cols || 80,
        rows: terminal?.rows || 24,
      });
    };
    ws.onmessage = (event: MessageEvent) => {
      if (event.data instanceof ArrayBuffer) {
        terminal?.write(new Uint8Array(event.data), () => {
          if (socket === ws && ws.readyState === WebSocket.OPEN)
            ws.send(JSON.stringify({ type: "ack" }));
        });
        return;
      }
      const message = JSON.parse(event.data as string);
      if (message.type === "ready") {
        clearTimeout(connectTimer);
        connected = true;
        emit("state", "connected");
        resize();
        if (props.active) terminal?.focus();
      } else if (message.type === "error")
        terminal?.writeln(`\r\n\x1b[31m${message.message}\x1b[0m`);
      else if (message.type === "exit")
        terminal?.writeln(`\r\n[会话已结束，退出码 ${message.code}]`);
    };
    ws.onerror = () =>
      terminal?.writeln("\r\n无法连接终端，请确认后端已更新并支持 WebSocket。");
    ws.onclose = () => {
      clearTimeout(connectTimer);
      connected = false;
      emit("state", "disconnected");
      terminal?.writeln(
        "\r\n\x1b[90m连接已断开，可点击「重连」建立新会话。\x1b[0m",
      );
    };
  } catch (error) {
    if (disposed || version !== generation) return;
    emit("state", "disconnected");
    terminal?.writeln(`\r\n${error instanceof Error ? error.message : error}`);
    ui.report(error);
  }
}
function clear() {
  terminal?.clear();
  terminal?.focus();
}
onMounted(() => {
  terminal = new Terminal({
    cursorBlink: true,
    fontSize: 13,
    fontFamily: '"Cascadia Code", Consolas, monospace',
    scrollback: 3000,
    theme: {
      background: "#142137",
      foreground: "#dbe7f5",
      cursor: "#9bb9ff",
      selectionBackground: "#3b5379",
    },
  });
  fit = new FitAddon();
  terminal.loadAddon(fit);
  terminal.open(host.value!);
  terminal.onData((data) => {
    if (!connected) return;
    // Chunk pasted input without splitting Unicode surrogate pairs.
    let chunk = "";
    for (const char of data) {
      chunk += char;
      if (chunk.length >= 4096) {
        send({ type: "input", data: chunk });
        chunk = "";
      }
    }
    if (chunk) send({ type: "input", data: chunk });
  });
  observer = new ResizeObserver(scheduleResize);
  observer.observe(host.value!);
  resize();
  void connect();
});
watch(
  () => props.active,
  async (active) => {
    if (active) {
      await nextTick();
      resize();
      terminal?.focus();
    }
  },
);
onBeforeUnmount(() => {
  disposed = true;
  disconnect();
  observer?.disconnect();
  cancelAnimationFrame(fitFrame);
  terminal?.dispose();
});
defineExpose({ connect, clear });
</script>

<template>
  <div class="device-terminal" :data-terminal="tab.node" @keydown.stop>
    <div
      ref="host"
      class="terminal-screen"
      :aria-label="`${tab.name} 交互终端`"
    ></div>
  </div>
</template>
