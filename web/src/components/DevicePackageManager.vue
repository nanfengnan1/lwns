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
import { useDevicePackagesStore } from "../stores/devicePackages";
import { useImagesStore } from "../stores/images";
import { useUiStore } from "../stores/ui";
import { useLabStore } from "../stores/lab";
import { readDeviceDescriptor } from "../domain/devicePackages";
import type {
  DeviceDescriptor,
  DevicePackageEntry,
  DevicePackageJob,
  DevicePackageSource,
} from "../types/devicePackages";
import type { DeviceKind } from "../types/lab";

const packages = useDevicePackagesStore(),
  images = useImagesStore(),
  ui = useUiStore(),
  lab = useLabStore();
const dialog = ref<HTMLDialogElement>(),
  log = ref<HTMLPreElement>();
const tab = ref<"library" | "import" | "pack">("library");
const error = ref(""),
  query = ref(""),
  importName = ref(""),
  inspectedFile = ref("");
const editing = ref(""),
  editName = ref("");
const descriptor = ref<DeviceDescriptor | null>(null),
  descriptorFile = ref("");
const archive = ref<File>(),
  dockerfileName = ref("");
const maker = reactive({
  name: "",
  version: "",
  category: "router" as DeviceKind,
  source: "repository" as DevicePackageSource["type"],
  reference: "",
  dockerfile: "",
});
const categories: Record<DeviceKind, string> = {
  router: "路由器",
  switch: "交换机",
  host: "PC",
  firewall: "防火墙",
};
const sources: Record<string, string> = {
  repository: "镜像仓库",
  archive: "离线镜像",
  dockerfile: "构建配方",
  local: "已有镜像",
};
const states = {
  queued: "等待中",
  running: "执行中",
  success: "已完成",
  error: "失败",
};
const entries = computed(() =>
  packages.data.devices.filter((item) =>
    `${item.name} ${item.descriptor_id} ${item.version} ${item.image}`
      .toLowerCase()
      .includes(query.value.trim().toLowerCase()),
  ),
);
const inspectionSource = computed(() => {
  const source = packages.inspection?.descriptor.source as
    { type?: string } | undefined;
  return source?.type ? sources[source.type] || source.type : "由设备包声明";
});
const disabled = computed(() => packages.busy || images.busy);
let timer: ReturnType<typeof setInterval> | undefined;
let fileRevision = 0;
async function run(action: () => unknown | Promise<unknown>) {
  error.value = "";
  try {
    await action();
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason);
    ui.report(reason);
  }
}
function syncDialog(open: boolean) {
  if (open) {
    dialog.value?.showModal();
    void run(() => packages.refresh(true));
    void ui.run(() => images.refresh());
  } else dialog.value?.close();
}
watch(() => ui.devicesOpen, syncDialog, { flush: "post" });
watch(
  () => packages.inspection,
  (value) => {
    if (!value) inspectedFile.value = "";
  },
);
watch(
  () => packages.job?.logs,
  async () => {
    const element = log.value;
    const nearBottom =
      !element ||
      element.scrollHeight - element.scrollTop - element.clientHeight < 48;
    if (nearBottom) {
      await nextTick();
      if (log.value) log.value.scrollTop = log.value.scrollHeight;
    }
  },
);
onMounted(() => {
  syncDialog(ui.devicesOpen);
  timer = setInterval(() => {
    if ((ui.devicesOpen || packages.data.busy) && !ui.accessOpen)
      void run(() => packages.refresh());
  }, 2000);
});
onBeforeUnmount(() => {
  clearInterval(timer);
  packages.cancelUpload();
  fileRevision++;
});
function fileOf(event: Event) {
  return (event.target as HTMLInputElement).files?.[0];
}
async function selectPackage(event: Event) {
  const file = fileOf(event);
  if (!file) return;
  await run(async () => {
    const result = await packages.inspectFile(file);
    importName.value = result.descriptor.name;
    inspectedFile.value = file.name;
  });
  (event.target as HTMLInputElement).value = "";
}
async function selectDescriptor(event: Event) {
  const file = fileOf(event),
    revision = ++fileRevision;
  if (!file) return;
  descriptor.value = null;
  descriptorFile.value = "";
  await run(async () => {
    if (file.size > 1024 * 1024) throw Error("device.json 不能超过 1 MiB");
    const item = readDeviceDescriptor(await file.text());
    if (revision !== fileRevision) return;
    descriptor.value = item;
    descriptorFile.value = file.name;
    maker.name = item.name;
    maker.version = item.version;
    maker.category = item.category;
    maker.reference = item.image;
  });
  (event.target as HTMLInputElement).value = "";
}
async function selectDockerfile(event: Event) {
  const file = fileOf(event);
  if (!file) return;
  maker.dockerfile = "";
  dockerfileName.value = "";
  await run(async () => {
    if (file.size > 512 * 1024) throw Error("Dockerfile 不能超过 512 KiB");
    maker.dockerfile = await file.text();
    dockerfileName.value = file.name;
  });
}
async function importPackage() {
  await packages.importPackage(importName.value);
  ui.notify("正在导入设备，可在任务日志中查看进度");
}
async function pack() {
  if (!descriptor.value) throw Error("请先选择 device.json");
  const source: DevicePackageSource = { type: maker.source };
  if (maker.source !== "archive") source.reference = maker.reference.trim();
  if (maker.source === "dockerfile") source.dockerfile = maker.dockerfile;
  await packages.pack(
    {
      ...descriptor.value,
      name: maker.name.trim(),
      version: maker.version.trim(),
      category: maker.category,
    },
    maker.name,
    source,
    archive.value,
  );
  ui.notify("设备包制作已开始，完成后可下载 .rov 文件");
}
function rename(item: DevicePackageEntry) {
  editing.value = item.id;
  editName.value = item.name;
}
async function saveName() {
  if (!editName.value.trim()) throw Error("请输入设备名称");
  await packages.update(editing.value, editName.value);
  editing.value = "";
  ui.notify("设备库名称已更新");
}
async function remove(item: DevicePackageEntry) {
  if (
    !window.confirm(
      `从设备库移除“${item.name} ${item.version}”？已有项目的配置和本地 Docker 镜像会保留；正在被项目引用的版本不能移除。`,
    )
  )
    return;
  await packages.remove(item.id);
  if (editing.value === item.id) editing.value = "";
  ui.notify("设备已移出设备库");
}
async function download(item: DevicePackageJob) {
  const result = await packages.download(item),
    url = URL.createObjectURL(result.blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = result.filename.replace(/[\\/]/g, "_");
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function legacy() {
  ui.devicesOpen = false;
  ui.imagesOpen = true;
}
</script>

<template>
  <dialog
    id="device-package-manager"
    ref="dialog"
    @close="!dialog?.open && (ui.devicesOpen = false)"
    @cancel="ui.devicesOpen = false"
  >
    <header class="device-manager-heading">
      <div>
        <span class="dialog-eyebrow">DEVICE LIBRARY</span>
        <h2>设备管理</h2>
        <p>在 {{ lab.serverHost }} 制作、导入和管理 .rov 设备包。</p>
      </div>
      <div class="heading-actions">
        <button
          id="refresh-device-packages"
          :disabled="packages.loading || disabled"
          @click="run(() => packages.refresh(true))"
        >
          刷新</button
        ><button
          id="close-device-packages"
          class="square"
          aria-label="关闭设备管理"
          @click="ui.devicesOpen = false"
        >
          ×
        </button>
      </div>
    </header>
    <nav class="device-manager-tabs" aria-label="设备管理页面">
      <button
        v-for="item in [
          { id: 'library', label: '已安装设备' },
          { id: 'import', label: '导入设备包' },
          { id: 'pack', label: '制作设备包' },
        ]"
        :id="`device-tab-${item.id}`"
        :key="item.id"
        :aria-pressed="tab === item.id"
        :class="{ active: tab === item.id }"
        @click="tab = item.id as typeof tab"
      >
        {{ item.label }}
      </button>
      <button id="device-legacy-images" class="legacy-link" @click="legacy">
        镜像管理 ↗
      </button>
    </nav>
    <p
      v-if="error"
      id="device-package-error"
      class="manager-error"
      role="alert"
    >
      {{ error }}
    </p>
    <p v-if="packages.data.error" class="manager-note" role="status">
      {{ packages.data.error }}
    </p>
    <main class="device-manager-body">
      <section
        v-if="tab === 'library'"
        aria-label="已安装设备"
        class="installed-devices"
      >
        <div class="section-heading">
          <div>
            <h3>
              我的设备 <span>{{ packages.data.devices.length }}</span>
            </h3>
            <p>每个版本独立保留，项目继续使用创建时的设备版本。</p>
          </div>
          <input
            id="device-package-search"
            v-model="query"
            type="search"
            placeholder="搜索名称、版本或镜像"
            aria-label="搜索设备包"
          />
        </div>
        <div v-if="!entries.length" class="device-manager-empty">
          <span class="empty-symbol">◇</span>
          <h3>{{ query ? "没有匹配的设备" : "开始添加设备" }}</h3>
          <p>
            {{
              query
                ? "尝试其他名称或版本。"
                : "导入 .rov 设备包，或将设备描述与镜像制作成可分享的包。"
            }}
          </p>
          <button v-if="!query" class="primary" @click="tab = 'import'">
            导入设备包
          </button>
        </div>
        <div v-else class="installed-device-grid">
          <article
            v-for="item in entries"
            :key="item.id"
            class="installed-device"
            :data-device-package="item.id"
          >
            <div class="device-entry-top">
              <span class="device-category">{{
                categories[item.category] || item.category
              }}</span
              ><span
                :class="[
                  'device-presence',
                  { missing: item.present === false },
                ]"
                >{{ item.present === false ? "镜像缺失" : "已安装" }}</span
              >
            </div>
            <form
              v-if="editing === item.id"
              class="device-rename"
              @submit.prevent="run(saveName)"
            >
              <input
                id="device-package-rename"
                v-model="editName"
                maxlength="80"
                required
                aria-label="设备库名称"
                :disabled="disabled"
              /><button type="submit" :disabled="disabled">保存</button
              ><button type="button" @click="editing = ''">取消</button>
            </form>
            <h3 v-else :title="item.name">{{ item.name }}</h3>
            <p class="device-version">
              <b>{{ item.version }}</b
              ><span>{{ item.descriptor_id }}</span>
            </p>
            <code class="device-image" :title="item.image">{{
              item.image
            }}</code>
            <div class="device-entry-actions">
              <button :disabled="disabled" @click="rename(item)">重命名</button
              ><button
                class="remove-device"
                :disabled="disabled"
                @click="run(() => remove(item))"
              >
                移出设备库
              </button>
            </div>
          </article>
        </div>
      </section>
      <section v-else-if="tab === 'import'" class="device-import-layout">
        <div class="device-task-intro">
          <span class="task-number">01 / IMPORT</span>
          <h3>加载一个文件<br />准备一台设备</h3>
          <p>
            设备包包含启动、保存和恢复配置的规则。导入后，在左侧设备库中选择它并拖入画布。
          </p>
          <div class="import-flow">
            <span>选择 .rov</span><i>↓</i><span>确认设备名称</span><i>↓</i
            ><span>准备镜像并加入设备库</span>
          </div>
        </div>
        <form
          id="device-package-import-form"
          class="device-task-form"
          @submit.prevent="run(importPackage)"
        >
          <fieldset :disabled="disabled">
            <label class="package-file-field"
              ><strong>选择 .rov 设备包</strong
              ><span>支持 Web 或 CLI 制作的设备包</span
              ><input
                id="device-package-file"
                type="file"
                accept=".rov"
                @change="selectPackage"
            /></label>
            <template v-if="packages.inspection"
              ><div class="package-inspected">
                <span>已检查</span><b>{{ inspectedFile }}</b>
              </div>
              <label class="field"
                ><span>设备名称</span
                ><input
                  id="device-package-import-name"
                  v-model="importName"
                  maxlength="80"
                  required
              /></label>
              <dl class="package-metadata">
                <div>
                  <dt>设备分类</dt>
                  <dd>
                    {{ categories[packages.inspection.descriptor.category] }}
                  </dd>
                </div>
                <div>
                  <dt>版本</dt>
                  <dd>{{ packages.inspection.descriptor.version }}</dd>
                </div>
                <div>
                  <dt>镜像来源</dt>
                  <dd>{{ inspectionSource }}</dd>
                </div>
                <div>
                  <dt>镜像</dt>
                  <dd>{{ packages.inspection.descriptor.image }}</dd>
                </div>
              </dl>
              <button
                id="import-device-package"
                class="primary"
                type="submit"
                :disabled="!packages.data.available"
              >
                导入设备
              </button></template
            >
          </fieldset>
        </form>
      </section>
      <section v-else class="device-pack-layout">
        <div class="device-task-intro">
          <span class="task-number">02 / CREATE</span>
          <h3>制作可复用的<br />设备包</h3>
          <p>
            选择设备描述，再关联镜像来源。设备包保存在当前服务器，完成后可下载分享。
          </p>
          <p class="source-help">
            {{
              maker.source === "archive" || maker.source === "local"
                ? "此方式携带镜像，可在其他宿主机离线加载。"
                : maker.source === "dockerfile"
                  ? "此方式携带构建配方，导入时构建镜像，可能需要网络。"
                  : "此方式记录仓库引用，导入时可能需要联网拉取镜像。"
            }}
          </p>
        </div>
        <form
          id="device-package-pack-form"
          class="device-task-form"
          @submit.prevent="run(pack)"
        >
          <fieldset :disabled="disabled">
            <label class="package-file-field"
              ><strong>设备描述 device.json</strong
              ><span>{{
                descriptorFile || "包含启动、保存动作与持久化目录"
              }}</span
              ><input
                id="device-descriptor-file"
                type="file"
                accept=".json,application/json"
                @change="selectDescriptor"
            /></label>
            <div class="device-form-row">
              <label class="field"
                ><span>设备名称</span
                ><input
                  id="device-package-name"
                  v-model="maker.name"
                  required
                  maxlength="80" /></label
              ><label class="field"
                ><span>版本</span
                ><input
                  id="device-package-version"
                  v-model="maker.version"
                  required
                  placeholder="1.0.0"
              /></label>
            </div>
            <div class="device-form-row">
              <label class="field"
                ><span>设备分类</span
                ><select id="device-package-category" v-model="maker.category">
                  <option
                    v-for="(name, category) in categories"
                    :key="category"
                    :value="category"
                  >
                    {{ name }}
                  </option>
                </select></label
              ><label class="field"
                ><span>镜像来源</span
                ><select id="device-package-source" v-model="maker.source">
                  <option value="repository">镜像仓库</option>
                  <option value="local">已有镜像</option>
                  <option value="archive">镜像 .tar 文件</option>
                  <option value="dockerfile">Dockerfile 构建</option>
                </select></label
              >
            </div>
            <label v-if="maker.source === 'local'" class="field"
              ><span>已管理的本地镜像</span
              ><select
                id="device-package-local-image"
                v-model="maker.reference"
                required
              >
                <option value="" disabled>选择镜像</option>
                <option
                  v-for="item in images.data.images.filter(
                    (item) => item.present,
                  )"
                  :key="item.id"
                  :value="item.reference"
                >
                  {{ item.title }} · {{ item.reference }}
                </option></select
              ><small
                >需要其他镜像时，可先通过镜像管理将其加入清单。</small
              ></label
            >
            <label v-else-if="maker.source !== 'archive'" class="field"
              ><span>{{
                maker.source === "dockerfile" ? "构建镜像标签" : "镜像仓库引用"
              }}</span
              ><input
                id="device-package-reference"
                v-model="maker.reference"
                required
                placeholder="registry.example/frr:1.0.0"
            /></label>
            <label v-if="maker.source === 'archive'" class="field"
              ><span>Docker 镜像归档</span
              ><input
                id="device-package-archive"
                type="file"
                accept=".tar"
                @change="archive = fileOf($event)"
              /><small>使用 docker save 导出的未压缩 .tar 文件。</small></label
            >
            <label v-if="maker.source === 'dockerfile'" class="field"
              ><span>Dockerfile</span
              ><input
                id="device-package-dockerfile"
                type="file"
                @change="selectDockerfile"
              /><small>{{
                dockerfileName ||
                "脚本和默认配置应由 Dockerfile 生成或由基础镜像提供。"
              }}</small></label
            >
            <button
              id="pack-device-package"
              class="primary"
              type="submit"
              :disabled="!descriptor"
            >
              制作 .rov 设备包
            </button>
          </fieldset>
        </form>
      </section>
    </main>
    <div v-if="packages.uploading" class="device-upload-progress">
      <progress max="100" :value="packages.uploadProgress"></progress
      ><span>上传 {{ packages.uploadProgress }}%</span
      ><button @click="packages.cancelUpload">取消上传</button>
    </div>
    <section
      v-if="packages.data.jobs.length"
      class="device-package-jobs"
      aria-label="设备任务日志"
    >
      <div class="device-job-heading">
        <h3>任务</h3>
        <select
          id="device-package-job"
          v-model="packages.activeJob"
          aria-label="选择设备任务"
        >
          <option
            v-for="item in packages.data.jobs"
            :key="item.id"
            :value="item.id"
          >
            {{ item.label }} · {{ states[item.state] }}
          </option></select
        ><span
          v-if="packages.job"
          :class="['device-job-status', packages.job.state]"
          >{{ states[packages.job.state] }}</span
        ><button
          v-if="
            packages.job?.state === 'success' &&
            packages.job.result?.download_url
          "
          id="download-device-package"
          class="primary"
          @click="run(() => download(packages.job!))"
        >
          下载 .rov
        </button>
      </div>
      <p v-if="packages.job?.result?.path" class="artifact-path">
        服务端文件：<code>{{ packages.job.result.path }}</code>
      </p>
      <pre id="device-package-log" ref="log" role="log">{{
        packages.job?.logs || packages.job?.error || "等待任务执行…"
      }}</pre>
    </section>
    <footer class="device-manager-footer">
      <span>设备模板共用，每个实例的配置独立保存。</span>
      <details>
        <summary>设备库位置</summary>
        <code>{{ packages.data.registry_path || "连接服务器后显示" }}</code>
      </details>
    </footer>
  </dialog>
</template>

<style scoped>
#device-package-manager {
  width: min(1100px, calc(100vw - 40px));
  max-width: none;
  height: min(850px, calc(100vh - 40px));
  max-height: calc(100vh - 40px);
  padding: 0;
  border: 1px solid #dae3ef;
  border-radius: 16px;
  overflow: hidden;
  color: #293c55;
}
#device-package-manager[open] {
  display: flex;
  flex-direction: column;
}
.device-manager-heading {
  padding: 22px 26px 18px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: linear-gradient(110deg, #f3f7fd, #fff);
}
.device-manager-heading h2 {
  margin: 4px 0 6px;
  font-size: 22px;
}
.device-manager-heading p,
.section-heading p {
  margin: 0;
  color: #718198;
  font-size: 12px;
}
.heading-actions {
  display: flex;
  gap: 10px;
}
.device-manager-tabs {
  display: flex;
  gap: 6px;
  padding: 0 22px 12px;
  border-bottom: 1px solid #e4eaf2;
}
.device-manager-tabs button {
  border: 0;
  background: transparent;
  padding: 9px 16px;
  color: #62738b;
}
.device-manager-tabs button.active {
  color: #225ca9;
  background: #eaf2fe;
  font-weight: 600;
}
.device-manager-tabs .legacy-link {
  margin-left: auto;
  font-size: 12px;
}
.manager-error,
.manager-note {
  margin: 0;
  padding: 10px 26px;
  font-size: 12px;
  line-height: 1.6;
}
.manager-error {
  color: #a2343e;
  background: #fff0f0;
}
.manager-note {
  color: #856b32;
  background: #fff8e8;
}
.device-manager-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 24px 26px;
}
.section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 22px;
}
.section-heading h3 {
  margin: 0 0 7px;
  font-size: 15px;
}
.section-heading h3 span {
  margin-left: 7px;
  color: #75869b;
}
.section-heading input {
  width: 240px;
}
.installed-device-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}
.installed-device {
  min-width: 0;
  border: 1px solid #e0e7f0;
  border-radius: 12px;
  padding: 17px 18px 12px;
  background: linear-gradient(150deg, #fff, #f9fbfe);
}
.device-entry-top {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}
.device-category {
  color: #4c6d96;
  font-size: 11px;
}
.device-presence {
  color: #287d65;
  background: #eaf7ef;
  border-radius: 5px;
  padding: 2px 6px;
  font-size: 10px;
}
.device-presence.missing {
  color: #926d31;
  background: #fff3d9;
}
.installed-device h3 {
  font-size: 15px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin: 12px 0 8px;
}
.device-version {
  margin: 0 0 9px;
  display: flex;
  gap: 10px;
  font-size: 11px;
  color: #7d8ca0;
}
.device-version b {
  color: #476384;
}
.device-image {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  color: #64768f;
}
.device-entry-actions {
  margin-top: 15px;
  padding-top: 10px;
  border-top: 1px solid #e8edf4;
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
.device-entry-actions button {
  font-size: 11px;
  padding: 5px 9px;
}
.remove-device {
  color: #a35a62;
}
.device-rename {
  display: flex;
  gap: 5px;
  margin: 10px 0;
}
.device-rename input {
  min-width: 0;
  flex: 1;
}
.device-rename button {
  padding: 4px 7px;
  font-size: 11px;
}
.device-manager-empty {
  padding: 45px 25px;
  text-align: center;
  border: 1px dashed #d6e0ee;
  border-radius: 12px;
  color: #78899f;
}
.empty-symbol {
  font-size: 40px;
  color: #6a93ca;
}
.device-manager-empty h3 {
  color: #39516f;
  font-size: 16px;
}
.device-manager-empty p {
  font-size: 12px;
  margin-bottom: 20px;
}
.device-import-layout,
.device-pack-layout {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 32px;
}
.device-task-intro {
  border-right: 1px solid #e8edf4;
  padding: 8px 28px 0 0;
}
.task-number {
  font-size: 10px;
  letter-spacing: 1.5px;
  color: #668ab8;
}
.device-task-intro h3 {
  font-size: 25px;
  line-height: 1.5;
  margin: 20px 0 14px;
  color: #2c4565;
}
.device-task-intro p {
  font-size: 12px;
  line-height: 1.9;
  color: #6d7f97;
}
.device-task-intro .source-help {
  margin-top: 24px;
  padding: 12px;
  background: #f0f5fc;
  border-radius: 8px;
}
.import-flow {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 9px;
  margin-top: 28px;
  font-size: 12px;
  color: #597da9;
}
.import-flow i {
  margin-left: 12px;
  color: #b2c2d6;
  font-style: normal;
}
.device-task-form {
  min-width: 0;
}
.device-task-form fieldset {
  border: 0;
  padding: 0;
  margin: 0;
  min-width: 0;
}
.device-task-form .field {
  margin-bottom: 15px;
}
.device-task-form .field small {
  color: #7a899d;
  line-height: 1.7;
  font-size: 11px;
}
.device-task-form input[type="file"] {
  width: 100%;
  box-sizing: border-box;
  font-size: 12px;
}
.device-task-form .primary {
  min-height: 36px;
}
.package-file-field {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 17px 18px;
  border: 1px dashed #b7cbe5;
  background: #f6f9fe;
  border-radius: 10px;
  margin-bottom: 20px;
}
.package-file-field strong {
  font-size: 13px;
  color: #3c6598;
}
.package-file-field span {
  font-size: 11px;
  color: #7a8da5;
}
.package-inspected {
  display: flex;
  gap: 9px;
  font-size: 12px;
  align-items: center;
  margin-bottom: 19px;
}
.package-inspected span {
  color: #2f8567;
  background: #edf9f1;
  padding: 3px 7px;
  border-radius: 4px;
}
.package-inspected b {
  font-weight: 500;
  word-break: break-all;
}
.package-metadata {
  margin: 18px 0 24px;
  padding: 14px;
  border-radius: 8px;
  background: #f7f9fc;
}
.package-metadata div {
  display: grid;
  grid-template-columns: 76px minmax(0, 1fr);
  padding: 6px 0;
  font-size: 12px;
}
.package-metadata dt {
  color: #7d8da2;
}
.package-metadata dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.device-form-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 14px;
}
.device-form-row input {
  width: 100%;
  box-sizing: border-box;
}
.device-upload-progress {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 26px;
  background: #f3f7fe;
  font-size: 12px;
}
.device-upload-progress progress {
  flex: 1;
  height: 6px;
  accent-color: #4675bf;
}
.device-package-jobs {
  border-top: 1px solid #e3eaf3;
  padding: 12px 26px;
  background: #f7f9fc;
  flex-shrink: 0;
}
.device-job-heading {
  display: flex;
  gap: 12px;
  align-items: center;
}
.device-job-heading h3 {
  margin: 0;
  font-size: 12px;
}
.device-job-heading select {
  min-width: 0;
  flex: 1;
  font-size: 11px;
}
.device-job-heading button {
  font-size: 11px;
}
.device-job-status {
  font-size: 11px;
  color: #607590;
}
.device-job-status.error {
  color: #b34650;
}
.device-job-status.success {
  color: #277f60;
}
.device-package-jobs pre {
  margin: 10px 0 0;
  max-height: 120px;
  min-height: 42px;
  overflow: auto;
  padding: 12px;
  background: #15243a;
  color: #cdd9e9;
  border-radius: 7px;
  font-size: 11px;
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.artifact-path {
  margin: 8px 0 0;
  font-size: 11px;
  color: #657994;
  overflow-wrap: anywhere;
}
.device-manager-footer {
  padding: 10px 26px;
  border-top: 1px solid #e3eaf3;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 10px;
  color: #8291a5;
  gap: 15px;
}
.device-manager-footer details {
  text-align: right;
}
.device-manager-footer code {
  display: block;
  max-width: 450px;
  overflow-wrap: anywhere;
  margin-top: 6px;
}
@media (max-width: 1100px) {
  .device-import-layout,
  .device-pack-layout {
    grid-template-columns: 205px minmax(0, 1fr);
    gap: 24px;
  }
  .device-task-intro h3 {
    font-size: 22px;
  }
}
</style>
