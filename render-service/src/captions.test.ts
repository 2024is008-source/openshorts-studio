import test from 'node:test';
import assert from 'node:assert/strict';
const modulePath='../../remotion/src/lib/captions.ts';
const {normalizeCaptions,groupCaptionsIntoBlocks,getActiveWordIndex,captionY,captionScale}=await import(modulePath);

test('overlapping timing, clip clamps and sync preserve the millisecond clock',()=>{
 const words=normalizeCaptions([{text:'A',startMs:-100,endMs:300},{text:'B',startMs:200,endMs:1200}],1000,50);
 assert.deepEqual(words.map((w:{startMs:number;endMs:number})=>[w.startMs,w.endMs]),[[0,250],[250,1000]]);
 assert.equal(getActiveWordIndex(words,250),1);
 for(const fps of [24,25,30,60]) assert.equal(getActiveWordIndex(words,Math.ceil(.3*fps)/fps*1000),1);
});
test('configurable groups avoid punctuation flashes and respect maximum words',()=>{
 const words=Array.from({length:12},(_,i)=>({text:'Yes.',startMs:i*80,endMs:i*80+60}));
 const groups=groupCaptionsIntoBlocks(words,80,2500,4,450);
 assert.ok(groups.every((g:{words:unknown[]})=>g.words.length<=4));
 assert.equal(groups[0].words.length,4);
});
test('restrained animation curves use elapsed milliseconds',()=>{
 assert.equal(captionScale('pop',0),.94);
 assert.equal(captionScale('pop',200),1);
 assert.equal(captionScale('bounce',220),1);
 assert.ok(captionScale('scale',60,300,true)<=1.06);
});
test('punctuation and long pauses create readable phrases without held highlights',()=>{
 const blocks=groupCaptionsIntoBlocks([{text:'Hello.',startMs:0,endMs:100},{text:'Next',startMs:2000,endMs:2300}]);
 assert.equal(blocks.length,2);assert.equal(blocks[0].endMs,450);
 assert.equal(getActiveWordIndex(blocks[0].words,300),-1);
});
test('safe placement respects split seam, editorial content and face regions',()=>{
 assert.equal(captionY(1000,'bottom',2,.03,[[0,2]]),.5);
 assert.equal(captionY(1000,'bottom',2,.03,[],[[0,2]]),.6);
 assert.ok(captionY(1000,'bottom',2,.03,[],[],[{x:.2,y:.5,width:.6,height:.3}])<.5);
});

test('blur layouts keep captions in the lower band despite foreground/face regions',()=>{
 const faces=[{x:0,y:.67,width:1,height:.3}];
 const y=captionY(1000,'top',1,.04,[],[],faces,1500,1.1,[[0,2,.6583]]);
 assert.ok(y-.04*1.1/2>.6583);
 assert.ok(y+.04*1.1/2<.81);
 assert.equal(captionY(2500,'bottom',1,.04,[],[],[],3000,1.1,[[0,2,.6583]]),.763);
});
