const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); }
const initData = tg?.initData || "";
let state = { balance: 0, ads_today: 0, user: null, withdrawals: [] };
const $ = id => document.getElementById(id);
function toast(msg){const el=$("toast");el.textContent=msg;el.classList.add("show");setTimeout(()=>el.classList.remove("show"),3000)}
async function api(path, options={}) {
  const headers = {"Content-Type":"application/json","X-Telegram-Init-Data":initData,...(options.headers||{})};
  const res = await fetch(path,{...options,headers});
  const data = await res.json().catch(()=>({error:"Server returned an invalid response"}));
  if(!res.ok) throw new Error(data.error || "Request failed");
  return data;
}
function renderHistory(target){
  const el=$(target);
  if(!state.withdrawals.length){el.className="history empty";el.textContent="No withdrawal requests yet.";return}
  el.className="history";el.innerHTML="";
  state.withdrawals.forEach(w=>{
    const item=document.createElement("div");item.className="history-item";
    const left=document.createElement("div"), title=document.createElement("b"), meta=document.createElement("span");
    title.textContent=`Withdrawal #${w.id} · ₹${w.amount_rupees}`;
    meta.textContent=`${w.amount_coins.toLocaleString()} coins · ${w.upi_id}`;
    left.append(title,meta);const status=document.createElement("span");status.className="status";status.textContent=w.status.replaceAll("_"," ");
    item.append(left,status);el.append(item);
  });
}
function render(){
  $("balance").textContent=Number(state.balance).toLocaleString("en-IN");
  $("rupee-balance").textContent=`≈ ₹${(state.balance/100).toFixed(2)} available`;
  $("ads-count").textContent=`${state.ads_today}/25 ads today`;
  $("profile-balance").textContent=Number(state.balance).toLocaleString("en-IN")+" coins";
  $("profile-ads").textContent=`${state.ads_today}/25`;
  if(state.user){
    const name=[state.user.first_name,state.user.last_name].filter(Boolean).join(" ")||"Telegram User";
    $("profile-name").textContent=name;
    $("profile-username").textContent=state.user.username?"@"+state.user.username:"No username set";
    $("profile-id").textContent="Telegram ID: "+state.user.telegram_id;
    $("avatar").textContent=(state.user.first_name||"C").slice(0,1).toUpperCase();
  }
  renderHistory("home-history");renderHistory("wallet-history");
}
async function refresh(){try{state=await api("/api/me");render()}catch(e){toast(e.message)}}
document.querySelectorAll(".tab").forEach(btn=>btn.addEventListener("click",()=>{
  document.querySelectorAll(".tab").forEach(x=>x.classList.toggle("active",x===btn));
  document.querySelectorAll(".panel").forEach(x=>x.classList.toggle("active",x.id==="panel-"+btn.dataset.tab));
}));
$("watch-btn").addEventListener("click",async()=>{try{await api("/api/claim-ad",{method:"POST",body:"{}"})}catch(e){toast(e.message)}});
$("amount").addEventListener("input",()=>{
  const amount=Math.max(0,Number($("amount").value)||0);
  $("coin-cost").textContent=`Cost: ${(amount*100).toLocaleString("en-IN")} coins`;
});
$("withdraw-form").addEventListener("submit",async e=>{
  e.preventDefault();const btn=$("withdraw-btn"),result=$("withdraw-result");
  btn.disabled=true;btn.textContent="Sending request…";result.hidden=true;result.className="result";
  try{
    const data=await api("/api/withdraw",{method:"POST",body:JSON.stringify({amount_rupees:$("amount").value,upi_id:$("upi").value.trim()})});
    result.textContent=data.message;result.hidden=false;$("withdraw-form").reset();$("coin-cost").textContent="Cost: 1,000 coins";await refresh();
  }catch(err){result.textContent=err.message;result.className="result error";result.hidden=false}
  finally{btn.disabled=false;btn.textContent="Request withdrawal"}
});
(async()=>{
 try{
   const config=await api("/api/config");
   if(config.demo_mode && !initData){$("mode-pill").textContent="Demo mode";toast("Demo mode: open through Telegram for a real user profile.")}
   if(tg?.initDataUnsafe?.user){const u=tg.initDataUnsafe.user;$("profile-name").textContent=[u.first_name,u.last_name].filter(Boolean).join(" ")}
   await refresh();
 }catch(e){toast(e.message)}
})();
