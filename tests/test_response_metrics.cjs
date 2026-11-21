const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync('agent/ui/dist/v-agent.html','utf8');
class Element{constructor(){this.children=[];this.textContent='';this.hidden=false;this.dataset={};this.attributes={};} setAttribute(k,v){this.attributes[k]=String(v);} removeAttribute(k){delete this.attributes[k];} append(...items){this.children.push(...items);} replaceChildren(...items){this.children=[...items];} querySelector(selector){return this.children.find(x=>x.className==='response-metrics')||null;} remove(){this.removed=true;}}
const context={document:{createElement:()=>new Element()},window:{VALI18n:{locale:'en-US'}},uiText:x=>x};vm.createContext(context);
vm.runInContext(html.slice(html.indexOf('function updateResponsePerformance('),html.indexOf('function messageFileList(')),context);
vm.runInContext(html.slice(html.indexOf('function responseVersion('),html.indexOf('function selectResponseVersion(')),context);
const g={};context.updateResponsePerformance(g,{predicted_per_second:53.4,prompt_per_second:1002});assert.equal(g.performance.decode,53.4);assert.equal(g.performance.prefill,1002);
context.updateResponsePerformance(g,{predicted_per_second:99,prompt_per_second:9999},true);assert.equal(g.performance.decode,53.4);assert.equal(g.performance.prefill,1002);
context.updateResponsePerformance(g,{predicted_per_second:NaN,prompt_per_second:0});assert.equal(g.performance.decode,53.4);
const version=context.responseVersion({content:'done',performance:g.performance});assert.equal(version.performance.prefill,1002);
const row=new Element();context.showResponseMetrics(row,version.performance);const view=row.querySelector('x');assert.equal(view.children.length,2);assert.equal(view.children[0].children[1].textContent,'53.4');assert.equal(view.children[1].children[1].textContent,'1,002');
const empty=new Element();context.showResponseMetrics(empty,{});assert.equal(empty.children.length,0);
// Per-round engine figures add up into the reply's detail, shown on hover/focus.
const d={};context.updateResponsePerformance(d,{prompt_n:300,cache_n:100,prompt_ms:250,predicted_n:50,predicted_ms:1000,predicted_per_second:49});
context.updateResponsePerformance(d,{prompt_n:60,cache_n:400,prompt_ms:50,predicted_n:150,predicted_per_second:50});
assert.deepEqual([d.detail.rounds,d.detail.promptNew,d.detail.cached,d.detail.promptMs,d.detail.generated,d.detail.genMs],[2,360,500,300,200,4000]);
const shown=new Element();context.showResponseMetrics(shown,{decode:50,detail:{...d.detail,firstMs:420,totalMs:5300,finish:'stop',tools:1}});
const metrics=shown.querySelector('x');assert.equal(metrics.dataset.detail,'true');assert(metrics.children.some(child=>child.className==='metrics-more'),'details button');
const box=metrics.children.find(child=>child.className==='metrics-detail');assert(box,'detail box');
const texts=box.children[0].children.map(child=>child.textContent);
assert(texts.includes('Primer token')&&texts.includes('420 ms')&&texts.includes('5.3 s')&&texts.includes('Terminó por sí mismo'),texts.join(' | '));
assert(texts.some(t=>t.startsWith('200 tokens · 4 s · 50 tok/s')),texts.join(' | '));
console.log('Response speeds render, persist per version, and ignore invalid values.');
