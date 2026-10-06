const {test}=require('node:test');const assert=require('node:assert/strict');
const {calculate,ema}=require('../static/indicators.js');
const close=(a,b)=>assert.ok(Math.abs(a-b)<1e-9,`${a} != ${b}`);
test('flat history has zero volatility, neutral RSI and no invented warmup values',()=>{
 const c=calculate(Array(80).fill(100));assert.equal(c.sma[48],null);assert.equal(c.sma[49],100);assert.equal(c.rsi[13],null);assert.equal(c.rsi[14],50);assert.equal(c.macd[24],null);assert.equal(c.signal[32],null);assert.equal(c.signal[33],0);assert.equal(c.volatility[19],null);assert.equal(c.volatility[20],0);assert.equal(c.upper[19],100);
});
test('rising history matches analytical bands, EMA, RSI, ROC and MACD',()=>{
 const c=calculate(Array.from({length:100},(_,i)=>i+1));close(c.mid[19],10.5);close(c.upper[19],10.5+2*Math.sqrt(33.25));close(c.ema[19],10.5);close(c.ema[20],11.5);assert.equal(c.rsi[14],100);close(c.roc[19],100);close(c.macd[33],7);close(c.signal[33],7);
});
test('future observations cannot change historical indicators',()=>{
 const prices=Array.from({length:100},(_,i)=>100+i+Math.sin(i));const a=calculate(prices.slice(0,70)),b=calculate(prices);
 for(const key of Object.keys(a))assert.deepEqual(a[key],b[key].slice(0,70));
});
test('EMA restarts warmup after missing values',()=>assert.deepEqual(ema([1,2,3,null,4,5,6],3),[null,null,2,null,null,null,5]));
