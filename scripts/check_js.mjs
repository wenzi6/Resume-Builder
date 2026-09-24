#!/usr/bin/env node
/** 前端语法检查（零依赖）：node --check 在 ESM 模式下逐文件解析。
 *  依赖仓库根 package.json 的 "type": "module"。
 *  用法：node scripts/check_js.mjs  （或 npm run check）
 */
import { execFileSync } from "node:child_process";
import { readdirSync, statSync } from "node:fs";
import { join } from "node:path";

function walk(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...walk(p));
    else if (name.endsWith(".js")) out.push(p);
  }
  return out;
}

const files = walk("static/js");
let failed = 0;
for (const f of files) {
  try {
    execFileSync(process.execPath, ["--check", f], { stdio: "pipe" });
    console.log("OK  " + f);
  } catch (e) {
    failed++;
    console.error("FAIL " + f);
    console.error(e.stderr?.toString() || e.message);
  }
}
console.log(`\n${files.length - failed}/${files.length} 文件语法正确`);
process.exit(failed ? 1 : 0);
