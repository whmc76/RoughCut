const tabs = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const tab = tabs.find((t) => t.type === "page" && t.url.includes("studio.youtube.com/video/") && t.webSocketDebuggerUrl);
class C {
  constructor(s) { this.s=s; this.i=1; this.p=new Map(); s.addEventListener("message", e=>{const m=JSON.parse(e.data); if(!this.p.has(m.id))return; const p=this.p.get(m.id); this.p.delete(m.id); m.error?p.j(new Error(m.error.message)):p.r(m.result);}); }
  static connect(u){return new Promise((r,j)=>{const s=new WebSocket(u);s.addEventListener("open",()=>r(new C(s)),{once:true});s.addEventListener("error",()=>j(new Error("ws")),{once:true});});}
  send(method,params={}){const id=this.i++;this.s.send(JSON.stringify({id,method,params}));return new Promise((r,j)=>{const timer=setTimeout(()=>{this.p.delete(id);j(new Error(method+" timeout"));},30000);this.p.set(id,{r:v=>{clearTimeout(timer);r(v)},j:e=>{clearTimeout(timer);j(e)}});});}
  close(){this.s.close();}
}
const c=await C.connect(tab.webSocketDebuggerUrl);
try {
  await c.send("Runtime.enable");
  const res=await c.send("Runtime.evaluate",{returnByValue:true,expression:`(() => {
    const clean=v=>String(v||"").replace(/\\s+/g," ").trim();
    const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=="none"&&s.visibility!=="hidden";};
    const items=[...document.querySelectorAll("button,ytcp-button,ytcp-icon-button,input,textarea,#textbox,[contenteditable=true],ytcp-video-thumbnail,ytcp-thumbnail,ytcp-dropdown-trigger,tp-yt-paper-item,ytcp-checkbox-lit")]
      .filter(visible).map((el,i)=>{const r=el.getBoundingClientRect(); return {i,tag:el.tagName,text:clean(el.innerText||el.textContent||el.value||el.getAttribute("aria-label")||el.getAttribute("placeholder")).slice(0,220),type:el.getAttribute("type")||"",accept:el.getAttribute("accept")||"",disabled:el.disabled||el.hasAttribute("disabled")||/disabled/.test(String(el.className||"")),className:String(el.className||"").slice(0,160),rect:{x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)}}})
      .filter(x=>/缩略图|上传文件|播放列表|选择|保存|公开|已排定时间|已预定|视频链接|标题|说明|thumbnail|playlist|upload|save/i.test(x.text+x.className+x.accept+x.type));
    const imgs=[...document.querySelectorAll("img")].filter(visible).map(img=>{const r=img.getBoundingClientRect();return{src:img.currentSrc||img.src,alt:img.alt||"",rect:{x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)}}}).slice(0,80);
    return {url:location.href,title:document.title,body:clean(document.body.innerText).slice(0,4000),items,imgs};
  })()`});
  console.log(JSON.stringify(res.result.value,null,2));
} finally { c.close(); }
