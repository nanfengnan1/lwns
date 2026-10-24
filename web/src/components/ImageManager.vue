<script setup lang="ts">
import {
  computed,
  nextTick,
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
  mode = ref<"address" | "archive" | "build" | "local">("address");
const status = ref<"all" | "present" | "missing">("all");
const logOpen = ref(false),
  logElement = ref<HTMLPreElement>();
const followLogs = ref(true);
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
  local: "已有镜像引用",
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
  images.data.images.filter(
    (item) =>
      (status.value === "all" ||
        item.present === (status.value === "present")) &&
      `${item.title} ${item.reference} ${item.image_id}`
        .toLowerCase()
        .includes(query.value.trim().toLowerCase()),
  ),
);
const present = computed(
  () => images.data.images.filter((item) => item.present).length,
);
const inLibrary = computed(
  () =>
    images.data.images.filter((item) => item.present && item.template).length,
);
const disabled = computed(() => images.busy || !images.data.available);
let timer: ReturnType<typeof setInterval> | undefined;
function syncDialog(open: boolean) {
  if (open) {
    dialog.value?.showModal();
    void ui.run(() => images.refresh(true));
  } else dialog.value?.close();
}
watch(() => ui.imagesOpen, syncDialog, { flush: "post" });
onMounted(() => {
  syncDialog(ui.imagesOpen);
  timer = setInterval(() => {
    if ((ui.imagesOpen || images.data.busy) && !ui.accessOpen)
      void ui.run(() => images.refresh());
  }, 2000);
});
onBeforeUnmount(() => {
  clearInterval(timer);
  images.cancelUpload();
});
watch(
  () => images.data.busy,
  (busy) => {
    if (busy) logOpen.value = true;
  },
);
watch(
  () => images.job?.id,
  () => {
    followLogs.value = true;
  },
);
watch(
  () => images.job?.logs,
  async () => {
    if (!followLogs.value) return;
    await nextTick();
    if (logElement.value)
      logElement.value.scrollTop = logElement.value.scrollHeight;
  },
);
watch(
  () => images.data.images,
  (items) => {
    if (editing.value && !items.some((item) => item.id === editing.value?.id))
      editing.value = null;
  },
);
function trackLogScroll() {
  const element = logElement.value;
  if (element)
    followLogs.value =
      element.scrollHeight - element.scrollTop - element.clientHeight < 32;
}
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
  if (mode.value === "local") {
    await images.start({
      ...metadata,
      mode: "local",
      reference: form.address.trim(),
    });
  } else if (mode.value === "address") {
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
  logOpen.value = true;
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
async function remove(item: ImageEntry, deleteLocal = item.can_delete) {
  const message = deleteLocal
    ? `删除本机镜像标签“${item.reference}”及其管理记录？若有其他标签，共享镜像层可能继续保留。被实验或容器使用的镜像不会删除。`
    : `将“${item.reference}”移出管理清单和设备库？本地 Docker 镜像与已有实验会保留。`;
  if (!window.confirm(message)) return;
  await images.remove(item.id, deleteLocal);
  logOpen.value = true;
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
        <p>管理实验用镜像，选择设备类型后添加到设备库。</p>
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
    <div class="image-scope-note">
      <span class="image-scope-dot"></span
      >仅显示项目管理的镜像。刷新不会自动纳入宿主机其他镜像。
    </div>
    <div v-if="images.data.error" class="image-environment-note" role="status">
      {{ images.data.error }}
    </div>
    <div class="image-manager-content">
      <section class="image-inventory" aria-label="镜像清单">
        <div class="image-list-heading">
          <h3>
            我的镜像 <span>{{ images.data.images.length }}</span>
          </h3>
          <input
            id="image-search"
            v-model="query"
            type="search"
            placeholder="搜索名称、标签或 ID"
            aria-label="搜索镜像"
          />
        </div>
        <div class="image-overview">
          <span
            ><strong>{{ present }}</strong> 已加载</span
          >
          <span
            ><strong>{{ images.data.images.length - present }}</strong>
            待加载</span
          >
          <span
            ><strong>{{ inLibrary }}</strong> 设备库可用</span
          >
        </div>
        <div class="image-filters" aria-label="镜像状态筛选">
          <button
            v-for="filter in [
              { id: 'all', title: '全部' },
              { id: 'present', title: '已加载' },
              { id: 'missing', title: '待加载' },
            ]"
            :key="filter.id"
            :data-image-filter="filter.id"
            :aria-pressed="status === filter.id"
            :class="{ active: status === filter.id }"
            @click="status = filter.id as typeof status"
          >
            {{ filter.title }}
          </button>
          <span>{{ filtered.length }} 个结果</span>
        </div>
        <div class="image-list-scroll">
          <div
            v-for="item in filtered"
            :key="item.id"
            class="image-entry"
            :class="{ selected: editing?.id === item.id }"
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
              <span
                v-if="item.present && !item.can_delete"
                class="image-protected"
                title="该镜像的本地文件受到保护，只能移出项目管理清单"
                >仅引用 · 保留本地</span
              >
            </div>
            <div class="image-entry-footer">
              <code :title="item.image_id">{{
                item.image_id
                  ? item.image_id.replace("sha256:", "").slice(0, 12)
                  : "等待导入"
              }}</code>
              <div>
                <button
                  v-if="item.can_delete"
                  class="image-forget"
                  :disabled="disabled"
                  @click="ui.run(() => remove(item, false))"
                >
                  移出清单
                </button>
                <button
                  class="image-settings"
                  :disabled="images.busy"
                  @click="startEdit(item)"
                >
                  设置</button
                ><button
                  class="image-delete"
                  :class="{ 'delete-button': item.can_delete }"
                  :disabled="disabled"
                  @click="ui.run(() => remove(item))"
                >
                  {{ item.can_delete ? "删除镜像" : "移出清单" }}
                </button>
              </div>
            </div>
          </div>
          <div v-if="!filtered.length" class="image-empty">
            {{
              query || status !== "all"
                ? "没有匹配的镜像"
                : "还没有管理的镜像，从右侧导入或添加已有镜像。"
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
          <p class="image-help">选择来源，再设置名称与设备类型。</p>
          <div class="image-import-tabs" aria-label="镜像来源">
            <button
              v-for="tab in [
                { id: 'address', title: '仓库 / URL' },
                { id: 'archive', title: '上传归档' },
                { id: 'build', title: 'Dockerfile' },
                { id: 'local', title: '已有镜像' },
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
            <template v-if="mode === 'local'">
              <label class="field"
                ><span>本机镜像名称与标签</span
                ><input
                  id="local-image-reference"
                  v-model="form.address"
                  placeholder="my-router:latest"
                  required
              /></label>
              <p class="image-help">
                填写宿主机已有镜像的完整名称与标签，将其加入管理清单。保留本地镜像，只允许移出清单。
              </p>
            </template>
            <template v-else-if="mode === 'address'">
              <label class="field"
                ><span>仓库镜像地址或归档 URL</span
                ><input
                  id="image-address"
                  v-model="form.address"
                  placeholder="alpine/frr:latest"
                  required
              /></label>
              <p class="image-help">
                支持 registry.example.com/router:tag，或指向未压缩 .tar
                镜像归档的 HTTP(S) 下载地址。私有仓库使用后端运行账户的 Docker
                登录凭据。
              </p>
            </template>
            <template v-else-if="mode === 'archive'">
              <label class="field"
                ><span>选择本地镜像归档</span
                ><input
                  id="image-archive-file"
                  type="file"
                  accept=".tar"
                  required
                  @change="file = selected($event)"
              /></label>
              <p class="image-help">
                仅支持 docker save 生成的未压缩 .tar 文件，直接调用 Docker
                加载。 .tar.gz、.tar.xz 等压缩文件请先在本地解压。
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
                  : mode === "local"
                    ? "加入管理清单"
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
    <section
      class="image-jobs"
      :class="{ collapsed: !logOpen }"
      aria-label="镜像任务日志"
    >
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
        <button
          id="toggle-image-log"
          :aria-expanded="logOpen"
          aria-controls="image-job-log"
          @click="logOpen = !logOpen"
        >
          {{ logOpen ? "收起日志" : "展开日志" }}
        </button>
      </div>
      <pre
        v-show="logOpen"
        id="image-job-log"
        ref="logElement"
        role="log"
        @scroll="trackLogScroll"
        >{{
          images.job?.logs || "导入、构建和删除任务的执行结果将在这里显示。"
        }}</pre>
    </section>
    <div class="image-manager-footer">
      <span>移出清单保留本地镜像；删除镜像仅适用于本项目创建的标签。</span>
      <details>
        <summary>清单位置</summary>
        <code :title="images.data.registry_path">{{
          images.data.registry_path || "连接后端后显示"
        }}</code>
      </details>
    </div>
  </dialog>
</template>

<style scoped>
#image-manager {
  width: min(1200px, calc(100vw - 40px));
  max-width: none;
  height: min(900px, calc(100vh - 40px));
  max-height: calc(100vh - 40px);
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
  padding: 18px 24px 14px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.image-manager-heading h2 {
  font-size: 20px;
  margin: 3px 0 7px;
}
.image-manager-heading p,
.image-help {
  font-size: 12px;
  color: #61718a;
  line-height: 1.7;
}
.image-heading-actions {
  display: flex;
  gap: 10px;
  flex-shrink: 0;
}
.image-scope-note {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 24px;
  background: #f0f6fc;
  color: #496580;
  font-size: 12px;
  flex-shrink: 0;
}
.image-scope-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #3983c3;
  flex-shrink: 0;
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
  grid-template-columns: minmax(0, 1fr) 380px;
  min-height: 180px;
  flex: 1;
  overflow: hidden;
}
.image-inventory {
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
  padding: 18px 22px 12px;
}
.image-list-heading {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.image-list-heading h3 {
  white-space: nowrap;
  font-size: 12px;
}
.image-list-heading h3 span {
  color: #7c8ca7;
  margin-left: 5px;
  background: #edf2f8;
  border-radius: 5px;
  padding: 2px 6px;
}
.image-list-heading input {
  width: 230px;
  min-width: 0;
  max-width: 65%;
  font-size: 12px;
}
.image-overview {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}
.image-overview > span {
  padding: 10px 12px;
  background: #f6f8fc;
  border: 1px solid #e7edf5;
  border-radius: 8px;
  color: #65748b;
  font-size: 11px;
}
.image-overview strong {
  color: #263e60;
  font-size: 20px;
  margin-right: 5px;
  font-weight: 600;
}
.image-filters {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-bottom: 12px;
}
.image-filters button {
  border: 0;
  font-size: 11px;
  padding: 5px 9px;
  background: transparent;
  color: #637690;
}
.image-filters button.active {
  background: #eaf2fc;
  color: #276bb3;
}
.image-filters > span {
  margin-left: auto;
  font-size: 11px;
  color: #77869b;
}
.image-list-scroll {
  overflow: auto;
  min-height: 0;
  padding-right: 5px;
  scrollbar-gutter: stable;
  flex: 1;
}
.image-entry {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 13px 14px 9px;
  margin-bottom: 10px;
  background: white;
}
.image-entry.selected {
  border-color: #78a7dc;
  box-shadow: 0 0 0 2px #e9f1fb;
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
  min-width: 0;
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
  color: #687b94;
  font-size: 11px;
}
.image-protected {
  color: #536e91;
  background: #f0f4fa;
  padding: 1px 5px;
  border-radius: 4px;
}
.image-entry-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-top: 9px;
  flex-wrap: wrap;
}
.image-entry-footer code {
  color: #7c8ba0;
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
  min-width: 0;
}
h3 {
  font-size: 13px;
  font-weight: 600;
  margin: 0;
}
.image-import-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
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
  font-size: 12px;
}
.field input,
.field select,
.field textarea {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
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
.image-jobs.collapsed {
  padding-bottom: 9px;
}
.image-jobs.collapsed .image-job-heading {
  margin-bottom: 0;
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
  min-width: 0;
}
.image-job-heading h3,
.image-job-state,
#toggle-image-log {
  flex-shrink: 0;
}
#toggle-image-log {
  margin-left: auto;
  padding: 4px 8px;
  font-size: 11px;
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
  height: clamp(100px, 16vh, 160px);
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
  font-size: 11px;
  padding: 10px 22px;
  border-top: 1px solid var(--border);
  background: #fafbfe;
  flex-shrink: 0;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
}
.image-manager-footer span {
  color: #687c96;
}
.image-manager-footer details {
  min-width: 0;
  max-width: 100%;
  font-size: 11px;
}
.image-manager-footer summary {
  cursor: pointer;
  color: #587ba5;
}
.image-manager-footer details[open] code {
  display: block;
  max-width: 100%;
  padding-top: 6px;
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
@media (max-width: 1100px) {
  .image-manager-content {
    grid-template-columns: minmax(0, 1fr) 340px;
  }
  .image-inventory {
    padding: 16px;
  }
  .image-import {
    padding: 16px;
  }
  .image-overview > span {
    padding: 8px;
  }
}
</style>
