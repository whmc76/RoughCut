const CDP='http://127.0.0.1:9222';
const platform=process.argv[2];
const domains={bilibili:['member.bilibili.com'],xiaohongshu:['creator.xiaohongshu.com'],wechat:['channels.weixin.qq.com'],toutiao:['mp.toutiao.com'],kuaishou:['cp.kuaishou.com'],youtube:['studio.youtube.com']}[platform];
const tabs=await (await fetch(CDP+'/json/list')).json();
const tab=tabs.find(t=>t.type==='page'&&domains.some(d=>String(t.url).includes(d)));
class C{constructor(s){this.s=s;this.id=1;this.p=new Map();s.addEventListener('message',e=>{const m=JSON.parse(e.data);const p=this.p.get(m.id);if(!p)return;this.p.delete(m.id);m.error?p.reject(new Error(m.error.message)):p.resolve(m.result)})} static connect(u){return new Promise((res,rej)=>{const s=new WebSocket(u);s.addEventListener('open',()=>res(new C(s)),{once:true});s.addEventListener('error',()=>rej(new Error('ws')),{once:true})})} send(method,params={}){const id=this.id++;return new Promise((resolve,reject)=>{this.p.set(id,{resolve,reject});this.s.send(JSON.stringify({id,method,params}))})}}
const c=await C.connect(tab.webSocketDebuggerUrl); await c.send('Runtime.enable');
const expr=`(() => { const clean=v=>String(v||'').replace(/\\s+/g,' ').trim(); const vis=el=>{const r=el.getBoundingClientRect(); const s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'}; return [...document.querySelectorAll('*')].filter(vis).map((el,i)=>{const r=el.getBoundingClientRect(); return {i,tag:el.tagName.toLowerCase(), cls:el.className&&String(el.className).slice(0,120), role:el.getAttribute('role')||'', text:clean(el.innerText||el.value||el.getAttribute('aria-label')||el.getAttribute('placeholder')||el.getAttribute('title')), x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width), h:Math.round(r.height)} }).filter(x=>x.text && x.text.length<120 && /分区|生活兴趣|户外|合集|原创|声明|群聊|分类|选择/.test(x.text)).slice(0,300); })()`;
const r=await c.send('Runtime.evaluate',{expression:expr,returnByValue:true,awaitPromise:true});
console.log(JSON.stringify({url:tab.url,title:tab.title,items:r.result.value},null,2));
c.s.close();
