import { rmSync } from "node:fs";
import { fileURLToPath } from "node:url";

const outputDirectory = fileURLToPath(
  new URL("../src/rune_web/static/build/", import.meta.url),
);

rmSync(outputDirectory, { recursive: true, force: true });
