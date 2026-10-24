<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import {
  captureActive,
  captureStatus,
  configureCaptureURL,
  useCapturesStore,
} from "../stores/captures";
import { useLabStore } from "../stores/lab";
import { useUiStore } from "../stores/ui";
const lab = useLabStore(),
  ui = useUiStore(),
  captures = useCapturesStore();
const dialog = ref<HTMLDialogElement>(),
  side = ref<"a" | "b">("a"),
  filter = ref(""),
  snaplen = ref(0);
const configureURL = configureCaptureURL(location.origin);
const link = computed(() =>
  lab.topology.links.find((l) => l.id === ui.captureLink),
);
const pending = computed(() =>
  captures.sessions.some(
    (s) =>
      s.link === ui.captureLink &&
      s.side === side.value &&
      ["waiting", "ready", "starting"].includes(s.state),
  ),
);
const canStart = computed(
  () =>
    !!link.value &&
    lab.saved &&
    !!lab.runtime?.deployment &&
    !lab.busy &&
    !lab.operation &&
    captures.capabilities.available &&
    !captures.submitting &&
    !pending.value,
);
let timer: ReturnType<typeof setInterval> | undefined;
function syncDialog(open: boolean) {
  if (open) {
    dialog.value?.showModal();
    void ui.run(() => captures.refresh(true));
  } else dialog.value?.close();
}
watch(() => ui.captureOpen, syncDialog, { flush: "post" });
watch(
  () => ui.captureLink,
  () => {
    side.value = "a";
  },
);
watch(
  () => lab.topology.id,
  () => {
    captures.reset();
    ui.captureOpen = false;
  },
);
onMounted(() => {
  syncDialog(ui.captureOpen);
  timer = setInterval(() => {
    if ((ui.captureOpen || captures.active.length) && !ui.accessOpen)
      void ui.run(() => captures.refresh());
  }, 2000);
});
onBeforeUnmount(() => clearInterval(timer));
async function start() {
  if (!link.value) return;
  const url = await captures.start(
    link.value.id,
    side.value,
    filter.value,
    snaplen.value,
  );
  if (url)
    ui.notify("会话已准备，请点击“打开本机 Wireshark”并允许浏览器打开应用");
}
async function copyPath(path: string) {
  if (navigator.clipboard && window.isSecureContext)
    await navigator.clipboard.writeText(path);
  else {
    // Private-network HTTP pages do not have the modern clipboard API.
    const field = document.createElement("textarea");
    field.value = path;
    field.style.cssText = "position:fixed;opacity:0;pointer-events:none";
    dialog.value?.appendChild(field);
    field.select();
    const copied = document.execCommand("copy");
    field.remove();
    if (!copied) throw Error("浏览器未允许复制，请选中路径手动复制");
  }
  ui.notify("已复制本机抓包文件路径");
}
</script>

<template>
  <dialog
    id="capture-manager"
    ref="dialog"
    aria-labelledby="capture-title"
    @close="!dialog?.open && (ui.captureOpen = false)"
    @cancel="ui.captureOpen = false"
  >
    <header class="capture-heading">
      <div>
        <small>PACKET CAPTURE</small>
        <h2 id="capture-title">Wireshark 实时抓包</h2>
        <p>选择网线一端，在使用浏览器的电脑上查看并保存报文。</p>
      </div>
      <button
        id="close-captures"
        aria-label="关闭抓包窗口"
        class="square"
        @click="ui.captureOpen = false"
      >
        ×
      </button>
    </header>
    <div class="capture-body">
      <section>
        <div class="capture-section-title">
          <h3><span class="step-number">1</span>设置抓包</h3>
          <a id="configure-capture-client" :href="configureURL"
            >本机连接与保存设置 ↗</a
          >
        </div>
        <form class="capture-form" @submit.prevent="ui.run(start)">
          <label class="field"
            ><span>抓包端点</span
            ><select id="capture-side" v-model="side" :disabled="!link">
              <option
                v-for="key in ['a', 'b'] as const"
                :key="key"
                :value="key"
              >
                {{
                  link
                    ? lab.getNode(link[key].node)?.name + " / " + link[key].port
                    : "请先选择连线"
                }}
              </option>
            </select></label
          >
          <label class="field"
            ><span>每包抓取长度</span
            ><select id="capture-snaplen" v-model="snaplen">
              <option :value="0">完整报文</option>
              <option :value="128">128 字节</option>
              <option :value="512">512 字节</option>
              <option :value="1500">1500 字节</option>
            </select></label
          >
          <label class="field capture-filter-field"
            ><span>抓包过滤条件 <small>BPF · 可选</small></span
            ><input
              id="capture-filter"
              v-model="filter"
              maxlength="1024"
              placeholder="例如 arp or icmp，留空抓取全部流量"
          /></label>
          <div class="capture-form-actions">
            <span>{{
              pending
                ? "此端点已有待连接会话，请完成下方连接或先停止。"
                : "准备后，点击下一步的按钮打开本机程序。"
            }}</span
            ><button
              id="start-capture"
              class="primary"
              type="submit"
              :disabled="!canStart"
            >
              {{ captures.submitting ? "准备中…" : "准备抓包" }}
            </button>
          </div>
        </form>
        <p
          v-if="!captures.capabilities.available"
          class="capture-warning"
          role="status"
        >
          {{ captures.capabilities.error }}
        </p>
      </section>

      <section v-if="captures.launchURL" class="capture-launch" role="status">
        <div>
          <h3><span class="step-number">2</span>打开本机 Wireshark</h3>
          <p>
            点击右侧按钮，并允许浏览器打开应用。首次使用会显示本地设置窗口。
          </p>
          <p>凭证 5 分钟内有效。没有弹窗可再次点击，无需重复创建会话。</p>
        </div>
        <a
          id="capture-launch-link"
          class="capture-launch-button"
          :href="captures.launchURL"
          >打开本机 Wireshark ↗</a
        >
      </section>

      <div class="capture-session-heading">
        <h3>
          抓包会话
          <span class="capture-count">{{ captures.sessions.length }}</span>
        </h3>
        <button
          id="refresh-captures"
          :disabled="captures.loading"
          @click="ui.run(() => captures.refresh(true))"
        >
          刷新
        </button>
      </div>
      <div class="capture-sessions" aria-live="polite">
        <p v-if="!captures.sessions.length" class="capture-empty">
          还没有抓包会话，先选择端点并准备抓包。
        </p>
        <article
          v-for="session in captures.sessions"
          :key="session.id"
          class="capture-session"
          :data-capture="session.id"
        >
          <div class="capture-session-top">
            <b>{{ session.label }}</b
            ><span :class="['capture-state', session.state]">{{
              captureStatus(session)
            }}</span
            ><button
              v-if="captureActive(session)"
              class="stop-capture"
              @click="ui.run(() => captures.stop(session))"
            >
              停止
            </button>
          </div>
          <dl class="capture-metrics">
            <div>
              <dt>过滤条件</dt>
              <dd>{{ session.filter || "全部流量" }}</dd>
            </div>
            <div>
              <dt>已接收</dt>
              <dd>{{ (session.bytes / 1024).toFixed(1) }} KiB</dd>
            </div>
            <div>
              <dt>抓取长度</dt>
              <dd>
                {{ session.snaplen ? session.snaplen + " 字节" : "完整报文" }}
              </dd>
            </div>
          </dl>
          <p v-if="session.state === 'waiting'" class="capture-next">
            尚未连接本地启动器。点击上方“打开本机
            Wireshark”；未安装时先下载并安装启动器。
          </p>
          <div v-if="session.state === 'ready'" class="capture-next">
            <template v-if="session.client?.manual_auth"
              ><b>密码认证无需私钥，请在 Wireshark 内完成：</b>
              <ol>
                <li>在首页找到 SSH remote capture，点击旁边的齿轮。</li>
                <li>切换到 Authentication，填写远程用户名和密码。</li>
                <li>点击 Start 开始抓包，连接成功后这里会变为“抓包中”。</li>
              </ol></template
            >
            <template v-else-if="session.client"
              >Wireshark 已启动，正在等待 SSH 数据连接。若持续等待，请查看本机
              Wireshark 的 SSH 错误或认证设置。</template
            >
            <template v-else
              >启动器已领取会话，尚未确认 Wireshark
              启动。请查看任务栏及本地错误弹窗；旧版启动器不会回传启动结果，请重新下载安装。</template
            >
          </div>
          <div class="capture-output">
            <span>本机保存文件</span
            ><template v-if="session.client?.output_file"
              ><code>{{ session.client.output_file }}</code
              ><button
                class="copy-capture-path"
                @click="ui.run(() => copyPath(session.client!.output_file))"
              >
                复制路径</button
              ><small
                >启动时指定的路径；成功开始后写入。若在 Wireshark
                中修改路径或另存，以 Wireshark 为准。</small
              ></template
            >
            <p v-else>
              等待新版启动器报告路径。旧版需在 Wireshark 中使用“文件 →
              另存为”指定保存位置。
            </p>
          </div>
          <p v-if="session.error" class="capture-warning">
            {{ session.error }}
          </p>
          <details v-if="session.logs" class="capture-logs">
            <summary>查看抓包日志</summary>
            <pre>{{ session.logs }}</pre>
          </details>
        </article>
      </div>

      <details class="capture-setup">
        <summary>安装、密码登录与保存位置</summary>
        <div class="capture-setup-grid">
          <div>
            <h4>本机安装一次</h4>
            <p>
              安装 Wireshark 及 SSH remote
              capture（sshdump），下载并解压启动器。更新后需要再次运行安装脚本。
            </p>
            <button
              id="download-capture-client"
              @click="ui.run(captures.downloadClient)"
            >
              下载本地启动器
            </button>
            <p>Windows：运行 install.ps1<br />Linux：运行 bash install.sh</p>
            <a :href="configureURL">打开本机连接与保存设置 ↗</a>
          </div>
          <div>
            <h4>用户名 + 密码即可</h4>
            <p>
              私钥可以留空。不勾选“自动开始”时，在 Wireshark 的 SSH 接口配置 →
              Authentication 中输入密码，再开始抓包。
            </p>
            <p>
              已有可用 Profile
              或密钥认证时，可启用自动开始。密码不会上传到工作台。
            </p>
          </div>
          <div>
            <h4>文件保存在本机</h4>
            <p>
              新版默认保存到当前用户主目录下的
              <code>route-ovs/captures</code>，每次使用独立子目录及
              <code>capture.pcapng</code>。可在本地设置中修改目录。
            </p>
            <p>
              会话显示完整目标路径。文件在浏览器所在电脑上，Linux Docker
              宿主机不保留副本。
            </p>
          </div>
        </div>
      </details>
    </div>
    <footer class="capture-footer">
      关闭本窗口后，已连接的抓包继续运行。每次最多 60
      分钟；停止抓包或清理设备会结束会话，已写入的本机文件保留。
    </footer>
  </dialog>
</template>

<style scoped>
#capture-manager {
  width: min(880px, calc(100vw - 40px));
  max-width: none;
  max-height: calc(100dvh - 40px);
  padding: 0;
  overflow: hidden;
}
#capture-manager[open] {
  display: flex;
  flex-direction: column;
}
.capture-heading {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
  padding: 22px 26px 18px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.capture-heading small {
  color: var(--blue);
  letter-spacing: 2px;
  font-size: 10px;
}
.capture-heading h2 {
  margin: 6px 0 5px;
  font-size: 21px;
}
.capture-heading p {
  margin: 0;
  color: #6c7c92;
}
.capture-heading button {
  flex-shrink: 0;
}
.capture-body {
  padding: 22px 26px;
  overflow-y: auto;
  min-height: 0;
}
h3 {
  font-size: 14px;
  margin: 0;
  color: #354b69;
}
.capture-section-title,
.capture-session-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.capture-section-title h3,
.capture-launch h3 {
  display: flex;
  align-items: center;
  gap: 9px;
}
a {
  color: var(--blue);
  font-size: 12px;
  text-decoration: none;
}
a:hover {
  text-decoration: underline;
}
.step-number {
  width: 22px;
  height: 22px;
  display: inline-grid;
  place-items: center;
  border-radius: 50%;
  background: #eaf0ff;
  color: var(--blue);
  font-size: 12px;
  flex-shrink: 0;
}
.capture-form {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 16px;
  margin-top: 18px;
}
.capture-form .field {
  margin: 0;
  min-width: 0;
}
.capture-form .field > span {
  font-size: 12px;
  color: #52657f;
  margin-bottom: 7px;
}
.capture-form .field small {
  display: inline;
  font-size: 11px;
  color: #8a98aa;
  margin-left: 6px;
}
.capture-form input,
.capture-form select {
  display: block;
  width: 100%;
  min-width: 0;
  height: 38px;
  margin: 0;
  font-size: 12px;
  padding: 8px 10px;
}
.capture-filter-field,
.capture-form-actions {
  grid-column: 1 / -1;
}
.capture-form-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.capture-form-actions > span {
  font-size: 12px;
  color: #718198;
  line-height: 1.6;
}
.capture-form-actions .primary {
  margin: 0;
  width: auto;
  min-width: 120px;
  min-height: 36px;
  flex-shrink: 0;
}
.capture-launch {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 20px;
  margin: 20px 0;
  padding: 16px;
  background: #f0f5ff;
  border: 1px solid #dbe6fc;
  border-radius: 9px;
}
.capture-launch p {
  color: #607795;
  font-size: 12px;
  line-height: 1.7;
  margin: 8px 0 0;
}
.capture-launch-button {
  padding: 11px 14px;
  border-radius: 6px;
  background: var(--blue);
  color: #fff;
  font-weight: 600;
  white-space: nowrap;
}
.capture-session-heading {
  margin: 24px 0 12px;
}
.capture-count {
  margin-left: 6px;
  font-weight: 400;
  color: #8795aa;
}
.capture-empty {
  padding: 24px;
  text-align: center;
  background: #f7f9fc;
  border: 1px dashed var(--border);
  border-radius: 8px;
  color: #718198;
}
.capture-session {
  border: 1px solid var(--border);
  border-radius: 9px;
  padding: 16px;
  margin-bottom: 12px;
  font-size: 12px;
}
.capture-session-top {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 10px;
}
.capture-session-top b {
  font-size: 13px;
  overflow-wrap: anywhere;
}
.capture-state {
  font-size: 11px;
  line-height: 1.5;
  padding: 4px 8px;
  border-radius: 5px;
  color: #687b97;
  background: #edf1f7;
}
.capture-state.running {
  color: #1d8061;
  background: #e7f6ef;
}
.capture-state.ready,
.capture-state.waiting {
  color: #8c661d;
  background: #fff5dd;
}
.capture-state.error,
.capture-state.expired {
  color: #b14e3f;
  background: #fff0ec;
}
.stop-capture {
  min-width: 56px;
}
.capture-metrics {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr) minmax(0, 1fr);
  gap: 12px;
  margin: 15px 0;
}
.capture-metrics dt {
  color: #8190a5;
  font-size: 11px;
  margin-bottom: 5px;
}
.capture-metrics dd {
  margin: 0;
  color: #4d617e;
  overflow-wrap: anywhere;
  font-variant-numeric: tabular-nums;
}
.capture-next {
  padding: 12px;
  border-radius: 6px;
  background: #f7f9fc;
  line-height: 1.8;
  font-size: 12px;
  color: #5f7390;
  margin: 12px 0;
}
.capture-next ol {
  margin: 6px 0 0;
  padding-left: 20px;
}
.capture-output {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  border-top: 1px solid #eaf0f7;
  padding-top: 12px;
}
.capture-output > span {
  grid-column: 1 / -1;
  font-size: 11px;
  color: #718198;
}
.capture-output code {
  overflow-wrap: anywhere;
  align-self: center;
  user-select: text;
  color: #445c7c;
  font-size: 11px;
  line-height: 1.6;
}
.capture-output small,
.capture-output p {
  grid-column: 1 / -1;
  font-size: 11px;
  line-height: 1.7;
  margin: 0;
  color: #8695a9;
}
.capture-output button {
  align-self: start;
  white-space: nowrap;
}
.capture-warning {
  color: #b05444;
  font-size: 12px;
  overflow-wrap: anywhere;
  margin: 12px 0 0;
}
.capture-logs {
  margin-top: 12px;
}
summary {
  cursor: pointer;
  color: #526986;
  font-size: 12px;
}
.capture-session pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 180px;
  overflow-y: auto;
  font-size: 11px;
  line-height: 1.6;
  padding: 12px;
  background: #18263d;
  color: #e2e9f5;
  border-radius: 6px;
}
.capture-setup {
  padding: 15px;
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-top: 20px;
  background: #fafbfe;
}
.capture-setup-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 20px;
  margin-top: 14px;
}
.capture-setup h4 {
  font-size: 12px;
  margin: 0 0 8px;
}
.capture-setup p {
  font-size: 12px;
  line-height: 1.8;
  color: #6c7e97;
  margin: 8px 0;
}
.capture-setup code {
  overflow-wrap: anywhere;
  font-size: 11px;
}
.capture-footer {
  padding: 13px 26px;
  border-top: 1px solid var(--border);
  background: #fafbfe;
  color: #7a8ba3;
  font-size: 11px;
  line-height: 1.7;
  flex-shrink: 0;
}
@media (max-width: 760px) {
  .capture-heading,
  .capture-body {
    padding: 18px;
  }
  .capture-setup-grid,
  .capture-launch {
    grid-template-columns: 1fr;
  }
  .capture-section-title,
  .capture-form-actions {
    align-items: flex-start;
    flex-direction: column;
  }
  .capture-form-actions .primary {
    width: 100%;
  }
  .capture-session-top {
    grid-template-columns: minmax(0, 1fr) auto;
  }
  .capture-session-top b {
    grid-column: 1 / -1;
  }
  .capture-launch-button {
    text-align: center;
  }
}
</style>
