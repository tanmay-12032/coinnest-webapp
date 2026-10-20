const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); }
const initData = tg?.initData || "";
let state = { balance: 0, user: null, withdrawals: [] };
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
  if(!el) return;
  if(!state.withdrawals.length){el.className="history empty";el.textContent="No withdrawal requests yet.";return}
  el.className="history";el.innerHTML="";
  state.withdrawals.forEach(w=>{
    const item=document.createElement("div");item.className="history-item";
    const left=document.createElement("div"), title=document.createElement("b"), meta=document.createElement("span");
    const methodName=({payz:"Payz",upi:"UPI",cwallet:"Cwallet USDT"})[w.method]||"Payz";
    const amountLabel=w.method==="cwallet"?`${Number(w.amount_value||0).toFixed(2)} USDT`:`₹${w.amount_rupees}`;
    title.textContent=`Withdrawal #${w.id} · ${amountLabel}`;
    meta.textContent=`${methodName} · ${w.amount_coins.toLocaleString()} coins · ${w.payout_id||w.upi_id}`;
    left.append(title,meta);const status=document.createElement("span");status.className="status";status.textContent=w.status.replaceAll("_"," ");
    item.append(left,status);el.append(item);
  });
}
function render(){
  $("balance").textContent=Number(state.balance).toLocaleString("en-IN");
  $("rupee-balance").textContent=`≈ ₹${(state.balance/100).toFixed(2)} available`;
  $("profile-hero-balance").textContent=Number(state.balance).toLocaleString("en-IN");
  $("profile-hero-rupees").textContent=`≈ ₹${(state.balance/100).toFixed(2)} available`;
  if(state.user){
    const name=[state.user.first_name,state.user.last_name].filter(Boolean).join(" ")||"Telegram User";
    $("profile-name").textContent=name;
    $("profile-username").textContent=state.user.username?"@"+state.user.username:"No username set";
    $("profile-id").textContent="Telegram ID: "+state.user.telegram_id;
    $("avatar").textContent=(state.user.first_name||"C").slice(0,1).toUpperCase();
  }
  renderHistory("wallet-history");
}
async function refresh(){try{state=await api("/api/me");render()}catch(e){toast(e.message)}}
document.querySelectorAll(".tab").forEach(btn=>btn.addEventListener("click",()=>{
  document.querySelectorAll(".tab").forEach(x=>x.classList.toggle("active",x===btn));
  document.querySelectorAll(".panel").forEach(x=>x.classList.toggle("active",x.id==="panel-"+btn.dataset.tab));
}));
let selectedWithdrawalMethod="payz";
const withdrawalMethods={
 payz:{label:"Payz Gateway number",placeholder:"Enter 10-digit Payz number",inputmode:"numeric",type:"tel",maxLength:20,amountLabel:"Withdrawal amount (₹)",min:1,step:1,amountPlaceholder:"e.g. 1",minLabel:"Minimum withdrawal",minValue:"₹1",infoLabel:"Payz number",infoValue:"10 digits"},
 upi:{label:"UPI ID",placeholder:"name@bank",inputmode:"text",type:"text",maxLength:100,amountLabel:"Withdrawal amount (₹)",min:50,step:1,amountPlaceholder:"e.g. 50",minLabel:"Minimum withdrawal",minValue:"₹50",infoLabel:"UPI ID",infoValue:"Must contain @" },
 cwallet:{label:"Cwallet ID",placeholder:"Enter your Cwallet ID",inputmode:"text",type:"text",maxLength:120,amountLabel:"Withdrawal amount (USDT)",min:0.01,step:0.01,amountPlaceholder:"e.g. 0.01",minLabel:"Minimum withdrawal",minValue:"0.01 USDT",infoLabel:"Conversion rate",infoValue:"100 coins = 0.01 USDT"}
};
function updateWithdrawalMethod(method){
 selectedWithdrawalMethod=method;const cfg=withdrawalMethods[method];
 document.querySelectorAll(".method-option").forEach(b=>b.classList.toggle("active",b.dataset.method===method));
 const payout=$("payout-id"),amount=$("amount");payout.value="";amount.value="";
 $("payout-label").textContent=cfg.label;payout.placeholder=cfg.placeholder;payout.inputMode=cfg.inputmode;payout.type=cfg.type;payout.maxLength=cfg.maxLength;
 $("amount-label").textContent=cfg.amountLabel;amount.min=cfg.min;amount.step=cfg.step;amount.placeholder=cfg.amountPlaceholder;
 $("minimum-label").textContent=cfg.minLabel;$("minimum-value").textContent=cfg.minValue;
 $("conversion-label").textContent=cfg.infoLabel;$("conversion-value").textContent=cfg.infoValue;updateCoinCost();
}
function updateCoinCost(){const amount=Math.max(0,Number($("amount").value)||0);const coins=selectedWithdrawalMethod==="cwallet"?Math.round(amount*10000):Math.round(amount*100);$("coin-cost").textContent=`Cost: ${coins.toLocaleString("en-IN")} coins`;}
document.querySelectorAll(".method-option").forEach(b=>b.addEventListener("click",()=>updateWithdrawalMethod(b.dataset.method)));
$("amount").addEventListener("input",updateCoinCost);
$("withdraw-form").addEventListener("submit",async e=>{
 e.preventDefault();const btn=$("withdraw-btn"),result=$("withdraw-result");btn.disabled=true;btn.textContent="Sending request…";result.hidden=true;result.className="result";
 try{const data=await api("/api/withdraw",{method:"POST",body:JSON.stringify({method:selectedWithdrawalMethod,amount:$("amount").value,payout_id:$("payout-id").value.trim()})});result.textContent=data.message;result.hidden=false;$("withdraw-form").reset();updateCoinCost();await refresh();}
 catch(err){result.textContent=err.message;result.className="result error";result.hidden=false;}
 finally{btn.disabled=false;btn.textContent="Withdraw now";}
});
updateWithdrawalMethod("payz");
(async()=>{
 try{
   const config=await api("/api/config");
   if(config.demo_mode && !initData){$("mode-pill").textContent="Demo mode";toast("Demo mode: open through Telegram for a real user profile.")}
   if(tg?.initDataUnsafe?.user){const u=tg.initDataUnsafe.user;$("profile-name").textContent=[u.first_name,u.last_name].filter(Boolean).join(" ")}
   await refresh();
 }catch(e){toast(e.message)}
})();


// Referral dashboard: the server owns attribution and statistics.
async function loadReferrals(){
  try{
    const d=await api("/api/referrals");
    $("ref-total").textContent=d.total ?? 0;
    $("ref-completed").textContent=d.completed ?? 0;
    $("ref-bonus").textContent=d.bonus_coins ?? 0;
    $("ref-link").value=d.referral_link || "";
    if(d.note) $("ref-note").textContent=d.note;
  }catch(e){ if($("ref-note")) $("ref-note").textContent=e.message; }
}
$("copy-ref")?.addEventListener("click",async()=>{
  const link=$("ref-link").value;
  if(!link){toast("Open CoinNest from Telegram first.");return}
  try{await navigator.clipboard.writeText(link);toast("Referral link copied!")}
  catch(e){$("ref-link").focus();$("ref-link").select();toast("Select and copy your link.")}
});
loadReferrals();

(async()=>{
  try{
    const config=await api("/api/config");
    if(config.demo_mode && !initData){$("mode-pill").textContent="Demo mode";toast("Demo mode: open through Telegram for a real user profile.")}
    if(tg?.initDataUnsafe?.user){const u=tg.initDataUnsafe.user;$("profile-name").textContent=[u.first_name,u.last_name].filter(Boolean).join(" ")}
    await refresh();
  }catch(e){toast(e.message)}
})();
