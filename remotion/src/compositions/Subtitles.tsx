import React from 'react';
import { AbsoluteFill,useCurrentFrame,useVideoConfig } from 'remotion';
import type { SubtitleConfig } from '../lib/types';
import { normalizeCaptions,groupCaptionsIntoBlocks,getActiveWordIndex,textWidth,captionY,captionScale } from '../lib/captions';
import { getFontStack,antonFontFace } from '../lib/fonts';
export const Subtitles: React.FC<{config: SubtitleConfig}>=({config})=>{
  const frame=useCurrentFrame();
  const {fps,width,height,durationInFrames}=useVideoConfig();
  // Composition time avoids rounded Sequence-start offsets at every FPS.
  const now=frame/fps*1000;
  const {style}=config;
  const size=Math.min(Math.max(24,Math.min(240,style.fontSize))*width/1080,height*.14);
  const lines=Math.max(1,Math.min(3,style.maxLines??2));
  const capacity=Math.max(6,Math.floor(width*.76/(size*.72)));
  const words=normalizeCaptions(config.captions,durationInFrames/fps*1000,config.syncOffsetMs??0);
  const block=groupCaptionsIntoBlocks(words,capacity*lines,2500,style.maxWords??6,style.minPhraseMs??450).find(b=>b.startMs<=now && now<b.endMs);
  if(!block) return null;
  const blurs=config.blurRanges??[];
  const bottom=Math.max(0,...blurs.filter(([a,b])=>a<block.endMs/1000 && block.startMs/1000<b).map(r=>r[2]));
  const rowLimit=bottom>0 && bottom<.76?1:lines;
  const rows: typeof words[]=[[]];let used=0;
  for(const word of block.words) {
    const n=textWidth(word.text);
    if(used && used+n+1>capacity && rows.length<rowLimit) {rows.push([]);used=0;}
    rows[rows.length-1].push(word);used+=n+1;
  }
  const longest=Math.max(...rows.map(row=>textWidth(row.map(w=>w.text).join(' '))));
  let fitted=size*Math.min(1,width*.76/Math.max(1,longest*size*1.05));

  if(bottom>0 && bottom<.76) fitted=Math.min(fitted,(.8-bottom-.04)*height/(rows.length*(style.lineSpacing??1.25)));
  const placementTime=Math.max(block.startMs,...blurs.flatMap(r=>r.slice(0,2).map(t=>t*1000)).filter(t=>block.startMs<t && t<=now));
  const y=captionY(placementTime,config.position,rows.length,fitted/height,config.splitRanges,config.editorialRanges,config.faceRegions,block.endMs,style.lineSpacing??1.25,blurs);
  const active=getActiveWordIndex(block.words,now);
  const shadow=style.shadow??1;
  let inactiveColor=style.fontColor;
  const rgb=/^#([a-f\d]{6})$/i.exec(style.fontColor);
  if(rgb && style.baseOpacity!=null && style.baseOpacity<1) {
    const factor=.5+.5*Math.max(.05,style.baseOpacity);
    inactiveColor='#'+[0,2,4].map(i=>Math.round(parseInt(rgb[1].slice(i,i+2),16)*factor).toString(16).padStart(2,'0')).join('');
  }
  const opacity=style.animation==='fade'?Math.min(1,(now-block.startMs)/70):1;
  const scale=style.animation==='pop' || style.animation==='bounce'?captionScale(style.animation,now-block.startMs):1;
  return <AbsoluteFill style={{pointerEvents:'none'}}>
    <style>{antonFontFace}</style>
    <div style={{position:'absolute',left:'48%',top:`${y*100}%`,transform:`translate(-50%,-50%) scale(${scale})`,
      maxWidth:'76%',textAlign:'center',whiteSpace:'nowrap',fontFamily:getFontStack(style.fontFamily),
      fontSize:fitted,fontWeight:700,lineHeight:style.lineSpacing??1.25,color:style.fontColor,
      backgroundColor:`${style.bgColor}${Math.round(Math.max(0,Math.min(1,style.bgOpacity))*255).toString(16).padStart(2,'0')}`,
      padding:style.bgOpacity>0?`${fitted*.15}px ${fitted*.2}px`:0,borderRadius:4,opacity}}>
      {rows.map((row,ri)=><div key={ri}>{row.map((word,i)=>{
        const isActive=block.words.indexOf(word)===active;
        const emphasis=(style.animation==='word-scale' || word.emphasis) && isActive?captionScale('scale',now-word.startMs,word.endMs-word.startMs,word.emphasis):1;
        return <React.Fragment key={i}>{i>0?' ':''}<span style={{display:'inline-block',transform:`scale(${emphasis})`,
          color:isActive?(style.animation==='karaoke'?style.bgColor:style.highlightColor):inactiveColor,
          opacity:style.animation==='word-reveal' && word.aligned!==false && now<word.startMs?0:1,
          backgroundColor:isActive && style.animation==='karaoke'?style.highlightColor:'transparent',borderRadius:3,
          WebkitTextStroke:`${style.borderWidth*width/1080}px ${style.borderColor}`,paintOrder:'stroke fill',
          textShadow:`${shadow*width/1080}px ${shadow*width/1080}px ${shadow*width/1080}px #000000${isActive && style.animation==='word-highlight'?`,0 0 ${fitted*.05}px ${style.highlightColor}`:''}`,
          overflowWrap:'anywhere'}}>{style.uppercase?word.text.toUpperCase():word.text}</span></React.Fragment>;
      })}</div>)}
    </div>
  </AbsoluteFill>;
};
