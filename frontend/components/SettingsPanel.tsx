"use client";
import {FormEvent, useEffect, useState} from "react";
import {api, post, type Settings} from "../lib/api";
import {Button} from "./ui/button";
export function SettingsPanel({settings, onSaved}: {settings: Settings; onSaved: (settings: Settings) => void}) {
  const [provider,setProvider] = useState(settings.provider);
  const [message,setMessage] = useState("");
  const [busy,setBusy] = useState(false);
  const [cli,setCli] = useState<{logged_in:boolean;message:string} | null>(null);
  async function check() {setCli({logged_in:false,message:"Checking local Codex..."}); try {setCli(await api("/api/providers/codex/status"));} catch {setCli({logged_in:false,message:"Could not check Codex. Start the backend on this host."});}}
  useEffect(() => {if(provider === "codex_cli") void check();}, [provider]);
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setMessage(""); const form=event.currentTarget; const data=new FormData(form);
    const value: Record<string,unknown>={provider,base_url:data.get("base_url") || null,model_fast:data.get("model_fast") || "",model_smart:data.get("model_smart") || ""};
    if(data.get("api_key")) value.api_key=data.get("api_key");
    try {onSaved(await api<Settings>("/api/settings",{method:"PUT",body:JSON.stringify(value)}));form.reset();} catch(error){setMessage((error as Error).message);} finally {setBusy(false);}
  }
  return <form className="settings-form" onSubmit={save}><p className="muted">Choose a provider or explore recorded examples. Keys stay in your local database.</p>
    <label>Provider<select aria-label="Provider" value={provider} onChange={e => setProvider(e.target.value as Settings["provider"])}><option value="openai">OpenAI / compatible local server</option><option value="anthropic">Anthropic</option><option value="codex_cli">Use my local Codex (no API key)</option></select></label>
    {provider === "codex_cli" ? <div className="notice"><strong>Host mode - uses Codex quota</strong><p>Run the backend with <code>scripts/dev.ps1</code>. Docker does not include Codex or mount login files.</p><p role="status">{cli?.message ?? "Checking Codex..."}</p>{!cli?.logged_in && <p>Install Codex on PATH, then run <code>codex --version</code> and <code>codex login</code>.</p>}<Button type="button" variant="secondary" onClick={check}>Check Codex again</Button></div> : <><label>Base URL <span className="muted">optional</span><input name="base_url" type="url" defaultValue={settings.base_url ?? ""} placeholder="https://provider.example/v1"/></label><label>API key<input name="api_key" type="password" autoComplete="off" placeholder={settings.api_key_masked || "Enter locally; never share in chat"}/></label></>}
    <div className="form-grid"><label>Fast model<input name="model_fast" defaultValue={settings.model_fast} placeholder={provider === "codex_cli" ? "CLI default" : "Configured model name"}/></label><label>Smart model<input name="model_smart" defaultValue={settings.model_smart} placeholder={provider === "codex_cli" ? "CLI default" : "Configured model name"}/></label></div>
    <small className="muted">Check vendor documentation for current model names. Local compatible servers use OpenAI with a custom base URL.</small>
    {!!settings.env_overrides.length && <div className="notice">Environment overrides take priority: {settings.env_overrides.join(", ")}</div>}
    {message && <p role="alert" className="error-text">{message}</p>}
    <div className="dialog-actions"><Button type="button" variant="secondary" disabled={busy} onClick={async()=>{try{onSaved(await post<Settings>("/api/onboarding/demo",{}));}catch(e){setMessage((e as Error).message);}}}>Use Demo mode</Button><Button disabled={busy}>Save settings</Button></div>
  </form>;
}
