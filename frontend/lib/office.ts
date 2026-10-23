import layout from "./office-layout.json";
import type {Event,Usage} from "./events";
export type Point=[number,number];
export type Agent=Event["agent"];
export type Character={position:Point;path:Point[];state:Event["state"];task:string;detail:string|null;usage:Usage|null;started:number;ended:number;event:Event|null;ticks:number};
export type World={characters:Record<Agent,Character>;visited:string[];log:Event[];blocked:boolean;saved:boolean;tokens:number|null;cost:number|null};
export const zones=layout.zones;
export const agents=zones.map(z=>z.agent as Agent);
export const palette=["#111622","#1b2332","#293347","#3c4a60","#b6c4d8","#f4dfbd","#b1a3ff","#7462d8","#75d4ac","#3b8c79","#e5bc73","#bc7e57","#ed8796","#7c526e","#87b9dc","#4c729a"];
export function walkable([x,y]:Point){if(x<0||y<0||x>=layout.width||y>=layout.height)return false;return !zones.some(z=>x>=z.x+1&&x<z.x+z.w-1&&y>=z.y+2&&y<=z.y+3);}
export function astar(start:Point,end:Point):Point[]{
 const key=(p:Point)=>p.join(",");if(!walkable(start)||!walkable(end))return [];
 const open:Point[]=[start],came=new Map<string,Point>(),cost=new Map([[key(start),0]]),closed=new Set<string>();
 const h=(p:Point)=>Math.abs(p[0]-end[0])+Math.abs(p[1]-end[1]);
 while(open.length){open.sort((a,b)=>(cost.get(key(a))!+h(a))-(cost.get(key(b))!+h(b)));const current=open.shift()!,k=key(current);if(closed.has(k))continue;if(k===key(end)){const path:Point[]=[];let p=current;while(key(p)!==key(start)){path.unshift(p);p=came.get(key(p))!;}return path;}closed.add(k);
  for(const [dx,dy]of [[1,0],[-1,0],[0,1],[0,-1]]){const next:Point=[current[0]+dx,current[1]+dy],n=key(next),g=cost.get(k)!+1;if(walkable(next)&&g<(cost.get(n)??Infinity)){came.set(n,current);cost.set(n,g);open.push(next);}}
 }return [];
}
export function initialWorld():World{
 const characters=agents.reduce((all,agent)=>{all[agent]={position:[...layout.entrance] as Point,path:[],state:agent==="repair"?"sleeping":"idle",task:"Waiting for a backend event",detail:null,usage:null,started:0,ended:0,event:null,ticks:0};return all;},{} as Record<Agent,Character>);
 return{characters,visited:[],log:[],blocked:false,saved:false,tokens:0,cost:0};
}
export function applyEvent(world:World,event:Event,reduced=false):World{
 const previous=world.characters[event.agent];if(!previous)return world;
 const zone=zones.find(z=>z.agent===event.agent)!;
 const destination:Point=event.agent==="repair"&&event.state!=="sleeping"?zones.find(z=>z.agent==="verifier")!.target as Point:event.cache_hit&&event.agent==="prober"?layout.entrance as Point:zone.target as Point;
 const character:Character={...previous,state:event.state,task:event.task,detail:event.detail,usage:event.llm??previous.usage,event,ticks:event.llm?0:previous.ticks,started:event.state==="walking"||!previous.started?event.ts:previous.started,ended:["success","error"].includes(event.state)?event.ts:previous.ended};
 // A sleep/skip event does not invent work or movement.
 let visited=world.visited;
 if(event.state!=="sleeping"&&event.state!=="idle"){
  const via=event.agent==="repair"&&!world.visited.includes("repair")?zone.target as Point:event.cache_hit&&event.agent==="prober"?zone.target as Point:null;
  character.path=via?[...astar(character.position,via),...astar(via,destination)]:astar(character.position,destination);
  if(reduced){character.position=destination;character.path=[];visited=Array.from(new Set([...visited,event.agent]));}
 }
 const last=world.log.at(-1);const duplicate=last&&last.agent===event.agent&&last.state===event.state&&last.task===event.task;
 const result={...world,characters:{...world.characters,[event.agent]:character},visited,log:duplicate?world.log:[...world.log.slice(-249),event],blocked:event.state==="waiting"||world.blocked,saved:!!event.cache_hit||world.saved};
 if(event.llm){result.tokens=event.llm.input_tokens===null||world.tokens===null?null:world.tokens+event.llm.input_tokens;result.cost=event.llm.cost_usd===null||world.cost===null?null:world.cost+event.llm.cost_usd;}
 return result;
}
export function tick(world:World):World{
 const characters={...world.characters};let visited=world.visited,changed=false;
 for(const agent of agents){let old=characters[agent];if(old.usage&&old.ticks<30){changed=true;old={...old,ticks:old.ticks+1};characters[agent]=old;}if(!old.path.length)continue;changed=true;const [position,...path]=old.path;characters[agent]={...old,position,path};if(!path.length)visited=Array.from(new Set([...visited,agent]));}
 return changed?{...world,characters,visited}:world;
}
export {layout};
