"use client";
import { FormEvent, useEffect, useState } from "react";

type Settings = { provider: "openai" | "anthropic" | "codex_cli"; base_url: string | null; model_fast: string; model_smart: string; onboarded: boolean; demo_mode: boolean; api_key_masked: string; env_overrides: string[]; usage_label: string };
const api = process.env.NEXT_PUBLIC_API_ORIGIN ?? "";
async function request(path: string, init?: RequestInit) {
  const response = await fetch(api + path, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  if (!response.ok) throw new Error("Could not save settings. Check the fields and backend connection.");
  return response.json();
}
export default function Home() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [status, setStatus] = useState("Connecting to local backend…");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [provider, setProvider] = useState("openai");
  const [cliStatus, setCliStatus] = useState<{message: string; logged_in: boolean} | null>(null);
  async function checkCodex() {
    setCliStatus({ message: "Checking local Codex version and login...", logged_in: false });
    try { setCliStatus(await request("/api/providers/codex/status")); }
    catch { setCliStatus({ message: "Could not check Codex. Run the backend on the host with scripts/dev.ps1.", logged_in: false }); }
  }
  useEffect(() => { if (provider === "codex_cli") void checkCodex(); }, [provider]);
  useEffect(() => { request("/api/settings").then(s => { setSettings(s); setProvider(s.provider); setStatus(""); }).catch(() => setStatus("Backend unavailable. Start the server and reload.")); }, []);
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setStatus("");
    const form = event.currentTarget;
    const fields = new FormData(form);
    const payload: Record<string, unknown> = { provider: fields.get("provider"), base_url: fields.get("base_url") || null, model_fast: fields.get("model_fast"), model_smart: fields.get("model_smart") };
    if (fields.get("api_key")) payload.api_key = fields.get("api_key");
    try { const s = await request("/api/settings", { method: "PUT", body: JSON.stringify(payload) }); form.reset(); setSettings(s); setEditing(false); setStatus("Settings saved locally."); }
    catch (error) { setStatus((error as Error).message); } finally { setBusy(false); }
  }
  async function demo() {
    setBusy(true);
    try { setSettings(await request("/api/onboarding/demo", { method: "POST" })); setEditing(false); setStatus("Demo selected. No LLM calls are made in Phase 1."); }
    catch (error) { setStatus((error as Error).message); } finally { setBusy(false); }
  }
  return <main><header><span className="eyebrow">Local workspace (Phase 1b) </span><h1>API Ingest Builder</h1><p>A foundation for portable, deterministic data engineering.</p></header>
    {settings && (!settings.onboarded || editing) ? <section className="panel"><h2>Set up your workspace</h2><p>Choose your provider, or explore the foundation in Demo mode. Keys stay in the local database and are never returned to the browser.</p>
      <form onSubmit={save}>
        <label>Provider<select name="provider" value={provider} onChange={e => setProvider(e.target.value)}><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option><option value="codex_cli">Use my local Codex (no API key)</option></select></label>
        {provider !== "codex_cli" ? <>
          <label>Base URL (optional)<input name="base_url" type="url" placeholder="OpenAI-compatible endpoint, including /v1" defaultValue={settings.base_url ?? ""}/></label>
          <label>API key<input name="api_key" type="password" autoComplete="off" placeholder={settings.api_key_masked || "Enter locally; never share in chat"}/></label>
        </> : <div>
          <p>Uses your saved local Codex login and Codex quota; no API key is needed. Run the backend directly on the host with <code>scripts/dev.ps1</code>. Docker does not include Codex or mount your login files.</p>
          <p role="status">{cliStatus?.message ?? "Checking Codex..."}</p>
          {!cliStatus?.logged_in && <p>Install the official Codex CLI, run <code>codex --version</code>, then <code>codex login</code> on this host. Restart the backend if PATH changed.</p>}
          <button type="button" className="secondary" onClick={checkCodex}>Check Codex again</button>
        </div>}
        <label>Fast model {provider === "codex_cli" && "(optional; CLI default if empty)"}<input name="model_fast" defaultValue={settings.model_fast}/></label>
        <label>Smart model {provider === "codex_cli" && "(optional)"}<input name="model_smart" defaultValue={settings.model_smart}/></label>
        <small>Check your vendor documentation for current model names. OpenAI-compatible servers use OpenAI with a custom base URL.</small>
        {settings.env_overrides.length > 0 && <small>Environment overrides: {settings.env_overrides.join(", ")}. These take priority.</small>}
        <div className="actions"><button disabled={busy}>Save settings</button><button type="button" className="secondary" disabled={busy} onClick={demo}>Use Demo mode</button></div>
      </form></section> : settings && <section className="panel"><span className="eyebrow">{settings.demo_mode ? "Demo mode" : "Provider configured"}</span><h2>Foundation ready</h2><p>Settings, cache, budgets and persistent event streaming are ready. Research starts in Phase 2; the product tabs arrive in later phases.</p><button className="secondary" onClick={() => setEditing(true)}>Manage settings</button><div className="grid">{["Builder · Phase 4", "Converter · Phase 5", "Explain · Phase 5", "Office · Phase 6"].map(t => <div className="tile" key={t}>{t}</div>)}</div></section>}
    <p role="status" aria-live="polite" className="status">{status}</p><footer><p aria-label="Usage meter">{settings?.usage_label ?? "Usage unavailable"}</p><small>Deterministic first · SQLite cache · No LLM calls on startup</small></footer></main>;
}
