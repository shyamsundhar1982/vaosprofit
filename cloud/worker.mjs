import {isoDay,ago,recommend,summary,backtest,parseCSV,exportDrafts,demoData} from './logic.mjs';

// The build step replaces this token with the dashboard HTML as a JSON string.
const DASHBOARD_HTML = '__DASHBOARD_HTML__';
const DEMO = 'public-synthetic-demo';
const SCHEMAS = {
 products:['sku','name','supplier','unit_cost','unit_price','lead_days','safety_days','pack_size','min_order_qty','shelf_life_days'],
 inventory:['store_id','sku','on_hand','on_order','snapshot_date'],
 sales:['store_id','sku','date','units']
};
const json=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{'content-type':'application/json; charset=utf-8','cache-control':'no-store','x-content-type-options':'nosniff'}});
function fail(error,status=400){return json({error},status);}
function intValue(x,name,min=0){if(!/^\d+$/.test(String(x))||!Number.isSafeInteger(Number(x))||Number(x)<min)throw Error(name+' must be an integer >= '+min);return Number(x);}
function amount(x,name){if(x===''||!Number.isFinite(Number(x))||Number(x)<0)throw Error(name+' must be a nonnegative number');return Number(x);}
async function sha256(text){const b=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text));return [...new Uint8Array(b)].map(v=>v.toString(16).padStart(2,'0')).join('');}
async function auth(request,db){
 const a=request.headers.get('Authorization')||'';
 if(a==='Bearer demo-public')return DEMO;
 if(!a.startsWith('Bearer ')||a.length>300)return null;
 const digest=await sha256(a.slice(7));
 const row=await db.prepare('SELECT tenant_id FROM tokens WHERE token_hash=?').bind(digest).first();
 return row?.tenant_id||null;
}
async function getItems(env,tenant,store,asOf,review){
 if(tenant===DEMO)return recommend(...Object.values(demoData(asOf)),asOf,review);
 const owns=await env.DB.prepare('SELECT 1 FROM stores WHERE tenant_id=? AND id=?').bind(tenant,store).first();
 if(!owns)throw Error('Unknown store for this tenant');
 const [products,inventory,sales]=await Promise.all([
  env.DB.prepare('SELECT * FROM products WHERE tenant_id=? ORDER BY sku').bind(tenant).all(),
  env.DB.prepare('SELECT * FROM inventory WHERE tenant_id=? AND store_id=?').bind(tenant,store).all(),
  env.DB.prepare('SELECT sku,day,units FROM sales WHERE tenant_id=? AND store_id=? AND day BETWEEN ? AND ?').bind(tenant,store,ago(asOf,27),asOf).all()
 ]);
 return recommend(products.results,inventory.results,sales.results,asOf,review);
}
async function getBacktest(env,tenant,store,asOf){
 if(tenant===DEMO)return backtest(demoData(asOf).sales,asOf);
 const owns=await env.DB.prepare('SELECT 1 FROM stores WHERE tenant_id=? AND id=?').bind(tenant,store).first();
 if(!owns)throw Error('Unknown store for this tenant');
 const rows=await env.DB.prepare('SELECT sku,day,units FROM sales WHERE tenant_id=? AND store_id=? AND day BETWEEN ? AND ?').bind(tenant,store,ago(asOf,20),asOf).all();
 return backtest(rows.results,asOf);
}
async function importRows(env,tenant,kind,request){
 if(tenant===DEMO)return fail('Public demo is read-only',403);
 if(!Object.hasOwn(SCHEMAS,kind))return fail('Unknown import type');
 if(request.headers.get('content-type')?.split(';')[0].trim()!=='text/csv')return fail('Use Content-Type: text/csv',415);
 if(Number(request.headers.get('content-length')||0)>300000)return fail('CSV chunk exceeds 300 KB',413);
 const body=await request.text();if(body.length>300000)return fail('CSV chunk exceeds 300 KB',413);
 const {header,records}=parseCSV(body);
 if(records.length>500)return fail('Upload in chunks of at most 500 rows',413);
 const missing=SCHEMAS[kind].filter(k=>!header.includes(k));if(missing.length)throw Error('Missing columns: '+missing.join(', '));
 const statements=[];
 for(let i=0;i<records.length;i++){
  const r=records[i];
  try{
   if(kind==='products'){
    const sku=r.sku.trim(),name=r.name.trim(),supplier=r.supplier.trim();
    if(!sku||!name||!supplier)throw Error('SKU, name and supplier are required');
    const values=[amount(r.unit_cost,'unit_cost'),amount(r.unit_price,'unit_price'),intValue(r.lead_days,'lead_days'),intValue(r.safety_days,'safety_days'),intValue(r.pack_size,'pack_size',1),intValue(r.min_order_qty,'min_order_qty'),intValue(r.shelf_life_days,'shelf_life_days')];
    statements.push(env.DB.prepare(`INSERT INTO products VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(tenant_id,sku) DO UPDATE SET name=excluded.name,supplier=excluded.supplier,unit_cost=excluded.unit_cost,unit_price=excluded.unit_price,lead_days=excluded.lead_days,safety_days=excluded.safety_days,pack_size=excluded.pack_size,min_order_qty=excluded.min_order_qty,shelf_life_days=excluded.shelf_life_days`).bind(tenant,sku,name,supplier,...values));
   }else if(kind==='inventory'){
    statements.push(env.DB.prepare(`INSERT INTO inventory VALUES(?,?,?,?,?,?) ON CONFLICT(tenant_id,store_id,sku) DO UPDATE SET on_hand=excluded.on_hand,on_order=excluded.on_order,snapshot_date=excluded.snapshot_date`).bind(tenant,r.store_id.trim(),r.sku.trim(),intValue(r.on_hand,'on_hand'),intValue(r.on_order,'on_order'),isoDay(r.snapshot_date)));
   }else{
    statements.push(env.DB.prepare(`INSERT INTO sales VALUES(?,?,?,?,?) ON CONFLICT(tenant_id,store_id,sku,day) DO UPDATE SET units=excluded.units`).bind(tenant,r.store_id.trim(),r.sku.trim(),isoDay(r.date),intValue(r.units,'units')));
   }
  }catch(error){throw Error(`CSV row ${i+2}: ${error.message}`);}
 }
 try{await env.DB.batch(statements);}catch{return fail('Database rejected this batch. Verify SKU/store ownership and referential integrity. No rows were imported.',400);}
 return json({kind,imported:records.length,tenant});
}
export default {
 async fetch(request,env){
  const u=new URL(request.url),path=u.pathname;
  if(path==='/'&&request.method==='GET')return new Response(DASHBOARD_HTML,{headers:{'content-type':'text/html; charset=utf-8','cache-control':'no-store','x-content-type-options':'nosniff','referrer-policy':'no-referrer','content-security-policy':"default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"}});
  if(path==='/api/health'&&request.method==='GET')return json({ok:true,status:'cloud-pilot',purchase_execution:false});
  if(!path.startsWith('/api/'))return fail('Not found',404);
  if(!env.DB)return fail('Pilot database is not configured',503);
  try{
   const tenant=await auth(request,env.DB);if(!tenant)return fail('A valid tenant API token is required',401);
   if(path==='/api/me'&&request.method==='GET'){
    if(tenant===DEMO)return json({tenant:'demo',name:'Synthetic Demo Grocery',stores:[{id:'main',name:'Demo Store'}]});
    const [t,s]=await Promise.all([env.DB.prepare('SELECT name FROM tenants WHERE id=?').bind(tenant).first(),env.DB.prepare('SELECT id,name FROM stores WHERE tenant_id=? ORDER BY id').bind(tenant).all()]);
    return json({tenant,name:t?.name,stores:s.results});
   }
   if(path.startsWith('/api/import/')&&request.method==='POST')return importRows(env,tenant,path.split('/').pop(),request);
   if(request.method!=='GET')return fail('Method not allowed',405);
   const store=u.searchParams.get('store')||'main',asOf=isoDay(u.searchParams.get('as_of')||ago(new Date().toISOString().slice(0,10),1));
   const review=intValue(u.searchParams.get('review_days')||'7','review_days',1);
   if(review>30)throw Error('review_days must be <=30');
   if(path==='/api/backtest')return json(await getBacktest(env,tenant,store,asOf));
   if(['/api/recommendations','/api/summary','/api/drafts.csv'].includes(path)){
    const items=await getItems(env,tenant,store,asOf,review);
    if(path==='/api/recommendations')return json({store,as_of:asOf,review_days:review,items});
    if(path==='/api/summary')return json({store,as_of:asOf,...summary(items)});
    return new Response(exportDrafts(items),{headers:{'content-type':'text/csv; charset=utf-8','cache-control':'no-store','content-disposition':'attachment; filename="purchase-order-DRAFT.csv"'}});
   }
   return fail('Not found',404);
  }catch(error){return fail(error.message||'Invalid request',400);}
 }
};
