import {agents,layout,palette as p,type Agent,type World,zones} from "./office";
const sprite=["..hhhh..",".hhhhh..","..ssss..","..s.ss..","...ss...","..bbbb..",".bbbbbb.",".b.bb.b.","...bb...","..l..l..","..l..l.."];
export function drawOffice(ctx:CanvasRenderingContext2D,world:World,time:number,selected:Agent|null,reduced:boolean,zoom=1){
 const width=layout.width*16,height=layout.height*16;ctx.imageSmoothingEnabled=false;ctx.fillStyle=p[0];ctx.fillRect(0,0,width,height);ctx.save();
 if(selected&&zoom>1){const pos=world.characters[selected].position;const x=Math.max(0,Math.min(width-width/zoom,pos[0]*16-width/zoom/2)),y=Math.max(0,Math.min(height-height/zoom,pos[1]*16-height/zoom/2));ctx.scale(zoom,zoom);ctx.translate(-x,-y);}
 const rect=(x:number,y:number,w:number,h:number,color:string)=>{ctx.fillStyle=color;ctx.fillRect(Math.round(x),Math.round(y),w,h);};
 for(let y=0;y<layout.height;y++)for(let x=0;x<layout.width;x++){rect(x*16,y*16,16,16,(x+y)%2?p[1]:p[0]);if(y%3===0&&x%3===0)rect(x*16,y*16,1,1,p[2]);}
 for(const zone of zones){const x=zone.x*16,y=zone.y*16,w=zone.w*16,h=zone.h*16;rect(x+2,y+5,w,h,p[0]);rect(x,y,w,h,p[2]);rect(x+1,y+1,w-2,h-2,p[1]);rect(x,y,w,2,p[3]);rect(x+8,y+18,w-16,1,p[3]);ctx.font="bold 7px monospace";ctx.fillStyle=p[4];ctx.fillText(zone.name.toUpperCase(),x+9,y+12);
  // Desk, cast shadow, monitor, chair and the role's procedural prop.
  rect(x+18,y+35,w-36,25,p[0]);rect(x+16,y+32,w-32,22,p[11]);rect(x+16,y+32,w-32,3,p[10]);rect(x+39,y+25,26,19,p[0]);rect(x+41,y+27,22,14,p[15]);rect(x+44,y+30,14,2,p[14]);rect(x+44,y+34,8,2,p[8]);rect(x+49,y+44,5,4,p[3]);rect(x+35,y+71,22,11,p[0]);rect(x+37,y+70,18,9,p[3]);
  if(zone.agent==="retriever"){for(let i=0;i<6;i++)rect(x+20+i*4,y+23,3,9,p[6+i%5]);}
  else if(zone.agent==="generator"){rect(x+76,y+25,19,17,p[4]);rect(x+79,y+21,13,8,p[5]);const active=world.characters.generator.state==="working";rect(x+79,y+39,13,active&&!reduced?7+Math.floor(time/200)%4:6,p[5]);}
  else if(zone.agent==="profiler"){ctx.strokeStyle=p[14];ctx.lineWidth=2;ctx.strokeRect(x+77,y+24,8,8);rect(x+85,y+33,7,2,p[14]);}
  else if(zone.agent==="verifier"){rect(x+78,y+26,6,14,p[14]);rect(x+79,y+32,4,7,p[8]);}
  else if(zone.agent==="repair"){rect(x+77,y+24,10,4,p[4]);rect(x+80,y+27,4,14,p[4]);}
  else if(zone.agent==="extractor"){rect(x+77,y+25,10,8,p[12]);rect(x+79,y+23,6,12,p[12]);}
  else if(zone.agent==="fetcher"){rect(x+76,y+26,15,13,p[10]);rect(x+82,y+26,3,13,p[11]);}
  else{rect(x+76,y+25,12,15,p[5]);rect(x+78,y+28,7,1,p[3]);rect(x+78,y+32,6,1,p[3]);}
  // Plants use the same 16-color palette; no external assets.
  rect(x+w-13,y+h-15,7,7,p[11]);rect(x+w-14,y+h-23,9,9,p[9]);rect(x+w-11,y+h-26,3,11,p[8]);
 }
 // Corridor signage.
 ctx.font="7px monospace";ctx.fillStyle=p[3];ctx.fillText("API INGEST / RESEARCH FLOOR",18,layout.height*16-8);
 const ordered=[...agents].sort((a,b)=>world.characters[a].position[1]-world.characters[b].position[1]);
 for(const agent of ordered){const c=world.characters[agent];if(!c.event)continue;const zone=zones.find(z=>z.agent===agent)!;const x=c.position[0]*16+4,y=c.position[1]*16-3;const moving=c.path.length>0,bob=!reduced&&(moving||c.state==="working")?Math.floor(time/180)%2:0;
  rect(x+1,y+21,13,3,p[0]);if(agent===selected){ctx.strokeStyle=p[6];ctx.lineWidth=1;ctx.strokeRect(x-2,y-3,21,28);}
  const colors:Record<string,string>={h:p[3],s:p[5],b:p[6+(zone.color%10)],l:p[4]};
  sprite.forEach((line,dy)=>[...line].forEach((color,dx)=>{if(color!==".")rect(x+dx*2,y+dy*2-bob,2,2,colors[color]);}));
  const emote=c.state==="error"?"!":c.state==="waiting"?"||":c.state==="sleeping"?"z":c.state==="success"?"+":c.state==="working"?"...":"^";
  rect(x+1,y-12,17,9,p[0]);ctx.fillStyle=c.state==="error"?p[12]:c.state==="success"?p[8]:p[5];ctx.font="bold 7px monospace";ctx.fillText(emote,x+4,y-5);
  if(c.usage&&agent==="extractor"){ctx.fillStyle=p[10];ctx.font="6px monospace";ctx.fillText(c.usage.input_tokens===null?"quota":`${Math.round(c.usage.input_tokens*(reduced?1:Math.min(1,c.ticks/30)))} tok`,x-5,y-17);}
 }
 if(world.blocked){rect(17*16,18*16,8*16,5,p[12]);for(let i=0;i<8;i++)rect((17+i)*16,18*16,7,5,p[0]);ctx.fillStyle=p[12];ctx.font="7px monospace";ctx.fillText("COST GUARD / APPROVAL REQUIRED",17*16,18*16-5);}
 if(world.saved){rect(19*16,8*16,12,9,p[10]);rect(20*16,8*16+2,8,8,p[5]);}
 ctx.restore();
}
