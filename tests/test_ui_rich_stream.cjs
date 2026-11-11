const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync('agent/ui/dist/v-agent.html','utf8');
class Element{
 constructor(){this.childNodes=[];this.classList={add(){}};this.className='';this.writes=0;this._html='';}
 set innerHTML(value){this._html=value;this.writes++;} get innerHTML(){return this._html;}
 insertBefore(node,before){if(node.parent)node.remove();const at=before?this.childNodes.indexOf(before):this.childNodes.length;this.childNodes.splice(at,0,node);node.parent=this;}
 get lastChild(){return this.childNodes.at(-1);}
 remove(){if(this.parent){this.parent.childNodes.splice(this.parent.childNodes.indexOf(this),1);this.parent=null;}}
}
const scope={document:{createElement:()=>new Element()},console};
vm.createContext(scope);vm.runInContext(html.slice(html.indexOf('function escHTML('),html.indexOf("let viewerCode=")),scope);
const root=new Element(),prefix='# Live heading\n\nA **formatted** paragraph.\n\n';
const table='| Name | Value |\n| --- | --- |\n| First | 1 |';
scope.renderRich(root,prefix+table,{streaming:true});
const prose=root.childNodes[0],stable=prose.childNodes[0],paragraph=prose.childNodes[1],tail=prose.childNodes[2];
assert.match(stable.innerHTML,/<h2>Live heading<\/h2>/);
assert.match(paragraph.innerHTML,/<strong>formatted<\/strong>/);
assert.match(tail.innerHTML,/<table>/,'Render table before generation finishes');
assert.match(tail.innerHTML,/<td>First<\/td>/);
const writes=stable.writes;
scope.renderRich(root,prefix+table+'\n| Second | 2 |',{streaming:true});
assert.strictEqual(prose.childNodes[0],stable);assert.equal(stable.writes,writes,'Completed blocks must not repaint');
assert.match(tail.innerHTML,/<td>Second<\/td>/);
scope.renderRich(root,prefix+table+'\n| Second | 2 |',{streaming:false});
assert.strictEqual(prose.childNodes[0],stable);assert.equal(stable.writes,writes,'Finalizing keeps existing rendered blocks');
const safe=scope.mdHTML('<img src=x onerror=alert(1)>\n[bad](javascript:alert(1))');assert(!safe.includes('<img'));assert(!safe.includes('href="javascript:'));
console.log('Live Markdown tables/headings, stable completed blocks, safe HTML and finalization passed.');
