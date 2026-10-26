import test from 'node:test';
import assert from 'node:assert/strict';
import {ago,recommend,summary,backtest,parseCSV,exportDrafts,demoData} from '../cloud/logic.mjs';
import worker from '../cloud/worker.mjs';

const asOf=ago(new Date().toISOString().slice(0,10),1);
const product={sku:'ABC',name:'Rice',supplier:'Supply Co',unit_cost:4,lead_days:2,safety_days:1,pack_size:6,min_order_qty:6,shelf_life_days:90};
const stock={sku:'ABC',on_hand:8,on_order:5,snapshot_date:asOf};
const sales=Array.from({length:28},(_,i)=>({sku:'ABC',day:ago(asOf,i),units:4}));

test('Cloud forecast exactly matches worked pilot example',()=>{
 const row=recommend([product],[stock],sales,asOf,7)[0];
 assert.equal(row.forecast_daily,4);
 assert.equal(row.target_stock,40);
 assert.equal(row.suggested_order,30);
 assert.equal(row.status,'ready');
 assert.equal(summary([row]).draft_value,120);
 assert.equal(backtest(sales,asOf).forecast_wape_pct,0);
});

test('Cloud forecast withholds incomplete sales and stale inventory',()=>{
 assert.equal(recommend([product],[stock],sales.slice(1),asOf)[0].status,'withheld');
 assert.equal(recommend([product],[{...stock,snapshot_date:'2024-01-01'}],sales,asOf)[0].status,'withheld');
 assert.equal(recommend([{...product,shelf_life_days:2}],[stock],sales,asOf)[0].status,'review');
});

test('CSV parser preserves quoted commas and newlines; detects malformed CSV',()=>{
 const parsed=parseCSV('sku,name\r\nA,"Milk, fresh"\r\nB,"Two\nlines"\r\n');
 assert.equal(parsed.records.length,2);
 assert.equal(parsed.records[0].name,'Milk, fresh');
 assert.equal(parsed.records[1].name,'Two\nlines');
 assert.throws(()=>parseCSV('sku,name\nA,"unclosed'),/Unclosed/);
});

test('Draft export neutralizes spreadsheet formulas',()=>{
 const row=recommend([{...product,name:'=HYPERLINK("bad")'}],[stock],sales,asOf)[0];
 assert.match(exportDrafts([row]),/'=HYPERLINK/);
});

test('Public cloud demo is read-only and usable without local PC',async()=>{
 const env={DB:{}};
 const base='https://retailpilot.example';
 let response=await worker.fetch(new Request(base+'/api/me'),env);
 assert.equal(response.status,401);
 const headers={Authorization:'Bearer demo-public'};
 response=await worker.fetch(new Request(base+'/api/me',{headers}),env);
 assert.equal((await response.json()).name,'Synthetic Demo Grocery');
 response=await worker.fetch(new Request(base+'/api/recommendations?as_of='+asOf,{headers}),env);
 const results=await response.json();
 assert.equal(results.items.length,4);
 assert.ok(results.items.some(x=>x.suggested_order>0));
 response=await worker.fetch(new Request(base+'/api/import/products',{method:'POST',headers:{...headers,'content-type':'text/csv'},body:'sku\nX'}),env);
 assert.equal(response.status,403);
 assert.equal((await response.json()).error,'Public demo is read-only');
});

test('Synthetic demo only contains generated sample products',()=>{
 assert.equal(demoData(asOf).products.length,4);
});
