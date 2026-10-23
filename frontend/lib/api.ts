import type { Event } from "./events";
export type Param = { name: string; location: string; required: boolean; type: string; default: unknown; description: string; allowed_values: unknown[] | null };
export type Endpoint = { path: string; method: string; description: string; source_url: string; verified: boolean; params: Param[]; date_params: {start: string; end: string | null; format: string} | null; pagination: { type: string } | null; record_path: string | null; response_sample_ref: string | null };
export type Spec = {name: string; base_url: string; auth: {required: boolean; type: string; signup_url: string | null; env_var: string}; endpoints: Endpoint[]; rate_limit: unknown; unsupported_reason: string | null};
export type Job = {id: string; status: string; calls: number; input_tokens: number | null; output_tokens: number | null; cost_usd: number | null; prompt_chars: number; created_at: string};
export type Research = {job: Job; status: string; spec: Spec | null; profile: {nested: boolean; record_path: string | null; nesting_depth: number} | null; warnings: string[]; cache_hit: boolean; saved_tokens: number | null; demo: boolean};
export type Settings = {provider: "openai" | "anthropic" | "codex_cli"; base_url: string | null; model_fast: string; model_smart: string; demo_mode: boolean; onboarded: boolean; has_api_key: boolean; api_key_masked: string; usage_label: string; env_overrides: string[]; max_llm_calls: number; max_input_tokens: number; max_output_tokens: number; max_prompt_chars: number};
export type History = {job: Job; result: Research | null}[];
export type Generated = {code: string; filename: string; sample: unknown; flattened_sample: string | null; events: Event[]};
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {...init, headers: {"Content-Type": "application/json", ...init?.headers}});
  if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(typeof data.detail === "string" ? data.detail : "Request failed. Check your inputs and try again."); }
  return response.json();
}
export function post<T>(path: string, data: unknown) {return api<T>(path, {method: "POST", body: JSON.stringify(data)});}
