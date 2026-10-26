// Pure, deterministic calculations shared by the Cloudflare Worker and tests.
export function isoDay(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) throw Error('Date must be YYYY-MM-DD');
  const d = new Date(value + 'T00:00:00Z');
  if (Number.isNaN(d.valueOf()) || d.toISOString().slice(0, 10) !== value) throw Error('Invalid date');
  return value;
}
export const ago = (dateString, days) => new Date(new Date(isoDay(dateString) + 'T00:00:00Z').getTime() - days * 86400000).toISOString().slice(0,10);
export const roundPack = (quantity, pack) => quantity > 0 ? Math.ceil(quantity / pack) * pack : 0;

export function recommend(products, inventory, sales, asOf, reviewDays=7) {
  isoDay(asOf);
  if (!Number.isInteger(reviewDays) || reviewDays < 1 || reviewDays > 30) throw Error('review_days must be between 1 and 30');
  const stock = new Map(inventory.map(v => [v.sku, v]));
  const history = new Map();
  for (const row of sales) {
    if (!history.has(row.sku)) history.set(row.sku, new Map());
    history.get(row.sku).set(row.day || row.date, Number(row.units));
  }
  const last14 = Array.from({length:14},(_,i)=>ago(asOf,i));
  const last28 = Array.from({length:28},(_,i)=>ago(asOf,i));
  return products.map(p => {
    const s=stock.get(p.sku), h=history.get(p.sku) || new Map(), flags=[];
    if (!last14.every(day=>h.has(day))) flags.push('incomplete_sales_14d');
    if (!s) flags.push('missing_inventory');
    else if (Math.abs((Date.parse(asOf)-Date.parse(s.snapshot_date))/86400000)>1) flags.push('stale_inventory');
    if (asOf > new Date().toISOString().slice(0,10)) flags.push('future_as_of');
    let forecast=null, target=null, suggested=0, cover=null;
    if (!flags.length) {
      const mean7=last14.slice(0,7).reduce((a,d)=>a+h.get(d),0)/7;
      const window=last28.every(d=>h.has(d))?last28:last14;
      const avg=window.reduce((a,d)=>a+h.get(d),0)/window.length;
      forecast=Math.round((0.6*mean7+0.4*avg)*1000)/1000;
      target=Math.ceil(forecast*(Number(p.lead_days)+Number(p.safety_days)+reviewDays));
      const deficit=Math.max(0,target-Number(s.on_hand)-Number(s.on_order));
      suggested=roundPack(Math.max(deficit,deficit?Number(p.min_order_qty):0),Number(p.pack_size));
      cover=forecast?Math.round((Number(s.on_hand)+Number(s.on_order))/forecast*10)/10:null;
      if (Number(p.shelf_life_days)>0 && Number(p.shelf_life_days)<Number(p.lead_days)+Number(p.safety_days)+reviewDays) flags.push('perishable_review');
      if (Number(s.on_hand)===0) flags.push('possible_censored_demand');
      if (window.length<28) flags.push('limited_history');
    }
    const status=forecast===null?'withheld':flags.length?'review':'ready';
    return {sku:p.sku,name:p.name,supplier:p.supplier,on_hand:s?.on_hand??null,on_order:s?.on_order??null,
      unit_cost:Number(p.unit_cost),forecast_daily:forecast,target_stock:target,days_of_cover:cover,
      suggested_order:suggested,estimated_order_value:Math.round(suggested*Number(p.unit_cost)*100)/100,status,flags};
  }).sort((a,b)=>Number(a.status==='withheld')-Number(b.status==='withheld')||b.suggested_order-a.suggested_order||a.sku.localeCompare(b.sku));
}
export function summary(items) {
  return {skus:items.length,actionable:items.filter(x=>x.status!=='withheld').length,
    withheld:items.filter(x=>x.status==='withheld').length,review_needed:items.filter(x=>x.status==='review').length,
    order_lines:items.filter(x=>x.suggested_order>0).length,
    draft_value:Math.round(items.reduce((v,x)=>v+x.estimated_order_value,0)*100)/100};
}
export function backtest(sales,asOf) {
  const groups=new Map();
  for (const s of sales) {if(!groups.has(s.sku))groups.set(s.sku,new Map());groups.get(s.sku).set(s.day||s.date,Number(s.units));}
  let evaluated=0,total=0,error=0,naiveError=0;
  const days=Array.from({length:21},(_,i)=>ago(asOf,i));
  for(const series of groups.values()){
    if(!days.every(d=>series.has(d)))continue;
    const actual=days.slice(0,7).reduce((v,d)=>v+series.get(d),0);
    const prior7=days.slice(7,14).reduce((v,d)=>v+series.get(d),0);
    const prior14=days.slice(7).reduce((v,d)=>v+series.get(d),0);
    const forecast=7*(0.6*prior7/7+0.4*prior14/14);
    total+=actual;error+=Math.abs(actual-forecast);naiveError+=Math.abs(actual-prior7);evaluated++;
  }
  return {evaluated_skus:evaluated,holdout_days:7,forecast_wape_pct:total?Math.round(error/total*10000)/100:null,
    naive_wape_pct:total?Math.round(naiveError/total*10000)/100:null,
    warning:'Requires 21 complete daily records per SKU; WAPE does not establish commercial ROI.'};
}
export function parseCSV(text) {
  const rows=[],row=[];let cell='',quoted=false,closed=false;
  text=text.replace(/^\uFEFF/,'');
  for(let i=0;i<text.length;i++){
    const c=text[i];
    if(quoted){if(c==='"' && text[i+1]==='"'){cell+='"';i++;}else if(c==='"'){quoted=false;closed=true;}else cell+=c;continue;}
    if(c==='"' && cell==='' && !closed){quoted=true;continue;}
    if(c===','){row.push(cell);cell='';closed=false;continue;}
    if(c==='\n'||c==='\r'){
      if(c==='\r' && text[i+1]==='\n')i++;
      row.push(cell); if(row.some(v=>v!==''))rows.push([...row]);row.length=0;cell='';closed=false;continue;
    }
    if(closed)throw Error('Unexpected characters after quoted CSV cell');
    cell+=c;
  }
  if(quoted)throw Error('Unclosed CSV quotation');
  row.push(cell);if(row.some(v=>v!==''))rows.push(row);
  if(rows.length<2)throw Error('CSV must contain a header and data rows');
  const header=rows.shift();if(new Set(header).size!==header.length)throw Error('Duplicate CSV columns');
  return {header,records:rows.map((r,i)=>{if(r.length!==header.length)throw Error(`CSV row ${i+2} has extra/missing columns`);return Object.fromEntries(header.map((key,j)=>[key,r[j]]));})};
}
const sheetSafe=v=>typeof v==='string' && /^[\s]*[=+@-]/.test(v)?"'"+v:v;
const cell=v=>'"'+String(sheetSafe(v)??'').replaceAll('"','""')+'"';
export function exportDrafts(items) {
  const lines=[['sku','product','supplier','suggested_units','estimated_value','review_status','flags']];
  for(const r of items){if(r.suggested_order>0&&r.status!=='withheld')lines.push([r.sku,r.name,r.supplier,r.suggested_order,r.estimated_order_value,r.status,r.flags.join('|')]);}
  return '\uFEFF'+lines.map(row=>row.map(cell).join(',')).join('\r\n')+'\r\n';
}
export function demoData(asOf) {
  const products=[
    {sku:'MILK500',name:'Milk 500 ml',supplier:'Local Dairy',unit_cost:22,lead_days:1,safety_days:1,pack_size:12,min_order_qty:12,shelf_life_days:3},
    {sku:'RICE5K',name:'Rice 5 kg',supplier:'Grain Supplier',unit_cost:240,lead_days:5,safety_days:4,pack_size:5,min_order_qty:5,shelf_life_days:365},
    {sku:'BREAD',name:'Whole Wheat Bread',supplier:'Bakery',unit_cost:28,lead_days:1,safety_days:1,pack_size:10,min_order_qty:10,shelf_life_days:4},
    {sku:'SOAP',name:'Bath Soap',supplier:'FMCG Distributor',unit_cost:31,lead_days:4,safety_days:3,pack_size:24,min_order_qty:24,shelf_life_days:730}
  ];
  const inventory=[['MILK500',15],['RICE5K',9],['BREAD',8],['SOAP',10]].map(([sku,on_hand])=>({sku,on_hand,on_order:0,snapshot_date:asOf}));
  const sales=[];for(let n=0;n<42;n++)for(const [sku,base] of [['MILK500',8],['RICE5K',2],['BREAD',5],['SOAP',3]])sales.push({sku,day:ago(asOf,n),units:base+n%3});
  return {products,inventory,sales};
}
