import type { CaptionWord } from './types';
export interface CaptionBlock { words: CaptionWord[]; startMs: number; endMs: number; text: string }
export function normalizeCaptions(words: CaptionWord[], durationMs=Infinity, offsetMs=0): CaptionWord[] {
  const output: CaptionWord[]=[];
  for (const w of [...words].filter(w=>w && Number.isFinite(w.startMs) && Number.isFinite(w.endMs)
      && w.endMs>w.startMs && w.text?.trim()).sort((a,b)=>a.startMs-b.startMs || a.endMs-b.endMs)) {
    const a=Math.max(0,w.startMs+Math.max(-1000,Math.min(1000,offsetMs)));
    const b=Math.min(durationMs,w.endMs+Math.max(-1000,Math.min(1000,offsetMs)));
    if (b<=a) continue;
    const previous=output[output.length-1];
    if (previous && a<previous.endMs) {
      if (a<=previous.startMs) {previous.text+=' '+w.text.trim();previous.endMs=Math.max(previous.endMs,b);previous.aligned=false;continue;}
      previous.endMs=a;
    }
    output.push({...w,text:w.text.trim().replace(/\s+/g,' '),startMs:a,endMs:b});
  }
  return output;
}
export function textWidth(text: string): number {
  return Array.from(text).reduce((n,c)=>n+(/\p{Mark}/u.test(c)?0:/[\u1100-\u11ff\u2e80-\ua4cf\uac00-\ud7ff\uf900-\ufaff\uff01-\uff60]/u.test(c)?2:1),0);
}
export function groupCaptionsIntoBlocks(captions: CaptionWord[], maxChars=30,maxDurationMs=2500,maxWords=6,minDurationMs=0): CaptionBlock[] {
  const blocks: CaptionBlock[]=[];let current: CaptionWord[]=[];
  const finish=()=>{if(current.length) blocks.push({words:current,startMs:current[0].startMs,endMs:current[current.length-1].endMs,text:current.map(w=>w.text).join(' ')});current=[];};
  for(const word of normalizeCaptions(captions)) {
    if(current.length && (word.startMs-current[current.length-1].endMs>450 ||
       (/[.!?。！？]["'”’)]*$/.test(current[current.length-1].text) && current[current.length-1].endMs-current[0].startMs>=minDurationMs) ||
       textWidth(current.map(w=>w.text).join(' ')+' '+word.text)>maxChars ||
       current.length>=maxWords || word.endMs-current[0].startMs>maxDurationMs)) finish();
    current.push(word);
  }
  finish();
  blocks.forEach((block,i)=>{block.endMs=Math.min(blocks[i+1]?.startMs ?? Infinity,
      Math.max(block.endMs+120,block.startMs+Math.max(150,minDurationMs || 450)));});
  return blocks;
}
export function getActiveWordIndex(words: CaptionWord[], timeMs: number): number {
  return words.findIndex(w=>w.aligned!==false && timeMs>=w.startMs && timeMs<w.endMs);
}
export function captionY(timeMs: number,position: string,lines: number,fontRatio: number,
    splits: number[][]=[],editorials: number[][]=[],faces: {start?:number;end?:number;x:number;y:number;width:number;height:number}[]=[],endMs?:number,lineSpacing=1.25,blurs:number[][]=[]): number {
  const half=Math.min(.20,lines*fontRatio*lineSpacing/2+.015),lo=.12+half,hi=.80-half;
  const bottom=Math.max(0,...blurs.filter(([a,b])=>a<=timeMs/1000 && timeMs/1000<b).map(r=>r[2]));
  if(bottom>0 && bottom<.76) return Math.max(bottom+.015+half,hi);
  const inRange=(ranges:number[][])=>ranges.some(([a,b])=>a<=timeMs/1000 && timeMs/1000<b);
  const preferred=inRange(splits) ? .5 : inRange(editorials) ? .6 : position==='top'?lo:position==='middle' ? .46 : hi;
  const candidates=[preferred,hi,lo,.46].map(y=>Math.max(lo,Math.min(hi,y)));
  const collision=(y:number)=>faces.filter(f=>(f.start??0)<(endMs??timeMs+.001)/1000 && timeMs/1000<(f.end??Infinity)
      && f.x<.88 && f.x+f.width>.08).reduce((n,f)=>n+Math.max(0,Math.min(y+half,f.y+f.height)-Math.max(y-half,f.y)),0);
  return candidates.sort((a,b)=>collision(a)-collision(b) || Math.abs(a-preferred)-Math.abs(b-preferred))[0];
}

export function captionScale(effect:string,elapsed:number,duration=200,emphasis=false):number {
 const points=effect==='pop'?[[0,.94],[100,1.025],[200,1]]:effect==='bounce'?[[0,.98],[90,1.015],[220,1]]:[[0,1],[Math.min(80,duration/3),emphasis?1.06:1.03],[duration,1]];
 for(let i=1;i<points.length;i++) {const [a,x]=points[i-1], [b,y]=points[i];if(elapsed>=a && elapsed<b)return x+(y-x)*(elapsed-a)/(b-a);}
 return elapsed<0?points[0][1]:1;
}
