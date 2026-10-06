const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
function setup() {
  class Node {
    constructor(){this.children=[];this.style={setProperty(){}};this.value='';}
    append(...nodes){this.children.push(...nodes)}
    prepend(node){this.children.unshift(node)}
    replaceChildren(...nodes){this.children=nodes}
    setAttribute(){}
    addEventListener(){}
  }
  const elements = new Map();
  const context = vm.createContext({console, document:{getElementById(id){if(!elements.has(id))elements.set(id,new Node());return elements.get(id)},createElement(){return new Node()}},window:{location:{origin:''},addEventListener(){}},localStorage:{getItem(){return null},setItem(){}},setInterval(){},setTimeout(){}});
  vm.runInContext(fs.readFileSync('static/app.js','utf8').replace('\nloadTickers();',''),context);
  return {context,elements};
}
test('summary uses latest observation and median endpoints with mixed horizons disclosed',()=>{
 const {context,elements}=setup();
 vm.runInContext(`renderInsights('TEST',{runs:[{run_label:'A',values:[90,120],horizons:['1d','7d']},{run_label:'B',values:[140],horizons:['30d']}]},{dates:['2026-10-02'],closes:[100]},{dates:['2026-10-01'],prices:[80]})`,context);
 const cards=elements.get('metrics').children;
 assert.equal(cards[0].children[1].textContent,'100.00');
 assert.equal(cards[1].children[1].textContent,'130.00');
 assert.equal(cards[2].children[1].textContent,'+30.0%');
 assert.match(elements.get('insight').textContent,/different horizons/);
 assert.equal(elements.get('model-rows').children.length,2);
});
test('missing data is not presented as zero or an actionable forecast',()=>{
 const {context,elements}=setup();
 vm.runInContext(`renderInsights('EMPTY',{runs:[]},null,null)`,context);
 assert.equal(elements.get('metrics').children[0].children[1].textContent,'—');
 assert.equal(elements.get('metrics').children[2].children[1].textContent,'—');
 assert.equal(elements.get('model-rows').children.length,0);
});
