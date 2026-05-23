const tabs = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const tab = tabs.find((t) => t.type === "page" && t.url.includes("studio.youtube.com"));
class C {
  constructor(s) { this.s=s; this.i=1; this.p=new Map(); s.addEventListener("message", e=>{const m=JSON.parse(e.data); if(!this.p.has(m.id))return; const p=this.p.get(m.id); this.p.delete(m.id); m.error?p.j(new Error(m.error.message)):p.r(m.result);}); }
  static connect(u){return new Promise((r,j)=>{const s=new WebSocket(u);s.addEventListener("open",()=>r(new C(s)),{once:true});s.addEventListener("error",()=>j(new Error("ws")),{once:true});});}
  send(method,params={}){const id=this.i++; this.s.send(JSON.stringify({id,method,params})); return new Promise((r,j)=>{this.p.set(id,{r,j}); setTimeout(()=>{if(this.p.has(id)){this.p.delete(id);j(new Error("timeout"));}},30000);});}
  close(){this.s.close();}
}
const c=await C.connect(tab.webSocketDebuggerUrl);
try {
  await c.send("Runtime.enable");
  const res=await c.send("Runtime.evaluate",{returnByValue:true,expression:`(() => {
    const clean=v=>String(v||"").replace(/\\s+/g," ").trim();
    const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=="none"&&s.visibility!=="hidden";};
    const nodes=[...document.querySelectorAll("tp-yt-paper-radio-button, ytcp-ve, ytcp-checkbox-lit, input, button, ytcp-button")].filter(visible);
    return nodes.map(el=>({tag:el.tagName,text:clean(el.innerText||el.textContent||el.value).slice(0,160),checked:el.checked||el.getAttribute("aria-checked")||el.hasAttribute("checked")||/checked/.test(String(el.className||"")),disabled:el.disabled||el.hasAttribute("disabled")||/disabled/.test(String(el.className||"")),className:String(el.className||"").slice(0,120)})).filter(x=>/公开|私享|安排|不公开|儿童|预定|20:00|00:00|时间|保存|发布/.test(x.text+x.className)).slice(0,120);
  })()`});
  console.log(JSON.stringify(res.result.value,null,2));
} finally { c.close(); }
