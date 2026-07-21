import { expect, test, type Page } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const repoRoot = path.resolve(__dirname, "../../..");
const python = path.join(repoRoot, ".venv", "Scripts", "python.exe");

async function waitForHealth(port: number): Promise<void> {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/healthz`);
      if (response.ok) return;
    } catch {
      // Server is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`local API did not become healthy on ${port}`);
}

async function stopServer(server: ChildProcess | undefined): Promise<void> {
  if (!server || server.exitCode !== null) return;
  await new Promise<void>((resolve) => {
    server.once("exit", () => resolve());
    server.kill();
    setTimeout(() => {
      if (server.exitCode === null) server.kill("SIGKILL");
      resolve();
    }, 5_000);
  });
}

async function api<T>(page: Page, pathName: string, init: RequestInit = {}): Promise<T> {
  return page.evaluate(
    async ({ pathName, init }) => {
      const token = sessionStorage.getItem("pushkey:session");
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 30_000);
      const response = await fetch(pathName, {
        ...init,
        signal: controller.signal,
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
          ...(init.headers || {}),
        },
      }).finally(() => window.clearTimeout(timeout));
      const text = await response.text();
      const body = text ? JSON.parse(text) : null;
      if (!response.ok) throw new Error(`${response.status}: ${text}`);
      return body;
    },
    { pathName, init },
  ) as Promise<T>;
}

test("local vault browser journey unlocks, mutates, injects, and locks", async ({ page }) => {
  const home = mkdtempSync(path.join(tmpdir(), "pushkey-e2e-"));
  const projectDir = path.join(home, "project");
  mkdirSync(projectDir);
  writeFileSync(path.join(projectDir, ".gitignore"), "", "utf-8");
  const token = "e2e-launch-token";
  const port = 7765;

  const seed = [
    "from pushkey_vault import save_vault",
    "save_vault({'EXISTING_KEY': {'value': 'sk-existing', 'env': 'dev', 'projects': []}}, 'test-password', recovery_code='PUSH-AAAA-BBBB-CCCC-DDDD')",
  ].join("; ");
  const seedResult = spawn(python, ["-c", seed], {
    cwd: repoRoot,
    env: {
      ...process.env,
      HOME: home,
      USERPROFILE: home,
      PYTHONPATH: repoRoot,
    },
  });
  await new Promise<void>((resolve, reject) => {
    seedResult.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`seed exited ${code}`))));
    seedResult.on("error", reject);
  });

  let server: ChildProcess | undefined;
  try {
    server = spawn(python, ["pushkey_local_api.py"], {
      cwd: repoRoot,
      env: {
        ...process.env,
        HOME: home,
        USERPROFILE: home,
        PYTHONPATH: repoRoot,
        PUSHKEY_LAUNCH_TOKEN: token,
        PUSHKEY_LOCAL_PORT: String(port),
      },
      stdio: "ignore",
    });
    await waitForHealth(port);

    await page.goto(`http://127.0.0.1:${port}/#t=${token}`);
    await expect(page.locator("body")).toContainText("Pushkey");
    await expect.poll(() => page.evaluate(() => sessionStorage.getItem("pushkey:session"))).toBeTruthy();

    await api(page, "/api/unlock", {
      method: "POST",
      body: JSON.stringify({ password: "test-password" }),
    });
    const before = await api<{ keys: { name: string }[] }>(page, "/api/keys");
    expect(before.keys.map((key) => key.name)).toContain("EXISTING_KEY");

    await api(page, "/api/keys", {
      method: "POST",
      body: JSON.stringify({ name: "NEW_KEY", value: "sk-new", env: "dev" }),
    });
    await api(page, "/api/keys/NEW_KEY/rotate", {
      method: "POST",
      body: JSON.stringify({ new_value: "sk-rotated" }),
    });
    const revealed = await api<{ value: string }>(page, "/api/keys/NEW_KEY");
    expect(revealed.value).toBe("sk-rotated");

    await api(page, "/api/projects", {
      method: "POST",
      body: JSON.stringify({ path: projectDir, name: "E2E Project" }),
    });
    await api(page, `/api/projects/assign?path=${encodeURIComponent(projectDir)}`, {
      method: "POST",
      body: JSON.stringify({ keys: ["NEW_KEY"] }),
    });
    const injected = await api<{ injected: string[]; wrote: boolean }>(
      page,
      `/api/projects/inject?path=${encodeURIComponent(projectDir)}&write=true`,
      { method: "POST", body: JSON.stringify({}) },
    );
    expect(injected).toMatchObject({ injected: ["NEW_KEY"], wrote: true });

    const locked = await api<{ locked: boolean }>(
      page,
      "/api/lock",
      { method: "POST", body: JSON.stringify({}) },
    );
    expect(locked.locked).toBe(true);
  } finally {
    await stopServer(server);
  }
});
