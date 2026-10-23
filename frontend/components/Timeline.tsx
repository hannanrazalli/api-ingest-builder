import {Check, Circle, LoaderCircle, Pause, X} from "lucide-react";
import type {Event} from "../lib/events";
const stages=["prober","fetcher","retriever","extractor","verifier","profiler"];
export function Timeline({events}: {events: Event[]}) {
  return <div className="timeline" aria-label="Agent timeline">{stages.map(agent=>{const event=events.filter(e=>e.agent===agent).at(-1); const state=event?.state ?? "idle"; const Icon=state==="success"?Check:state==="error"?X:state==="working"||state==="walking"?LoaderCircle:state==="sleeping"||state==="waiting"?Pause:Circle;return <div key={agent} className={`timeline-step state-${state}`} title={event?.task}><Icon size={12} aria-hidden="true"/><span>{agent}</span></div>;})}</div>;
}
