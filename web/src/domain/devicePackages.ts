import type { DeviceDescriptor } from "../types/devicePackages";

export function readDeviceDescriptor(text: string): DeviceDescriptor {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw Error("device.json 不是有效的 JSON 文件");
  }
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw Error("设备描述必须是 JSON 对象");
  const item = value as Record<string, unknown>;
  if (item.schema_version !== 1) throw Error("设备描述需要 schema_version: 1");
  for (const key of ["id", "version", "name", "image"])
    if (typeof item[key] !== "string" || !item[key].trim())
      throw Error(`设备描述缺少 ${key}`);
  if (!["router", "switch", "host", "firewall"].includes(String(item.category)))
    throw Error("设备分类必须为 router、switch、host 或 firewall");
  const actions = item.actions as Record<string, unknown> | undefined;
  if (!actions || !actions.save_config)
    throw Error("设备描述必须声明 actions.save_config 保存动作");
  return item as DeviceDescriptor;
}

export function validatePackageFile(
  file: File,
  kind: "package" | "archive",
  maximum: number,
) {
  const extension = kind === "package" ? ".rov" : ".tar";
  if (!file.name.toLowerCase().endsWith(extension))
    throw Error(
      kind === "package"
        ? "请选择 .rov 设备包"
        : "镜像仅支持未压缩的 .tar 文件",
    );
  if (!file.size) throw Error("文件不能为空");
  if (file.size > maximum) throw Error("文件超过宿主机上传大小限制");
}
