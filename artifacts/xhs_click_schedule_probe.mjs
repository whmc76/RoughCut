const tabs = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const tab = tabs.find((t) => t.type === "page" && t.url.includes("creator.xiaohongshu.com/publish") && t.webSocketDebuggerUrl);
class C {
  constructor(s) { this.s=s; this.i=1; this.p=new Map(); s.addEventListener("message", e=>{const m=JSON.parse(e.data); if(!this.p.has(m.id))return; const p=this.p.get(m.id); this.p.delete(m.id); m.error?p.j(new Error(m.error.message)):p.r(m.result);}); }
  static connect(u){return new Promise((r,j)=>{const s=new WebSocket(u);s.addEventListener("open",()=>r(new C(s)),{once:true});s.addEventListener("error",()=>j(new Error("ws")),{once:true});});}
  send(method,params={}){const id=this.i++;this.s.send(JSON.stringify({id,method,params}));return new Promise((r,j)=>{const timer=setTimeout(()=>{this.p.delete(id);j(new Error("timeout"));},30000);this.p.set(id,{r:v=>{clearTimeout(timer);r(v)},j:e=>{clearTimeout(timer);j(e)}});});}
  close(){this.s.close();}
}
const c=await C.connect(tab.webSocketDebuggerUrl);
try{
 await c.send("Runtime.enable");
 const res=await c.send("Runtime.evaluate",{awaitPromise:true,returnByValue:true,expression:`(async()=>{
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const clean=v=>String(v||"").replace(/\\s+/g," ").trim();
  const vis=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.display!=="none"&&s.visibility!=="hidden"};
  const click=el=>{el.scrollIntoView({block:"center",inline:"center"}); const r=el.getBoundingClientRect(); const init={bubbles:true,cancelable:true,view:window,clientX:r.left+r.width/2,clientY:r.top+r.height/2}; for(const t of ["pointerdown","mousedown","pointerup","mouseup","click"]) el.dispatchEvent(new MouseEvent(t,init)); if(typeof el.click==="function")el.click();};
  const schedule=[...document.querySelectorAll("*")].filter(vis).map(el=>({el,text:clean(el.innerText||el.textContent),cls:String(el.className||"")})).filter(x=>x.text==="定时发布"||x.text.includes("定时发布")).sort((a,b)=>a.text.length-b.text.length)[0];
  if(schedule) click(schedule.el);
  await sleep(1500);
  const elements=[...document.querySelectorAll("input,button,[role=button],.d-select,div,span")].filter(vis).map(el=>{const r=el.getBoundingClientRect();return{tag:el.tagName,text:clean(el.innerText||el.textContent||el.value||el.getAttribute("placeholder")).slice(0,120),type:el.getAttribute("type")||"",cls:String(el.className||"").slice(0,100),rect:{x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)}}}).filter(x=>/定时|发布|时间|日期|选择|立即|保存|确认|取消|2026|21:00|标题|封面/.test(x.text+x.cls)).slice(0,140);
  return {clicked:Boolean(schedule), body:clean(document.body.innerText).slice(0,3000), elements};
 })()`});
 console.log(JSON.stringify(res.result.value,null,2));
}finally{c.close();}
