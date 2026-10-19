import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
// Compatibility markup fixture uses the retained renderer React installation.
const rendererRequire=createRequire(new URL('../package.json',import.meta.url));
const React=rendererRequire('react');
const {renderToStaticMarkup}=rendererRequire('react-dom/server');
const componentPath='../test-fixtures/ClipScoreReport.jsx';
const {default:ClipScoreReport}=await import(componentPath);

test('story reports remain visible for summary clips without legacy weighted scores',()=>{
 const html=renderToStaticMarkup(React.createElement(ClipScoreReport,{clip:{story_report:{mode:'educational',rank:1,
   main_idea:'A useful demonstration.',ending_rationale:'The conclusion is retained.',scores:{value:null},
   evidence:[{start:10,end:12,channel:'transcript',quote:'<script>source text</script>'}]}}}));
 assert.match(html,/Story evidence/);assert.match(html,/educational/);assert.match(html,/Not assessed/);
 assert.match(html,/10.00/);assert.ok(!html.includes('<script>'));assert.match(html,/&lt;script&gt;/);
});
test('legacy clips and stale story evidence render without invented explanations',()=>{
 const legacy=renderToStaticMarkup(React.createElement(ClipScoreReport,{clip:{}}));
 assert.ok(!legacy.includes('Story evidence'));
 const stale=renderToStaticMarkup(React.createElement(ClipScoreReport,{clip:{story_report:{stale:true,main_idea:'Outdated'}}}));
 assert.match(stale,/predates the current timeline/);assert.ok(!stale.includes('Outdated'));
});
