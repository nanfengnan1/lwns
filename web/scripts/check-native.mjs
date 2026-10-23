// Run before Vite so a shared Windows/Linux checkout gets an actionable error.
// Import the actual loader: a package can exist but still have the wrong ABI.
try {
  await import("rolldown");
} catch (error) {
  console.error(
    `[route-ovs] 无法加载 ${process.platform}/${process.arch} 的前端原生依赖。`,
  );
  console.error(
    "Windows 和 Linux 不能直接复用 node_modules。请在要运行 Vite 的系统中，" +
      "从项目根目录执行：\n\n" +
      "  npm --prefix web ci --include=optional\n\n" +
      "保留 package-lock.json；npm ci 会按锁文件重新安装当前平台的依赖。\n" +
      "通过 Samba 共享源码时，建议分别使用独立检出目录安装依赖。",
  );
  // The loader's generic advice to delete the lockfile does not apply when
  // our lockfile already contains the required platform packages.
  const summary =
    error instanceof Error
      ? error.message.split(". npm has a bug")[0]
      : String(error);
  console.error(`原始错误：${summary}`);
  process.exitCode = 1;
}
