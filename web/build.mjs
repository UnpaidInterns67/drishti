import { mkdir, copyFile } from "node:fs/promises";

// Explicit allowlist: never copy Python code, identity files, or runtime secrets.
await mkdir(new URL("./dist/assets/", import.meta.url), { recursive: true });
await copyFile(new URL("./index.html", import.meta.url), new URL("./dist/index.html", import.meta.url));
for (const filename of ["app.js", "styles.css"]) {
  await copyFile(new URL(`./${filename}`, import.meta.url), new URL(`./dist/assets/${filename}`, import.meta.url));
}
