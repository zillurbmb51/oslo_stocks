const {test}=require('node:test');const assert=require('node:assert/strict');
const {summarize}=require('../static/decision-insights.js');const {calculate}=require('../static/indicators.js');
function fixture(prices){const dates=prices.map((_,i)=>new Date(Date.UTC(2025,0,i+1)).toISOString().slice(0,10));return {dates,prices,origins:[],cutoff:dates.at(-1)};}
const status=d=>({available:true,stale:false,expected_session:d.cutoff});
test('positive alignment is descriptive and extreme RSI does not imply sell',()=>{
 const d=fixture(Array.from({length:100},(_,i)=>100+i)),c=calculate(d.prices);c.histogram[c.histogram.length-1]=1;
 const result=summarize(d,c,status(d));assert.match(result.title,/Upward trend/);assert.match(result.cards[2].title,/above 70/);assert.match(result.cards[2].meaning,/persist/);assert.equal(result.cards.length,6);
});
test('stale ticker and failed freshness checks override directional headline',()=>{
 const d=fixture(Array.from({length:100},(_,i)=>100+i)),c=calculate(d.prices);
 assert.equal(summarize(d,c,{available:true,stale:false,expected_session:'2026-10-06'}).title,'Check data freshness first');
 assert.equal(summarize(d,c,null).title,'Check data freshness first');
});
test('excluded and short histories never produce confident analysis',()=>{
 assert.equal(summarize(fixture([]),calculate([]),null).cards.length,0);
 const d=fixture([100,101]);const r=summarize(d,calculate(d.prices),status(d));assert.equal(r.title,'Build more evidence');assert.match(r.cards[5].title,/Too few/);assert.match(r.cards[3].title,/Limited/);
});
test('forecast evidence uses matched resolved targets and a baseline, never pending outcomes',()=>{
 const d=fixture(Array(100).fill(100));
 d.origins=Array.from({length:20},(_,i)=>({date:d.dates[i],price:100,points:[[20,d.dates[i+20],110]]}));
 d.origins.push({date:d.dates[99],price:100,points:[[20,'2030-01-01',10000]]});
 const r=summarize(d,calculate(d.prices),status(d));assert.match(r.cards[5].title,/No advantage/);assert.match(r.cards[5].evidence,/20 resolved origins/);assert.match(r.cards[5].evidence,/adaptive 10.00%, no-change 0.00%/);
 d.origins=d.origins.slice(0,19);assert.match(summarize(d,calculate(d.prices),status(d)).cards[5].title,/Too few/);
});
test('flat volatility history ranks at midpoint rather than artificially elevated',()=>{
 const d=fixture(Array(120).fill(100));const r=summarize(d,calculate(d.prices),status(d));assert.equal(r.cards[3].title,'Volatility near its usual range');assert.match(r.cards[3].evidence,/50th percentile/);
});
