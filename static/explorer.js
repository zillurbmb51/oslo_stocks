(function() {
  const el=id=>document.getElementById(id), fmt=v=>Number.isFinite(v)?v.toFixed(2):'—';
  let state=null, indicators=null;
  const config={responsive:true,displaylogo:false,scrollZoom:false,toImageButtonOptions:{format:'png',scale:2}};
  const axis={gridcolor:'#29344c',zeroline:false,automargin:true};
  const base=()=>({paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'#0b1526',font:{color:'#dce5f5'},hovermode:'x unified',dragmode:'zoom',margin:{l:65,r:25,t:35,b:65},legend:{orientation:'h',y:1.15},autosize:true});
  const trace=(name,x,y,color,more={})=>({name,x,y,type:'scatter',mode:'lines',connectgaps:false,line:{color,width:2},...more});
  const range=(dates,count)=>count==='all'?undefined:[dates[Math.max(0,dates.length-Number(count))],dates.at(-1)];
  const padded = values => {const v=values.filter(Number.isFinite);if(!v.length)return undefined;const lo=Math.min(...v),hi=Math.max(...v),pad=(hi-lo)*.08||Math.abs(hi)*.02||1;return [lo-pad,hi+pad];};
  function empty(id,text){return Plotly.react(el(id),[],{...base(),xaxis:{visible:false},yaxis:{visible:false},annotations:[{text,x:.5,y:.5,xref:'paper',yref:'paper',showarrow:false}]},config);}
  async function renderPrice() {
    if(!state)return;
    const {data,forecast,ticker}=state, archived=el('chart-view').value==='legacy';
    el('forecast-controls').hidden=archived;el('outcomes-table').hidden=archived;el('forecast-insight').textContent='';el('outcome-rows').replaceChildren();
    if(archived){
      el('chart-heading').textContent=`${ticker} · Undated archived projections`;
      el('chart-note').textContent='Original relative horizons only: forecast cutoffs and price bases are unverified, so these legacy models cannot be aligned to actual dates.';
      return Plotly.react(el('chart'),(forecast.runs||[]).map((r,i)=>trace(r.run_label||`Run ${i+1}`,r.horizons,r.values,['#b8a4ff','#f7ca7e','#7fdac8','#64baff'][i%4],{mode:'lines+markers'})),{...base(),xaxis:{...axis,type:'category',title:'Original horizon'},yaxis:{...axis,title:'Archived projected price'}},config);
    }
    el('chart-heading').textContent=`${ticker} · History, predictions & actuals`;
    el('chart-note').textContent='Retrospective walk-forward simulations, not forecasts recorded live on these dates. All lines use the same provider dividend- and split-adjusted NOK basis. Dashed segments connect only the six forecast horizons; intermediate values are not forecasts. Last 126 eligible origins available.';
    if(!data.dates.length||!data.prices.length)return empty('chart','No validated adjusted-price series for this ticker');
    const origin=data.origins.find(o=>o.date===el('forecast-origin').value);
    if(!origin){el('forecast-insight').textContent='Dated predictions are not available in this snapshot yet.';return Plotly.react(el('chart'),[trace('Actual adjusted close',data.dates,data.prices,'#7fdac8')],{...base(),xaxis:{...axis,type:'date'},yaxis:{...axis,title:'Adjusted NOK'}},config);}
    const before=data.dates.map(d=>d<=origin.date), after=data.dates.map(d=>d>=origin.date);
    const x=[origin.date,...origin.points.map(p=>p[1])], y=[origin.price,...origin.points.map(p=>p[2])];
    const lookup=new Map(data.dates.map((d,i)=>[d,data.prices[i]]));let completed=0,total=0;
    for(const [h,date,prediction] of origin.points){
      const actual=lookup.get(date),error=actual===undefined?null:(prediction/actual-1)*100;
      if(error!==null){completed++;total+=Math.abs(error);}
      const row=document.createElement('tr');
      [h,date,fmt(prediction),actual===undefined?(date>data.cutoff?'Pending':'Missing session'):fmt(actual),error===null?'—':`${error>=0?'+':''}${error.toFixed(2)}%`].forEach(v=>{const td=document.createElement('td');td.textContent=v;row.append(td);});el('outcome-rows').append(row);
    }
    el('forecast-insight').textContent=`Origin ${origin.date} · ${completed}/${origin.points.length} target outcomes available${completed?` · Mean absolute percentage error ${fmt(total/completed)}% across these targets`:''}. Purple = simulated adaptive forecast; teal = subsequent actual prices; amber = no-change baseline. Latest actual: ${data.dates.at(-1)}.`;
    const idx=data.dates.indexOf(origin.date),n=el('history-window').value;
    const start=n==='all'?data.dates[0]:data.dates[Math.max(0,idx-Number(n))];
    await Plotly.react(el('chart'),[
      trace('History at origin',data.dates,data.prices.map((v,i)=>before[i]?v:null),'#94a3b8'),
      trace('Actual after origin',data.dates,data.prices.map((v,i)=>after[i]?v:null),'#7fdac8'),
      trace('Adaptive forecast · simulated',x,y,'#b8a4ff',{mode:'lines+markers',line:{color:'#b8a4ff',dash:'dash',width:3},marker:{size:7}}),
      trace('No-change baseline',x,x.map(()=>origin.price),'#f7ca7e',{line:{color:'#f7ca7e',dash:'dot',width:1.5}})
    ],{...base(),uirevision:`${ticker}-${origin.date}-${n}`,xaxis:{...axis,type:'date',range:[start,[data.dates.at(-1),x.at(-1)].sort().at(-1)],rangeslider:{visible:true,thickness:.09}},yaxis:{...axis,title:'Adjusted NOK',range:padded([...data.prices.filter((v,i)=>data.dates[i]>=start),...y])},shapes:[{type:'line',xref:'x',yref:'paper',x0:origin.date,x1:origin.date,y0:0,y1:1,line:{color:'#b8a4ff',dash:'dot'}}]},config);
  }
  async function renderIndicators(){
    if(!state)return;const {data,ticker}=state;
    el('indicator-readings').replaceChildren();
    if(!data.prices.length)return empty('indicator-chart','Indicators unavailable: no validated adjusted closes');
    const d=data.dates,v=data.prices,c=indicators,mode=el('momentum-indicator').value;
    const traces=[trace('Adjusted close',d,v,'#e5e7eb')];
    if(el('show-bb').checked)traces.push(trace('BB lower',d,c.lower,'#648ee7',{legendgroup:'bb',showlegend:false}),trace('BB ±2σ',d,c.upper,'#648ee7',{legendgroup:'bb',fill:'tonexty',fillcolor:'rgba(100,142,231,.14)'}),trace('BB mean 20',d,c.mid,'#648ee7',{legendgroup:'bb',line:{color:'#648ee7',dash:'dot'}}));
    if(el('show-sma').checked)traces.push(trace('SMA 50',d,c.sma,'#f7ca7e'));
    if(el('show-ema').checked)traces.push(trace('EMA 20',d,c.ema,'#b8a4ff'));
    const momentum=(name,y,color,more={})=>trace(name,d,y,color,{xaxis:'x2',yaxis:'y2',...more});
    if(mode==='macd')traces.push(momentum('MACD',c.macd,'#7fdac8'),momentum('Signal',c.signal,'#f7ca7e'),momentum('Histogram',c.histogram,'#64baff',{type:'bar',marker:{color:c.histogram.map(v=>v>=0?'#7fdac8':'#ff95a3')}}));
    else traces.push(momentum(mode==='rsi'?'RSI 14':'ROC 10 (%)',c[mode],'#7fdac8'));
    traces.push(trace('Volatility 20 · annualized %',d,c.volatility,'#ff95a3',{xaxis:'x3',yaxis:'y3',fill:'tozeroy',fillcolor:'rgba(255,149,163,.08)'}));
    const r=range(d,el('indicator-window').value),shapes=mode==='rsi'?[30,70].map(y=>({type:'line',xref:'paper',yref:'y2',x0:0,x1:1,y0:y,y1:y,line:{color:'#687992',dash:'dot'}})):[];
    await Plotly.react(el('indicator-chart'),traces,{...base(),height:700,uirevision:`${ticker}-${mode}-${el('indicator-window').value}`,legend:{orientation:'h',y:1.12},xaxis:{...axis,type:'date',range:r,anchor:'y',showticklabels:false},xaxis2:{...axis,type:'date',matches:'x',anchor:'y2',showticklabels:false},xaxis3:{...axis,type:'date',matches:'x',anchor:'y3',title:'Session date'},yaxis:{...axis,domain:[.55,1],title:'Adjusted NOK',range:padded([v,c.lower,c.upper,c.sma,c.ema].flatMap(values=>values.filter((v,i)=>!r||d[i]>=r[0])))},yaxis2:{...axis,domain:[.28,.47],title:mode.toUpperCase(),...(mode==='rsi'?{range:[0,100]}:{})},yaxis3:{...axis,domain:[0,.20],title:'Volatility %',rangemode:'tozero'},shapes},config);
    const last=v.at(-1),rsi=c.rsi.at(-1),macd=c.histogram.at(-1),roc=c.roc.at(-1),vol=c.volatility.at(-1),sma=c.sma.at(-1),ema=c.ema.at(-1),upper=c.upper.at(-1),lower=c.lower.at(-1);
    const readings=[['Bollinger Bands',upper===null?'Warming up':last>upper?'Above upper band':last<lower?'Below lower band':'Inside bands'],['SMA 50',sma===null?'Warming up':`${fmt((last/sma-1)*100)}% from average`],['EMA 20',ema===null?'Warming up':`${fmt((last/ema-1)*100)}% from average`],['RSI 14',`${fmt(rsi)} · ${rsi===null?'warming up':rsi>70?'above 70':rsi<30?'below 30':'30–70 range'}`],['MACD histogram',fmt(macd)],['ROC 10',`${fmt(roc)}%`],['Volatility 20',`${fmt(vol)}% annualized`]];
    for(const [label,value] of readings){const card=document.createElement('div');const small=document.createElement('small'),strong=document.createElement('strong');small.textContent=label;strong.textContent=value;card.append(small,strong);el('indicator-readings').append(card);}
  }
  function renderDecision(status) {
    const summary=DecisionInsights.summarize(state.data,indicators,status);
    el('decision-title').textContent=summary.title;
    el('decision-panel').dataset.tone=summary.tone;
    el('decision-date').textContent=`${state.ticker} · ${summary.date}`;
    el('decision-next').textContent=summary.next;
    const grid=el('decision-cards');grid.replaceChildren();
    for(const card of summary.cards){
      const article=document.createElement('article');article.className='decision-card';article.dataset.tone=card.tone;
      for(const [tag,key] of [['small','label'],['h3','title'],['p','evidence'],['p','meaning']]){
        const node=document.createElement(tag);node.textContent=card[key];node.className=key;article.append(node);
      }grid.append(article);
    }
  }
  window.MarketExplorer={async load(ticker,forecast,isCurrent){
    const [response,status]=await Promise.all([
      fetch(`${window.APP_API_BASE||window.location.origin}/api/explorer/${encodeURIComponent(ticker)}`),
      fetch(`${window.APP_API_BASE||window.location.origin}/api/market-status?ticker=${encodeURIComponent(ticker)}`).then(r=>r.ok?r.json():null).catch(()=>null)
    ]);
    if(!response.ok)throw new Error('Explorer data unavailable');const data=await response.json();if(!isCurrent())return;
    const old=state?.ticker===ticker?el('forecast-origin').value:null;
    state={ticker,forecast,data};indicators=TechnicalIndicators.calculate(data.prices);renderDecision(status);
    const select=el('forecast-origin');select.replaceChildren();
    for(const o of [...data.origins].reverse()){const option=document.createElement('option');option.value=o.date;option.textContent=o.date;select.append(option);}
    // Start with a past origin so subsequent outcomes are visible on first load.
    if(data.origins.some(o=>o.date===old))select.value=old;
    else if(data.origins.length)select.value=data.origins[Math.max(0,data.origins.length-61)].date;
    select.disabled=!data.origins.length;
    await renderPrice();if(isCurrent())await renderIndicators();
  }};
  for(const id of ['chart-view','forecast-origin','history-window'])el(id).addEventListener('change',renderPrice);
  for(const id of ['indicator-window','momentum-indicator','show-bb','show-sma','show-ema'])el(id).addEventListener('change',renderIndicators);
  window.addEventListener('resize',()=>{if(el('indicator-chart').data)Plotly.Plots.resize(el('indicator-chart'));});
})();
