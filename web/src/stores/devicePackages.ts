import { computed, ref } from "vue";
import { defineStore } from "pinia";
import { api, ApiError, getToken } from "../api/client";
import { validatePackageFile } from "../domain/devicePackages";
import type {
  DeviceDescriptor,
  DevicePackageInventory,
  DevicePackageInspection,
  DevicePackageJob,
  DevicePackageSource,
} from "../types/devicePackages";
import { useLabStore } from "./lab";

const base = "/api/device-packages";
export const useDevicePackagesStore = defineStore("devicePackages", () => {
  const lab = useLabStore();
  const data = ref<DevicePackageInventory>({
    devices: [],
    jobs: [],
    busy: false,
    available: false,
    error: "",
    registry_path: "",
    max_upload_bytes: 8 * 1024 ** 3,
  });
  const loading = ref(false),
    submitting = ref(false),
    uploading = ref(false),
    uploadProgress = ref(0);
  const activeJob = ref("");
  const inspection = ref<DevicePackageInspection | null>(null);
  const inspectedUpload = ref("");
  let importingJob = "";
  const busy = computed(
    () => data.value.busy || submitting.value || uploading.value,
  );
  const job = computed(
    () =>
      data.value.jobs.find((item) => item.id === activeJob.value) ||
      data.value.jobs[0],
  );
  let xhr: XMLHttpRequest | undefined;
  let revision = 0,
    catalogKey = "";

  async function refresh(sync = false) {
    if (loading.value || submitting.value) return;
    loading.value = true;
    const current = revision,
      wasBusy = data.value.busy;
    try {
      const result = await api<DevicePackageInventory>(
        sync ? `${base}/refresh` : base,
        sync ? "POST" : "GET",
        sync ? {} : undefined,
      );
      if (current !== revision) return;
      data.value = result;
      if (importingJob) {
        const imported = result.jobs.find((item) => item.id === importingJob);
        if (imported?.state === "success") {
          inspection.value = null;
          inspectedUpload.value = "";
          importingJob = "";
        }
        // Failed imports retain their checked upload so the user can retry.
      }
      if (!activeJob.value && result.jobs[0])
        activeJob.value = result.jobs[0].id;
      const nextKey = JSON.stringify(
        result.devices.map((item) => [
          item.id,
          item.name,
          item.version,
          item.image_id,
          item.present,
        ]),
      );
      if (sync || nextKey !== catalogKey || (wasBusy && !result.busy)) {
        await lab.refreshCatalog();
        await lab.refreshEnvironment();
        if (current === revision) catalogKey = nextKey;
      }
    } finally {
      loading.value = false;
    }
  }
  async function discard(id: string) {
    if (id) await api(`${base}/uploads/${encodeURIComponent(id)}`, "DELETE");
  }
  async function upload(file: File, kind: "package" | "archive") {
    validatePackageFile(file, kind, data.value.max_upload_bytes);
    const info = await api<{ id: string }>(`${base}/uploads`, "POST", {
      name: file.name,
      size: file.size,
      kind,
    });
    uploading.value = true;
    uploadProgress.value = 0;
    try {
      await new Promise<void>((resolve, reject) => {
        const request = new XMLHttpRequest();
        xhr = request;
        request.open("PUT", `${base}/uploads/${encodeURIComponent(info.id)}`);
        request.setRequestHeader("Authorization", `Bearer ${getToken()}`);
        request.setRequestHeader("Content-Type", "application/octet-stream");
        request.upload.onprogress = (event) => {
          if (event.lengthComputable)
            uploadProgress.value = Math.round(
              (event.loaded / event.total) * 100,
            );
        };
        request.onload = () => {
          if (request.status >= 200 && request.status < 300) resolve();
          else {
            let message = "设备文件上传失败";
            try {
              message = JSON.parse(request.responseText).error || message;
            } catch {
              /* non-JSON proxy error */
            }
            reject(new ApiError(message, request.status));
          }
        };
        request.onerror = () =>
          reject(Error("上传连接失败，请检查后端或代理限制"));
        request.onabort = () => reject(Error("上传已取消"));
        request.send(file);
      });
      return info.id;
    } catch (error) {
      await discard(info.id).catch(() => {});
      throw error;
    } finally {
      uploading.value = false;
      xhr = undefined;
    }
  }
  function assertIdle() {
    if (busy.value) throw Error("请等待当前设备任务完成");
  }
  async function inspectFile(file: File) {
    assertIdle();
    revision++;
    submitting.value = true;
    let uploaded = "";
    try {
      uploaded = await upload(file, "package");
      const result = await api<DevicePackageInspection>(
        `${base}/inspect`,
        "POST",
        { upload_id: uploaded },
      );
      const old = inspectedUpload.value;
      inspectedUpload.value = uploaded;
      inspection.value = result;
      importingJob = "";
      if (old) await discard(old).catch(() => {});
      return result;
    } catch (error) {
      if (uploaded) await discard(uploaded).catch(() => {});
      throw error;
    } finally {
      submitting.value = false;
    }
  }
  async function start(payload: Record<string, unknown>) {
    const result = await api<DevicePackageJob>(`${base}/jobs`, "POST", payload);
    activeJob.value = result.id;
    data.value.jobs.unshift(result);
    data.value.busy = true;
    return result;
  }
  async function importPackage(name: string) {
    assertIdle();
    if (!inspection.value || !inspectedUpload.value)
      throw Error("请先选择并检查设备包");
    if (!name.trim()) throw Error("请输入设备名称");
    revision++;
    submitting.value = true;
    try {
      const result = await start({
        mode: "import",
        upload_id: inspectedUpload.value,
        name: name.trim(),
      });
      importingJob = result.id;
      return result;
    } finally {
      submitting.value = false;
    }
  }
  async function pack(
    descriptor: DeviceDescriptor,
    name: string,
    source: DevicePackageSource,
    archive?: File,
  ) {
    assertIdle();
    if (!name.trim()) throw Error("请输入设备名称");
    if (
      (source.type === "repository" || source.type === "local") &&
      !source.reference?.trim()
    )
      throw Error("请输入或选择镜像引用");
    if (source.type === "dockerfile" && !source.dockerfile?.trim())
      throw Error("请选择 Dockerfile");
    if (source.type === "archive" && !archive)
      throw Error("请选择镜像 .tar 文件");
    revision++;
    submitting.value = true;
    let uploaded = "",
      started = false;
    try {
      if (source.type === "archive" && archive)
        uploaded = await upload(archive, "archive");
      const result = await start({
        mode: "pack",
        descriptor,
        name: name.trim(),
        source: { ...source, ...(uploaded ? { upload_id: uploaded } : {}) },
      });
      started = true;
      return result;
    } finally {
      if (uploaded && !started) await discard(uploaded).catch(() => {});
      submitting.value = false;
    }
  }
  async function update(id: string, name: string) {
    assertIdle();
    revision++;
    submitting.value = true;
    try {
      await api(`${base}/${encodeURIComponent(id)}`, "PATCH", {
        name: name.trim(),
      });
    } finally {
      submitting.value = false;
    }
    await refresh();
  }
  async function remove(id: string) {
    assertIdle();
    revision++;
    submitting.value = true;
    try {
      await api(`${base}/${encodeURIComponent(id)}`, "DELETE");
    } finally {
      submitting.value = false;
    }
    await refresh();
  }
  async function download(item: DevicePackageJob) {
    const response = await fetch(
      `${base}/artifacts/${encodeURIComponent(item.id)}`,
      { headers: { Authorization: `Bearer ${getToken()}` } },
    );
    if (!response.ok) {
      let message = "设备包下载失败";
      try {
        message = (await response.json()).error || message;
      } catch {
        /* proxy error */
      }
      throw new ApiError(message, response.status);
    }
    return {
      blob: await response.blob(),
      filename: item.result?.filename || "device.lwns",
    };
  }
  function cancelUpload() {
    xhr?.abort();
  }
  return {
    data,
    loading,
    submitting,
    uploading,
    uploadProgress,
    activeJob,
    job,
    busy,
    inspection,
    inspectedUpload,
    refresh,
    inspectFile,
    importPackage,
    pack,
    update,
    remove,
    download,
    cancelUpload,
  };
});
