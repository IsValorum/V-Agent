const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync('agent/ui/dist/v-agent.html','utf8');
class Element{constructor(){this.children=[];this.textContent='';this.hidden=false;} append(...items){this.children.push(...items);} replaceChildren(...items){this.children=[...items];} querySelector(selector){return this.children.find(x=>x.className==='response-metrics')||null;} remove(){this.removed=true;}}
const context={document:{createElement:()=>new Element()},window:{VALI18n:{locale:'en-US'}},uiText:x=>x};vm.createContext(context);
vm.runInContext(html.slice(html.indexOf('function updateResponsePerformance('),html.indexOf('function messageFileList(')),context);
vm.runInContext(html.slice(html.indexOf('function responseVersion('),html.indexOf('function selectResponseVersion(')),context);
const g={};context.updateResponsePerformance(g,{predicted_per_second:53.4,prompt_per_second:1002});assert.equal(g.performance.decode,53.4);assert.equal(g.performance.prefill,1002);
context.updateResponsePerformance(g,{predicted_per_second:99,prompt_per_second:9999},true);assert.equal(g.performance.decode,53.4);assert.equal(g.performance.prefill,1002);
context.updateResponsePerformance(g,{predicted_per_second:NaN,prompt_per_second:0});assert.equal(g.performance.decode,53.4);
const version=context.responseVersion({content:'done',performance:g.performance});assert.equal(version.performance.prefill,1002);
const row=new Element();context.showResponseMetrics(row,version.performance);const view=row.querySelector('x');assert.equal(view.children.length,2);assert.equal(view.children[0].children[1].textContent,'53.4');assert.equal(view.children[1].children[1].textContent,'1,002');
const empty=new Element();context.showResponseMetrics(empty,{});assert.equal(empty.children.length,0);
console.log('Response speeds render, persist per version, and ignore invalid values.');
