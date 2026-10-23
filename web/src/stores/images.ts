import { computed, ref } from "vue";
import { defineStore } from "pinia";
import { api, ApiError, getToken } from "../api/client";
import type { ImageInventory, ImageJob } from "../types/images";
import { useLabStore } from "./lab";

export const useImagesStore = defineStore("images", () => {
  const lab = useLabStore();
  const data = ref<ImageInventory>({
    images: [],
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
  const job = computed(
    () =>
      data.value.jobs.find((item) => item.id === activeJob.value) ||
      data.value.jobs[0],
  );
  let xhr: XMLHttpRequest | undefined;
  let revision = 0;
  const busy = computed(
    () => data.value.busy || submitting.value || uploading.value,
  );

  async function refresh(sync = false) {
    if (loading.value || submitting.value) return;
    loading.value = true;
    const current = revision;
    const wasBusy = data.value.busy;
    try {
      const result = await api<ImageInventory>(
        sync ? "/api/images/refresh" : "/api/images",
        sync ? "POST" : "GET",
        sync ? {} : undefined,
      );
      if (current !== revision) return;
      data.value = result;
      if (!activeJob.value && result.jobs[0])
        activeJob.value = result.jobs[0].id;
      if (sync || (wasBusy && !data.value.busy)) {
        await lab.refreshCatalog();
        await lab.refreshEnvironment();
      }
    } finally {
      loading.value = false;
    }
  }
  async function upload(file: File, kind: "archive" | "context") {
    if (file.size > data.value.max_upload_bytes)
      throw Error("文件超过宿主机上传大小限制");
    const info = await api<{ id: string }>("/api/images/uploads", "POST", {
      name: file.name,
      size: file.size,
      kind,
    });
    uploading.value = true;
    uploadProgress.value = 0;
    try {
      await new Promise<void>((resolve, reject) => {
        xhr = new XMLHttpRequest();
        xhr.open("PUT", `/api/images/uploads/${info.id}`);
        xhr.setRequestHeader("Authorization", `Bearer ${getToken()}`);
        xhr.setRequestHeader("Content-Type", "application/octet-stream");
        xhr.upload.onprogress = (event) => {
          if (event.lengthComputable)
            uploadProgress.value = Math.round(
              (event.loaded / event.total) * 100,
            );
        };
        xhr.onload = () => {
          if (xhr!.status >= 200 && xhr!.status < 300) resolve();
          else {
            let error = "上传失败，请检查后端连接";
            try {
              error = JSON.parse(xhr!.responseText).error || error;
            } catch {
              /* proxy may return non-JSON */
            }
            reject(new ApiError(error, xhr!.status));
          }
        };
        xhr.onerror = () =>
          reject(Error("上传连接失败，请检查后端或代理的文件大小限制"));
        xhr.onabort = () => reject(Error("上传已取消"));
        xhr.send(file);
      });
      return info.id;
    } catch (error) {
      await api(`/api/images/uploads/${info.id}`, "DELETE").catch(() => {});
      throw error;
    } finally {
      uploading.value = false;
      xhr = undefined;
    }
  }
  async function start(
    payload: Record<string, unknown>,
    file?: File,
    kind: "archive" | "context" = "archive",
  ) {
    if (busy.value) throw Error("请等待当前镜像任务完成");
    revision++;
    submitting.value = true;
    let uploaded: string | undefined,
      started = false;
    try {
      if (file) uploaded = await upload(file, kind);
      const result = await api<ImageJob>("/api/images/jobs", "POST", {
        ...payload,
        ...(uploaded ? { upload: uploaded } : {}),
      });
      started = true;
      activeJob.value = result.id;
      data.value.jobs.unshift(result);
      data.value.busy = true;
      return result;
    } finally {
      if (uploaded && !started)
        await api(`/api/images/uploads/${uploaded}`, "DELETE").catch(() => {});
      submitting.value = false;
    }
  }
  async function remove(id: string) {
    if (busy.value) throw Error("请等待当前镜像任务完成");
    revision++;
    submitting.value = true;
    try {
      const result = await api<ImageJob>(`/api/images/${id}`, "DELETE");
      activeJob.value = result.id;
      data.value.jobs.unshift(result);
      data.value.busy = true;
    } finally {
      submitting.value = false;
    }
  }
  async function update(id: string, title: string, template: string) {
    revision++;
    await api(`/api/images/${id}`, "PUT", { title, template });
    await refresh();
    await lab.refreshCatalog();
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
    refresh,
    start,
    remove,
    update,
    cancelUpload,
  };
});
