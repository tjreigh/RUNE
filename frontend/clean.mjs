import { rmSync } from "node:fs";
import { fileURLToPath } from "node:url";

const browserOutputDirectory = fileURLToPath(
  new URL("../src/rune_web/static/build/", import.meta.url),
);
const testOutputDirectory = fileURLToPath(
  new URL("../build/frontend-tests/", import.meta.url),
);

rmSync(browserOutputDirectory, { recursive: true, force: true });
rmSync(testOutputDirectory, { recursive: true, force: true });
