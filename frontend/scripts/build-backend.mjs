import { cp, mkdtemp, rename, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "vite";

const frontendDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const projectDir = resolve(frontendDir, "..");
const staticDir = resolve(projectDir, "backend", "app", "static");
const parentDir = dirname(staticDir);
const tempRoot = await mkdtemp(resolve(tmpdir(), "upil-vue-build-"));
const tempDist = resolve(tempRoot, "dist");
const stagedStatic = resolve(parentDir, ".static-vue-next");
const backupStatic = resolve(parentDir, ".static-vue-previous");

try {
  // 先在系统临时目录完成整套构建；若 Vite 失败，现有静态目录完全不动。
  await build({ root: frontendDir, build: { outDir: tempDist, emptyOutDir: true } });

  // 复制完成后才执行目录级切换，避免 --emptyOutDir 在失败时留下半套产物。
  await rm(stagedStatic, { recursive: true, force: true });
  await cp(tempDist, stagedStatic, { recursive: true });
  await rm(backupStatic, { recursive: true, force: true });
  await rename(staticDir, backupStatic);
  try {
    await rename(stagedStatic, staticDir);
  } catch (error) {
    // 新目录切换失败时立即恢复旧静态页，不能破坏当前可运行工作区。
    await rename(backupStatic, staticDir);
    throw error;
  }
  await rm(backupStatic, { recursive: true, force: true });
} finally {
  await rm(stagedStatic, { recursive: true, force: true });
  await rm(tempRoot, { recursive: true, force: true });
}
