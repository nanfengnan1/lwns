<script setup lang="ts">
import { ref, watch } from "vue";
import { getToken, setToken } from "../api/client";
import { useLabStore } from "../stores/lab";
import { useUiStore } from "../stores/ui";
import polarBear from "../assets/polar-bear.svg";
const lab = useLabStore(),
  ui = useUiStore();
const accessDialog = ref<HTMLDialogElement>(),
  infoDialog = ref<HTMLDialogElement>();
const tokenInput = ref(""),
  error = ref(""),
  connecting = ref(false);
watch(
  () => ui.accessOpen,
  (open) => {
    if (open) accessDialog.value?.showModal();
    else accessDialog.value?.close();
  },
  { flush: "post" },
);
watch(
  () => ui.infoOpen,
  (open) => {
    if (open) infoDialog.value?.showModal();
    else infoDialog.value?.close();
  },
  { flush: "post" },
);
async function connect() {
  if (connecting.value) return;
  connecting.value = true;
  error.value = "";
  setToken(tokenInput.value);
  try {
    await lab.bootstrap();
    sessionStorage.setItem("route-ovs-token", getToken());
    ui.accessOpen = false;
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason);
  } finally {
    connecting.value = false;
  }
}
</script>

<template>
  <div
    id="toast"
    role="status"
    :hidden="!ui.notification"
    :class="{ error: ui.notification?.error }"
  >
    {{ ui.notification?.message }}
  </div>
  <dialog id="access-dialog" ref="accessDialog" @cancel.prevent>
    <form id="access-form" @submit.prevent="connect">
      <img
        class="dialog-logo"
        :src="polarBear"
        alt="北极熊头像"
        width="52"
        height="52"
      />
      <span class="dialog-eyebrow">ROUTE OVS</span>
      <h2>连接实验主机</h2>
      <p>粘贴后端启动时显示的访问令牌。</p>
      <input
        id="access-token"
        v-model="tokenInput"
        type="password"
        required
        autocomplete="off"
        aria-label="访问令牌"
      />
      <p id="access-error" class="error-text">{{ error }}</p>
      <button class="primary" type="submit" :disabled="connecting">
        {{ connecting ? "连接中…" : "连接工作台" }}
      </button>
    </form>
  </dialog>
  <dialog id="info-dialog" ref="infoDialog" @close="ui.infoOpen = false">
    <div class="dialog-top">
      <h2>实验主机</h2>
      <button id="close-info" aria-label="关闭" @click="ui.infoOpen = false">
        ×
      </button>
    </div>
    <div id="environment-detail">
      <p>
        {{
          lab.environment.ready
            ? "已连接 Linux Docker 宿主机，可以部署实验。"
            : "画布和拓扑文件可正常使用。部署状态如下："
        }}
      </p>
      <div
        v-for="message in lab.environment.errors"
        :key="message"
        class="environment-item"
      >
        {{ message }}
      </div>
      <p>在 Linux Docker 主机安装依赖并启动后端：</p>
      <code
        >python3 -m venv .venv<br />.venv/bin/python -m pip install -r
        script/python/requirements.txt<br />sudo .venv/bin/python
        script/python/lab_server.py --host 0.0.0.0</code
      >
      <p>镜像准备：</p>
      <code
        >docker load -i devices/route/frr.tar.xz<br />docker load -i
        devices/vpcs/vpcs.tar.xz</code
      >
      <p>容器镜像标签以本机 docker image ls 为准，可在设备属性中选择。</p>
    </div>
  </dialog>
</template>
