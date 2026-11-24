import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "@playwright/test";

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(currentDir, "..");
const userLocalBin = path.join(os.homedir(), ".local", "bin");
const inheritedPath = process.env["PATH"] ?? "/usr/local/bin:/usr/bin:/bin";
const serverPath = `${userLocalBin}:${inheritedPath}`;
const chromeBinary = process.env["CHROME_EXECUTABLE_PATH"] ?? "/usr/bin/google-chrome";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 45_000,
  expect: {
    timeout: 10_000,
  },
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:5174",
    trace: "retain-on-failure",
    browserName: "chromium",
    launchOptions: {
      executablePath: chromeBinary,
      args: ["--no-sandbox", "--disable-gpu", "--font-render-hinting=none"],
    },
  },
  webServer: [
    {
      command: "uv run uvicorn app.fast_api_app:app --host 127.0.0.1 --port 18100",
      cwd: repoRoot,
      url: "http://127.0.0.1:18100/api/health",
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        PATH: serverPath,
        APP_ENV: "local",
        BREW_AUTH_MODE: "local_mock",
        BREW_PERSISTENCE_BACKEND: "in_memory",
        BREW_SESSION_BACKEND: "in_memory",
        BREW_BRIEF_COACH_BACKEND: "fake",
        BREW_MEMORY_EXTRACTOR_BACKEND: "fake",
        OTEL_TO_CLOUD: "false",
        ALLOW_ORIGINS:
          "http://localhost:5174,http://127.0.0.1:5174,http://localhost:5173,http://127.0.0.1:5173",
      },
    },
    {
      command: "node ./node_modules/vite/bin/vite.js --host localhost --port 5174 --strictPort",
      cwd: currentDir,
      url: "http://localhost:5174",
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        PATH: serverPath,
        BACKEND_ORIGIN: "http://127.0.0.1:18100",
      },
    },
  ],
});
