/* Pure trailing calculations. Null means insufficient warm-up, never zero-fill. */
(function(root) {
  const rolling = (values, n, fn) => values.map((_,i) => {
    const w = values.slice(i-n+1,i+1);
    return i<n-1 || w.some(v => !Number.isFinite(v)) ? null : fn(w);
  });
  const mean = w => w.reduce((a,b)=>a+b,0)/w.length;
  const deviation = (w, sample=false) => {const m=mean(w);return Math.sqrt(w.reduce((s,v)=>s+(v-m)**2,0)/(w.length-(sample?1:0)));};
  const sma = (v,n) => rolling(v,n,mean);
  function ema(values,n) {
    let previous=null, seed=[];
    return values.map(v=>{
      if (!Number.isFinite(v)) {previous=null;seed=[];return null;}
      if(previous===null) {seed.push(v);if(seed.length<n)return null;previous=mean(seed);}
      else previous += 2/(n+1)*(v-previous);
      return previous;
    });
  }
  function rsi(values,n=14) {
    const result=values.map(()=>null);let gain=0,loss=0;
    for(let i=1;i<values.length;i++) {
      const change=values[i]-values[i-1],g=Math.max(change,0),l=Math.max(-change,0);
      if(i<=n){gain+=g/n;loss+=l/n;}else{gain=(gain*(n-1)+g)/n;loss=(loss*(n-1)+l)/n;}
      if(i>=n)result[i]=loss===0?(gain===0?50:100):100-100/(1+gain/loss);
    }return result;
  }
  function calculate(values) {
    const mid=sma(values,20),sd=rolling(values,20,deviation),fast=ema(values,12),slow=ema(values,26);
    const macd=fast.map((v,i)=>v===null||slow[i]===null?null:v-slow[i]);
    const signal=ema(macd,9);
    const returns=values.map((v,i)=>i?Math.log(v/values[i-1]):null);
    return {mid,upper:mid.map((v,i)=>v===null?null:v+2*sd[i]),lower:mid.map((v,i)=>v===null?null:v-2*sd[i]),
      sma:sma(values,50),ema:ema(values,20),rsi:rsi(values),macd,signal,
      histogram:macd.map((v,i)=>v===null||signal[i]===null?null:v-signal[i]),
      roc:values.map((v,i)=>i<10?null:(v/values[i-10]-1)*100),
      volatility:rolling(returns,20,w=>deviation(w,true)*Math.sqrt(252)*100)};
  }
  const api={calculate,sma,ema,rsi};
  if(typeof module!=='undefined')module.exports=api;else root.TechnicalIndicators=api;
})(typeof window==='undefined'?this:window);
