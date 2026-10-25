<script setup lang="ts">
import { useLabStore } from "../stores/lab";
import { useEditorStore } from "../stores/editor";
import { useUiStore } from "../stores/ui";
import { colors, titles } from "../domain/topology";
import AnnotationInspector from "./AnnotationInspector.vue";
import DeviceIcon from "./DeviceIcon.vue";
import DeleteLabButton from "./DeleteLabButton.vue";
import DeviceConfigPanel from "./DeviceConfigPanel.vue";
import { useTerminalsStore } from "../stores/terminals";
const terminals = useTerminalsStore();
const lab = useLabStore(),
  editor = useEditorStore(),
  ui = useUiStore();
function apply() {
  editor.commitDraft();
  ui.notify(
    lab.runtime?.deployment
      ? "设备设置已写入草稿，点击顶部“应用拓扑”后生效"
      : "设备设置已应用，保存后部署生效",
  );
}
</script>

<template>
  <aside class="inspector">
    <div class="inspector-heading">
      <h2>属性</h2>
      <span id="selection-type">{{
        editor.node
          ? "设备"
          : editor.link
            ? "链路"
            : editor.annotation
              ? "注释"
              : "实验"
      }}</span>
    </div>
    <div id="inspector-content">
      <AnnotationInspector v-if="editor.annotation" />
      <template v-else-if="editor.node && editor.draft">
        <div class="inspector-summary">
          <div class="large-icon" :style="{ color: colors[editor.node.kind] }">
            <DeviceIcon :kind="editor.node.kind" />
          </div>
          <div>
            <b>{{ editor.node.name }}</b
            ><small>{{ titles[editor.node.kind] }} · DOCKER</small>
          </div>
        </div>
        <div v-if="lab.runtime?.deployment" class="readonly-note">
          {{
            lab.getRuntimeNode(editor.node.id)
              ? "设备正在运行。修改先保留在草稿中，点击顶部“应用拓扑”后生效。"
              : "此设备尚未部署，点击顶部“应用拓扑”后才能打开终端。"
          }}
        </div>
        <form
          id="node-form"
          :key="editor.node.id"
          @submit.prevent="ui.run(apply)"
          @input="editor.touchDraft"
        >
          <label class="field"
            ><span>设备名称</span
            ><input
              id="node-name"
              v-model="editor.draft.name"
              maxlength="32"
              required
              :disabled="lab.locked"
          /></label>
          <label class="field"
            ><span>Docker 镜像</span
            ><input
              id="node-image"
              v-model="editor.draft.image"
              list="images"
              required
              :disabled="lab.locked"
            /><small>{{
              editor.node.kind === "router"
                ? "使用兼容 /usr/lib/frr/docker-start 的 FRR 镜像"
                : "使用带 sleep 命令的 Linux 镜像"
            }}</small></label
          >
          <label class="field"
            ><span>端口数量</span
            ><input
              id="node-port-count"
              v-model="editor.portCount"
              type="number"
              min="1"
              max="32"
              :disabled="lab.locked"
          /></label>
          <div class="property-section">
            <h3>
              接口配置
              <span
                >{{
                  editor.node.ports.filter((p) =>
                    lab.getConnection(editor.node!.id, p.name),
                  ).length
                }}
                已连接 / {{ editor.node.ports.length }} 端口</span
              >
            </h3>
            <div
              v-for="port in editor.draft.ports"
              :key="port.name"
              class="port-row"
              :class="{
                connected: !!lab.getConnection(editor.node.id, port.name),
              }"
            >
              <i class="port-indicator"></i><label>{{ port.name }}</label>
              <span
                v-if="editor.node.kind === 'switch'"
                class="peer-name"
                :title="lab.peerLabel(editor.node.id, port.name)"
                >{{ lab.peerLabel(editor.node.id, port.name) }}</span
              >
              <input
                v-else
                v-model="port.address"
                :data-address="port.name"
                :aria-label="port.name + ' IP 地址'"
                placeholder="IP / 前缀长度"
                :disabled="lab.locked"
              />
            </div>
            <label
              v-if="editor.node.kind !== 'switch'"
              class="field gateway-field"
              ><span>默认网关（可选）</span
              ><input
                id="node-gateway"
                v-model="editor.draft.gateway"
                placeholder="例如 10.10.1.1"
                :disabled="lab.locked"
            /></label>
            <p v-else class="inspector-help">
              已连接端口自动加入容器内 br0，启用 STP。
            </p>
          </div>
          <details class="property-section">
            <summary>高级配置</summary>
            <label class="field command-field"
              ><span>启动命令（JSON 数组，可留空）</span
              ><textarea
                id="node-command"
                v-model="editor.commandText"
                placeholder='["sleep", "infinity"]'
                :disabled="lab.locked"
              ></textarea>
            </label>
            <label v-if="lab.supportsConfig(editor.node)" class="field"
              ><span>FRR 启动配置（可选）</span
              ><textarea
                id="node-config"
                v-model="editor.draft.config"
                rows="7"
                placeholder="router ospf&#10; network 10.0.0.0/8 area 0"
                :disabled="lab.locked"
              ></textarea
              ><small
                >首次部署用于初始化配置。部署后修改此文本，应用拓扑时会重建设备并备份、替换磁盘配置。
                请先保存需要保留的运行配置；Web
                保存设备配置会同步未手动修改的文本。</small
              ></label
            >
          </details>
          <div class="inspector-actions">
            <button class="primary" type="submit" :disabled="lab.locked">
              应用设置</button
            ><button
              id="delete-selection"
              type="button"
              class="delete-button"
              :disabled="lab.locked"
              @click="editor.deleteSelection"
            >
              删除设备
            </button>
          </div>
        </form>
        <DeviceConfigPanel
          v-if="
            lab.supportsConfig(
              lab.getRuntimeNode(editor.node.id) || editor.node,
            )
          "
          :node="lab.getRuntimeNode(editor.node.id) || editor.node"
        />
        <div class="property-section">
          <h3>设备终端</h3>
          <button
            id="inspect-console"
            :disabled="!lab.canOpenTerminal(editor.node.id)"
            @click="ui.run(() => terminals.open(editor.node!.id))"
          >
            打开交互终端 ↗
          </button>
          <code v-if="lab.getRuntimeNode(editor.node.id)" class="code-line"
            >docker exec -it {{ lab.runtime!.nodes[editor.node.id].name }}
            {{
              lab.getTemplate(lab.getRuntimeNode(editor.node.id)!)?.console ||
              (lab.getRuntimeNode(editor.node.id)!.kind === "router"
                ? "vtysh"
                : "sh")
            }}</code
          >
          <p v-else class="inspector-help">
            部署后可查看接口、路由和执行连通性测试。
          </p>
        </div>
      </template>
      <template v-else-if="editor.link">
        <div class="inspector-summary">
          <div class="large-icon">⌁</div>
          <div><b>veth 网线</b><small>点对点 · 双向以太网</small></div>
        </div>
        <label
          v-for="(end, index) in [editor.link.a, editor.link.b]"
          :key="end.node + end.port"
          class="field"
          ><span>端点 {{ index + 1 }}</span
          ><input
            readonly
            :value="lab.getNode(end.node)?.name + ' / ' + end.port"
        /></label>
        <p class="inspector-help">
          两个端口分别位于设备容器内，直接互为 veth 对端，不经过宿主机 OVS。
        </p>
        <button
          id="capture-link"
          class="primary"
          :disabled="!lab.canCapture(editor.link.id)"
          @click="
            ui.captureLink = editor.link.id;
            ui.captureOpen = true;
          "
        >
          在 Wireshark 中抓包
        </button>
        <div class="inspector-actions">
          <button
            id="delete-selection"
            class="delete-button"
            :disabled="lab.locked"
            @click="editor.deleteSelection"
          >
            删除网线
          </button>
        </div>
      </template>
      <template v-else>
        <div class="inspector-summary">
          <div class="large-icon"><DeviceIcon kind="router" /></div>
          <div><b>拓扑概览</b><small>DOCKER NETWORK LAB</small></div>
        </div>
        <label class="field"
          ><span>实验 ID</span><input readonly :value="lab.topology.id"
        /></label>
        <div class="inspector-stats">
          <div class="stat">
            <b>{{ lab.topology.nodes.length }}</b
            ><span>设备</span>
          </div>
          <div class="stat">
            <b>{{ lab.topology.links.length }}</b
            ><span>veth 链路</span>
          </div>
        </div>
        <div class="property-section">
          <h3>开始组网</h3>
          <div class="step">
            <span>1</span>
            <div><b>添加设备</b><br />进入左侧分类，选择设备加入画布。</div>
          </div>
          <div class="step">
            <span>2</span>
            <div><b>连接端口</b><br />点击两个空闲端口，创建一根网线。</div>
          </div>
          <div class="step">
            <span>3</span>
            <div><b>配置并部署</b><br />设置接口地址，保存并部署实验。</div>
          </div>
        </div>
        <div class="property-section">
          <h3>快捷操作</h3>
          <div class="shortcut-list">
            <div><span>选择设备</span><kbd>V</kbd></div>
            <div><span>连线模式</span><kbd>C</kbd></div>
            <div><span>添加注释</span><kbd>T</kbd></div>
            <div><span>删除选中项</span><kbd>Delete</kbd></div>
            <div><span>取消当前工具</span><kbd>Esc</kbd></div>
          </div>
        </div>
        <div class="property-section">
          <DeleteLabButton id="delete-lab" />
        </div>
      </template>
    </div>
    <div class="inspector-footer">
      <i class="status-dot"></i><span>容器隔离 · veth 直连</span>
    </div>
    <datalist id="images">
      <option v-for="image in lab.images" :key="image" :value="image"></option>
    </datalist>
  </aside>
</template>

<style scoped>
.gateway-field {
  margin-top: 16px;
}
.command-field {
  margin-top: 14px;
}
</style>
