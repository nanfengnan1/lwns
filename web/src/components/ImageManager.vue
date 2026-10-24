<script setup lang="ts">
import {
  computed,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  watch,
} from "vue";
import { useImagesStore } from "../stores/images";
import { useUiStore } from "../stores/ui";
import type { ImageEntry } from "../types/images";
import { deviceCategories } from "../domain/library";

const images = useImagesStore(),
  ui = useUiStore();
const dialog = ref<HTMLDialogElement>();
const query = ref(""),
  mode = ref<"address" | "archive" | "build">("address");
const file = ref<File>(),
  context = ref<File>();
const editing = ref<ImageEntry | null>(null);
const form = reactive({
  address: "",
  reference: "",
  dockerfile: "",
  title: "",
  template: "",
});
const edit = reactive({ title: "", template: "" });
const templates = [
  { id: "", title: "仅管理镜像" },
  ...deviceCategories.map((item) => ({
    id: item.template,
    title: item.description,
  })),
];
const sourceNames: Record<string, string> = {
  default: "默认清单",
  discovered: "宿主机已有",
  archive: "归档导入",
  url: "URL 下载",
  pull: "仓库拉取",
  build: "Dockerfile 构建",
};
const states = {
  queued: "等待中",
  running: "执行中",
  success: "已完成",
  error: "失败",
};
const filtered = computed(() =>
  images.data.images.filter((item) =>
    `${item.title} ${item.reference} ${item.image_id}`
      .toLowerCase()
      .includes(query.value.trim().toLowerCase()),
  ),
);
const present = computed(
  () => images.data.images.filter((item) => item.present).length,
);
const disabled = computed(() => images.busy || !images.data.available);
let timer: ReturnType<typeof setInterval> | undefined;
watch(
  () => ui.imagesOpen,
  (open) => {
    if (open) {
      dialog.value?.showModal();
      void ui.run(() => images.refresh(true));
    } else dialog.value?.close();
  },
  { flush: "post" },
);
onMounted(() => {
  timer = setInterval(() => {
    if ((ui.imagesOpen || images.data.busy) && !ui.accessOpen)
      void ui.run(() => images.refresh());
  }, 2000);
});
onBeforeUnmount(() => {
  clearInterval(timer);
  images.cancelUpload();
});
function size(value: number) {
  return value >= 1024 ** 3
    ? `${(value / 1024 ** 3).toFixed(1)} GiB`
    : `${(value / 1024 ** 2).toFixed(1)} MiB`;
}
function selected(event: Event) {
  return (event.target as HTMLInputElement).files?.[0];
}
async function readDockerfile(event: Event) {
  const value = selected(event);
  if (!value) return;
  if (value.size > 512 * 1024) throw Error("Dockerfile 不能超过 512 KiB");
  form.dockerfile = await value.text();
}
async function submit() {
  const metadata = { title: form.title, template: form.template };
  if (mode.value === "address") {
    const address = form.address.trim();
    if (!address) throw Error("请输入镜像地址");
    await images.start(
      /^https?:\/\//i.test(address)
        ? { ...metadata, mode: "url", url: address }
        : {
            ...metadata,
            mode: "pull",
            reference: address.replace(/^docker:\/\//i, ""),
          },
    );
  } else if (mode.value === "archive") {
    if (!file.value) throw Error("请选择 Docker 镜像归档");
    await images.start({ ...metadata, mode: "archive" }, file.value);
  } else {
    await images.start(
      {
        ...metadata,
        mode: "build",
        reference: form.reference.trim(),
        dockerfile: form.dockerfile,
      },
      context.value,
      "context",
    );
  }
  ui.notify("镜像任务已开始，可在下方查看进度和结果");
}
function startEdit(item: ImageEntry) {
  editing.value = item;
  edit.title = item.title;
  edit.template = item.template;
}
async function saveEdit() {
  if (!editing.value) return;
  await images.update(editing.value.id, edit.title, edit.template);
  editing.value = null;
  ui.notify("镜像设置已保存，设备库已更新");
}
async function remove(item: ImageEntry) {
  const message = item.present
    ? `删除本机镜像标签“${item.reference}”及其管理记录？若有其他标签，共享镜像层可能继续保留。被实验或容器使用的镜像不会删除。`
    : `移除已不存在的镜像“${item.reference}”的管理记录？`;
  if (!window.confirm(message)) return;
  await images.remove(item.id);
}
</script>

<template>
  <dialog
    id="image-manager"
    ref="dialog"
    @close="!dialog?.open && (ui.imagesOpen = false)"
    @cancel="ui.imagesOpen = false"
  >
    <div class="image-manager-heading">
      <div>
        <span class="dialog-eyebrow">IMAGE LIBRARY</span>
        <h2>镜像管理</h2>
        <p>导入镜像，选择设备模板，即可添加到画布。</p>
      </div>
      <div class="image-heading-actions">
        <button
          id="refresh-images"
          :disabled="images.loading || images.busy"
          @click="ui.run(() => images.refresh(true))"
        >
          {{ images.loading ? "刷新中…" : "刷新清单" }}
        </button>
        <button
          id="close-images"
          class="square"
          aria-label="关闭镜像管理"
          @click="ui.imagesOpen = false"
        >
          ×
        </button>
      </div>
    </div>
    <div v-if="images.data.error" class="image-environment-note" role="status">
      {{ images.data.error }}
    </div>
    <div class="image-manager-content">
      <section class="image-inventory" aria-label="镜像清单">
        <div class="image-list-heading">
          <b
            >本机镜像 <span>{{ present }}</span></b
          ><input
            id="image-search"
            v-model="query"
            type="search"
            placeholder="搜索名称、标签或 ID"
            aria-label="搜索镜像"
          />
        </div>
        <div class="image-list-scroll">
          <div
            v-for="item in filtered"
            :key="item.id"
            class="image-entry"
            :data-image="item.reference"
          >
            <div class="image-entry-top">
              <b :title="item.title">{{ item.title }}</b
              ><span class="image-status" :class="{ missing: !item.present }">{{
                item.present ? "已加载" : "未加载"
              }}</span>
            </div>
            <code class="image-reference">{{ item.reference }}</code>
            <div class="image-entry-meta">
              <span>{{ item.size || "—" }}</span
              ><span>{{
                sourceNames[item.source.type] || item.source.type
              }}</span
              ><span>{{
                templates.find((t) => t.id === item.template)?.title ||
                "仅管理镜像"
              }}</span>
            </div>
            <div class="image-entry-footer">
              <code :title="item.image_id">{{
                item.image_id
                  ? item.image_id.replace("sha256:", "").slice(0, 12)
                  : "等待导入"
              }}</code>
              <div>
                <button
                  class="image-settings"
                  :disabled="images.busy"
                  @click="startEdit(item)"
                >
                  设置</button
                ><button
                  class="image-delete delete-button"
                  :disabled="disabled"
                  @click="ui.run(() => remove(item))"
                >
                  {{ item.present ? "删除" : "移除记录" }}
                </button>
              </div>
            </div>
          </div>
          <div v-if="!filtered.length" class="image-empty">
            {{
              query
                ? "没有匹配的镜像"
                : "暂无镜像，从右侧添加或刷新宿主机清单。"
            }}
          </div>
        </div>
      </section>
      <section class="image-import" aria-label="添加或设置镜像">
        <form
          v-if="editing"
          id="image-edit-form"
          @submit.prevent="ui.run(saveEdit)"
        >
          <div class="image-form-heading">
            <h3>设备库设置</h3>
            <button type="button" @click="editing = null">返回导入</button>
          </div>
          <code class="image-reference">{{ editing.reference }}</code>
          <label class="field"
            ><span>显示名称</span
            ><input id="edit-image-title" v-model="edit.title" maxlength="80"
          /></label>
          <label class="field"
            ><span>设备类型</span
            ><select id="edit-image-template" v-model="edit.template">
              <option v-for="item in templates" :key="item.id" :value="item.id">
                {{ item.title }}
              </option>
            </select></label
          >
          <p class="image-help">
            选择兼容的模板后，已加载镜像会出现在左侧设备库。FRR 镜像需兼容
            /usr/lib/frr/docker-start；PC 和交换机需要 Linux 网络工具。
            防火墙使用 Linux Shell，镜像需自带防火墙工具，规则由终端配置。
          </p>
          <button
            id="save-image-settings"
            type="submit"
            class="primary"
            :disabled="images.busy"
          >
            保存设置
          </button>
        </form>
        <form v-else id="image-import-form" @submit.prevent="ui.run(submit)">
          <h3>添加镜像</h3>
          <div class="image-import-tabs" aria-label="镜像来源">
            <button
              v-for="tab in [
                { id: 'address', title: '镜像地址' },
                { id: 'archive', title: '镜像归档' },
                { id: 'build', title: 'Dockerfile' },
              ]"
              :key="tab.id"
              type="button"
              :data-image-mode="tab.id"
              :aria-pressed="mode === tab.id"
              :class="{ active: mode === tab.id }"
              :disabled="images.busy"
              @click="mode = tab.id as typeof mode"
            >
              {{ tab.title }}
            </button>
          </div>
          <fieldset :disabled="disabled">
            <template v-if="mode === 'address'">
              <label class="field"
                ><span>仓库镜像地址或归档 URL</span
                ><input
                  id="image-address"
                  v-model="form.address"
                  placeholder="alpine/frr:latest"
                  required
              /></label>
              <p class="image-help">
                支持 registry.example.com/router:tag，或指向 Docker 镜像归档的
                HTTP(S) 下载地址。私有仓库使用后端运行账户的 Docker 登录凭据。
              </p>
            </template>
            <template v-else-if="mode === 'archive'">
              <label class="field"
                ><span>选择本地镜像归档</span
                ><input
                  id="image-archive-file"
                  type="file"
                  accept=".tar,.gz,.xz,.bz2,.zst,.tgz,.txz"
                  required
                  @change="file = selected($event)"
              /></label>
              <p class="image-help">
                上传 docker save 生成的 .tar、.tar.xz
                等归档，自动恢复归档中的镜像和标签。
              </p>
              <p v-if="file" class="image-file-info">
                {{ file.name }} · {{ size(file.size) }}
              </p>
            </template>
            <template v-else>
              <label class="field"
                ><span>生成的镜像标签</span
                ><input
                  id="build-image-tag"
                  v-model="form.reference"
                  placeholder="my-router:1.0"
                  required
              /></label>
              <label class="field"
                ><span>加载 Dockerfile 文件</span
                ><input
                  id="dockerfile-file"
                  type="file"
                  @change="ui.run(() => readDockerfile($event))"
              /></label>
              <label class="field"
                ><span>Dockerfile 内容</span
                ><textarea
                  id="dockerfile-content"
                  v-model="form.dockerfile"
                  rows="6"
                  placeholder='FROM alpine:3.22&#10;RUN apk add --no-cache iproute2&#10;CMD ["sleep", "infinity"]'
                  required
                ></textarea>
              </label>
              <label class="field"
                ><span>构建上下文（可选）</span
                ><input
                  id="build-context-file"
                  type="file"
                  accept=".tar,.gz,.xz,.tgz,.txz,.zip"
                  @change="context = selected($event)"
              /></label>
              <p class="image-help">
                COPY/ADD 所需文件应放在上下文归档根目录。支持
                tar、tar.gz、tar.xz、zip；使用上方 Dockerfile
                覆盖归档根目录的同名文件。
              </p>
              <p v-if="context" class="image-file-info">
                {{ context.name }} · {{ size(context.size) }}
                <button type="button" @click="context = undefined">清除</button>
              </p>
            </template>
            <label class="field"
              ><span>显示名称（可选）</span
              ><input
                id="image-title"
                v-model="form.title"
                maxlength="80"
                placeholder="例如：实验用 FRR"
            /></label>
            <label class="field"
              ><span>添加到设备库</span
              ><select id="image-template" v-model="form.template">
                <option
                  v-for="item in templates"
                  :key="item.id"
                  :value="item.id"
                >
                  {{ item.title }}
                </option>
              </select></label
            >
            <p v-if="form.template" class="image-help">
              请确认镜像兼容所选模板；导入成功后会出现在对应设备分类。
            </p>
            <button id="start-image-job" type="submit" class="primary">
              {{
                images.submitting
                  ? "提交中…"
                  : mode === "build"
                    ? "构建镜像"
                    : "导入镜像"
              }}
            </button>
          </fieldset>
          <div v-if="images.uploading" class="image-upload-progress">
            <progress max="100" :value="images.uploadProgress"></progress
            ><span>上传 {{ images.uploadProgress }}%</span
            ><button type="button" @click="images.cancelUpload">
              取消上传
            </button>
          </div>
          <p class="image-help image-size-limit">
            单文件上限
            {{
              size(images.data.max_upload_bytes)
            }}。任务提交后，关闭窗口仍会继续执行。
          </p>
        </form>
      </section>
    </div>
    <section class="image-jobs" aria-label="镜像任务日志">
      <div class="image-job-heading">
        <h3>任务日志</h3>
        <select
          v-if="images.data.jobs.length"
          id="image-job-select"
          v-model="images.activeJob"
          aria-label="选择镜像任务"
        >
          <option
            v-for="item in images.data.jobs"
            :key="item.id"
            :value="item.id"
          >
            {{ item.created_at }} · {{ item.label }}
          </option></select
        ><span
          v-if="images.job"
          class="image-job-state"
          :class="images.job.state"
          >{{ states[images.job.state] }}</span
        >
      </div>
      <pre id="image-job-log" role="log">{{
        images.job?.logs || "导入、构建和删除任务的执行结果将在这里显示。"
      }}</pre>
    </section>
    <div class="image-manager-footer">
      <span>管理清单</span
      ><code :title="images.data.registry_path">{{
        images.data.registry_path || "连接后端后显示"
      }}</code>
    </div>
  </dialog>
</template>

<style scoped>
#image-manager {
  width: min(1080px, calc(100vw - 48px));
  max-width: none;
  height: min(880px, calc(100vh - 48px));
  max-height: calc(100vh - 48px);
  padding: 0;
  border: 1px solid var(--border);
  border-radius: 14px;
  color: #26334a;
  overflow: hidden;
}
#image-manager[open] {
  display: flex;
  flex-direction: column;
}
.image-manager-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 22px 24px 18px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.image-manager-heading h2 {
  font-size: 20px;
  margin: 3px 0 7px;
}
.image-manager-heading p,
.image-help {
  font-size: 11px;
  color: #8090a6;
  line-height: 1.7;
}
.image-heading-actions {
  display: flex;
  gap: 10px;
}
.image-heading-actions .square {
  font-size: 20px;
}
.image-environment-note {
  padding: 10px 24px;
  font-size: 11px;
  color: #936b2d;
  background: #fff8e9;
  flex-shrink: 0;
}
.image-manager-content {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 350px;
  min-height: 180px;
  flex: 1;
  overflow: hidden;
}
.image-inventory {
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 18px 22px 12px;
}
.image-list-heading {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.image-list-heading b {
  white-space: nowrap;
  font-size: 12px;
}
.image-list-heading b span {
  color: #7c8ca7;
  margin-left: 5px;
}
.image-list-heading input {
  width: 230px;
  font-size: 11px;
}
.image-list-scroll {
  overflow: auto;
  min-height: 0;
  padding-right: 5px;
}
.image-entry {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 13px 14px 9px;
  margin-bottom: 10px;
}
.image-entry-top {
  display: flex;
  gap: 12px;
  justify-content: space-between;
  align-items: center;
}
.image-entry-top b {
  font-size: 12px;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.image-status {
  white-space: nowrap;
  color: #299773;
  background: #edfaf5;
  padding: 3px 6px;
  border-radius: 4px;
  font-size: 10px;
}
.image-status.missing {
  color: #998059;
  background: #fff7e8;
}
.image-reference {
  display: block;
  overflow-wrap: anywhere;
  color: #536683;
  font-size: 11px;
  line-height: 1.6;
  margin: 7px 0;
}
.image-entry-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 5px 12px;
  color: #8b98ad;
  font-size: 10px;
}
.image-entry-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-top: 9px;
}
.image-entry-footer code {
  color: #a1acbb;
  font-size: 10px;
}
.image-entry-footer button {
  padding: 4px 9px;
  font-size: 11px;
  margin-left: 6px;
}
.image-import {
  border-left: 1px solid var(--border);
  background: #fafbfe;
  overflow-y: auto;
  padding: 18px 20px;
}
h3 {
  font-size: 12px;
  font-weight: 600;
  margin: 0;
}
.image-import-tabs {
  display: flex;
  padding: 3px;
  background: #eaf0f7;
  border-radius: 7px;
  margin: 14px 0 18px;
  gap: 3px;
}
.image-import-tabs button {
  flex: 1;
  border: 0;
  padding: 7px 4px;
  font-size: 11px;
  background: transparent;
}
.image-import-tabs button.active {
  background: white;
  color: var(--blue);
  box-shadow: 0 1px 3px #26334a12;
}
fieldset {
  border: 0;
  padding: 0;
  margin: 0;
  min-width: 0;
}
.field {
  margin: 14px 0;
}
.field span {
  font-size: 11px;
}
.field input[type="file"] {
  padding: 6px;
  font-size: 10px;
  background: white;
}
.image-import .primary {
  width: 100%;
  margin-top: 15px;
}
.image-file-info {
  font-size: 11px;
  overflow-wrap: anywhere;
  margin: 8px 0;
  color: #586d91;
}
.image-file-info button {
  padding: 1px 5px;
  font-size: 10px;
}
.image-size-limit {
  margin-top: 14px;
}
.image-upload-progress {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-top: 12px;
  font-size: 11px;
}
.image-upload-progress progress {
  width: 100%;
  accent-color: var(--blue);
}
.image-form-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 15px;
}
.image-form-heading button {
  font-size: 10px;
  padding: 4px 7px;
}
.image-jobs {
  border-top: 1px solid var(--border);
  padding: 12px 22px 14px;
  flex-shrink: 0;
}
.image-job-heading {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 9px;
}
.image-job-heading select {
  flex: 1;
  padding: 5px 8px;
  font-size: 10px;
}
.image-job-state {
  font-size: 10px;
  color: #7990b0;
}
.image-job-state.success {
  color: #299773;
}
.image-job-state.error {
  color: #c35959;
}
#image-job-log {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  overflow: auto;
  height: 112px;
  background: #18243a;
  color: #c4d3e9;
  border-radius: 6px;
  margin: 0;
  padding: 11px 13px;
  font:
    11px/1.6 Consolas,
    monospace;
}
.image-manager-footer {
  display: flex;
  gap: 10px;
  color: #96a2b5;
  font-size: 10px;
  padding: 10px 22px;
  border-top: 1px solid var(--border);
  background: #fafbfe;
  flex-shrink: 0;
}
.image-manager-footer span {
  white-space: nowrap;
}
.image-manager-footer code {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.image-empty {
  padding: 50px 12px;
  text-align: center;
  color: #94a1b6;
  font-size: 12px;
}
</style>
