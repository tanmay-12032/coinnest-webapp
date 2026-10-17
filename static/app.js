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
  $("ads-count").textContent=`${state.ads_today}/25 ads today`;
  $("profile-hero-balance").textContent=Number(state.balance).toLocaleString("en-IN");
  $("profile-hero-rupees").textContent=`≈ ₹${(state.balance/100).toFixed(2)} available`;
  $("profile-hero-ads-count").textContent=`${state.ads_today}/25 ads today`;
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
// Monetag SDK loader. Use the zone ID and script URL supplied by Monetag.
let monetagConfig = null;
let monetagLoadPromise = null;
async function loadMonetag() {
  if (monetagLoadPromise) return monetagLoadPromise;
  monetagLoadPromise = (async () => {
    monetagConfig = await api("/api/config");
    const zone = String(monetagConfig.monetag_zone_id || "12053770").trim();
    const sdkUrl = String(monetagConfig.monetag_sdk_url || "").trim();
    if (!sdkUrl) throw new Error("Add MONETAG_SDK_URL from your Monetag dashboard in Vercel.");
    const sdkName = `show_${zone}`;
    if (typeof window[sdkName] === "function") return sdkName;
    await new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = sdkUrl; script.async = true;
      script.dataset.coinnestMonetag = zone;
      script.onload = resolve;
      script.onerror = () => reject(new Error("Monetag SDK failed to load. Check MONETAG_SDK_URL."));
      document.head.appendChild(script);
    });
    if (typeof window[sdkName] !== "function") throw new Error(`Monetag function ${sdkName} was not created. Check the exact SDK script from Monetag.`);
    return sdkName;
  })();
  try { return await monetagLoadPromise; }
  catch (e) { monetagLoadPromise = null; throw e; }
}

$("watch-btn").addEventListener("click", async () => {
  const btn = $("watch-btn");
  btn.disabled = true; btn.textContent = "Loading ad…";
  try {
    const sdkName = await loadMonetag();
    // Matches the Monetag snippet provided by the user: show_12053770('pop').
    await window[sdkName]("pop");
    const result = await api("/api/monetag/claim", { method: "POST", body: JSON.stringify({ format: "pop" }) });
    toast(`Ad flow completed. ${result.reward} coins added.`);
    await refresh();
  } catch (e) {
    toast(e.message || "Ad was unavailable or did not complete. No coins were added.");
  } finally {
    btn.disabled = false; btn.textContent = "Watch ads";
  }
});
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

// Games are entertainment only; they do not grant coins or affect referral eligibility.
document.querySelectorAll("[data-game]").forEach(btn=>btn.addEventListener("click",()=>{
  document.querySelectorAll(".game-panel").forEach(p=>p.hidden=true);
  const panel=$("game-"+btn.dataset.game); if(panel) panel.hidden=false;
  if(btn.dataset.game==="maze")startNewMaze();
  if(btn.dataset.game==="village") newVillage();
}));
document.querySelectorAll("[data-close-game]").forEach(btn=>btn.addEventListener("click",()=>{
  btn.closest(".game-panel").hidden=true;
}));

let mathAnswer=0, mathScore=0, mathRound=0, mathRewardPrompted=false, mathAnswerCount=0, pendingRetry=null;
function nextMath(){
  const op=["+","−","×","÷"][Math.floor(Math.random()*4)];
  let a,b;
  if(op==="÷"){b=Math.floor(Math.random()*9)+2;mathAnswer=Math.floor(Math.random()*12)+1;a=b*mathAnswer;}
  else {a=Math.floor(Math.random()*30)+1;b=Math.floor(Math.random()*20)+1;mathAnswer=op==="+"?a+b:op==="−"?a-b:a*b;}
  $("math-question").textContent=`${a} ${op} ${b} = ?`;
  const choices=new Set([mathAnswer,mathAnswer+Math.ceil(Math.random()*5),mathAnswer-Math.ceil(Math.random()*5),mathAnswer+Math.ceil(Math.random()*10)]);
  const arr=[...choices].sort(()=>Math.random()-.5).slice(0,4);
  if(!arr.includes(mathAnswer)) arr[0]=mathAnswer;
  $("math-answers").innerHTML="";
  arr.sort(()=>Math.random()-.5).forEach(n=>{
    const b=document.createElement("button");b.className="answer-button";b.textContent=n;
    b.addEventListener("click",()=>{
      if(n!==mathAnswer){showIncorrect("math",()=>{},()=>advanceMath(false));return;}
      mathScore++;mathAnswerCount++;$("math-feedback").textContent=`Correct! Score: ${mathScore}`;
      advanceMath(true);
    });$("math-answers").append(b);
  });
}
function advanceMath(correct){
  mathRound++;
  if(mathAnswerCount>0 && mathAnswerCount%5===0){openGameReward("math");}
  if(mathRound>=10){$("math-question").textContent=`Quiz complete! Final score: ${mathScore}/10`;$("math-answers").innerHTML="";return;}
  nextMath();
}
$("math-start")?.addEventListener("click",()=>{mathScore=0;mathRound=0;mathAnswerCount=0;mathRewardPrompted=false;$("math-feedback").textContent="";nextMath()});

// Small fixed maze; # are walls, S is start, E is exit.
const mazeMap=["#########","#S#.....#","#.#.###.#","#...#...#","###.#.#.#","#.....#.E","#########"];
let ball={r:1,c:1};
let mazeRewardPrompted=false, mazeWon=false;
function startNewMaze(){
  const cells=[];mazeMap.forEach((row,r)=>[...row].forEach((ch,c)=>{if(ch==="."||ch==="S")cells.push({r,c})}));
  ball=cells[Math.floor(Math.random()*cells.length)];mazeRewardPrompted=false;mazeWon=false;
  $("maze-feedback").textContent="Find the exit on the outer boundary!";drawMaze();
}
function drawMaze(){
  const board=$("maze-board"); if(!board)return;board.innerHTML="";
  mazeMap.forEach((row,r)=>[...row].forEach((cell,c)=>{
    const tile=document.createElement("div");tile.className="maze-cell "+(cell==="#"?"wall":"path");
    if(r===ball.r&&c===ball.c){tile.textContent="🔵";tile.classList.add("ball")}
    else if(cell==="E")tile.textContent="🟢";
    board.append(tile);
  }));
}
function moveBall(dir){
  if(mazeWon)return;
  const delta={up:[-1,0],down:[1,0],left:[0,-1],right:[0,1]}[dir];if(!delta)return;
  const r=ball.r+delta[0],c=ball.c+delta[1];
  if(!mazeMap[r]||mazeMap[r][c]==="#"||!mazeMap[r][c])return;
  ball={r,c};drawMaze();
  if(mazeMap[r][c]==="E"){
    mazeWon=true;$("maze-feedback").textContent="You escaped the maze! 🎉";
    if(!mazeRewardPrompted){mazeRewardPrompted=true;openGameReward("maze");}
  }
}
let currentRewardGame="maze";
function openGameReward(game){
  currentRewardGame=game;
  const modal=$("maze-reward-modal");
  if(!modal)return;
  $("maze-reward-title").textContent="You won 5 coins!";
  $("maze-reward-message").textContent="";
  $("maze-claim").disabled=false;
  $("maze-claim").textContent="Claim 5 coins";
  modal.hidden=false;
}
function closeMazeReward(){ $("maze-reward-modal").hidden=true; }
$("maze-skip")?.addEventListener("click",closeMazeReward);
$("maze-claim")?.addEventListener("click",async()=>{
  const btn=$("maze-claim");
  btn.disabled=true;btn.textContent="Claiming…";
  try{
    const result=await api("/api/claim-game-reward",{method:"POST",body:JSON.stringify({game:currentRewardGame})});
    $("maze-reward-message").textContent=result.message||"5 coins added to your balance!";
    $("maze-reward-message").classList.add("success");
    await refresh();
    btn.textContent="Claimed ✓";
    setTimeout(closeMazeReward,1200);
  }catch(e){
    $("maze-reward-message").textContent=e.message;
    btn.disabled=false;btn.textContent="Try claim again";
  }
});
$("maze-new-game")?.addEventListener("click",startNewMaze);
document.querySelectorAll("[data-move]").forEach(b=>b.addEventListener("click",()=>moveBall(b.dataset.move)));
document.addEventListener("keydown",e=>{if(!$("game-maze")?.hidden){const d={ArrowUp:"up",ArrowDown:"down",ArrowLeft:"left",ArrowRight:"right"}[e.key];if(d){e.preventDefault();moveBall(d)}}});


let incorrectRetryAction=null, incorrectCancelAction=null;
function showIncorrect(game,retry,cancel){
  incorrectRetryAction=retry;incorrectCancelAction=cancel;
  const m=$("incorrect-modal");if(!m)return;
  $("incorrect-message").textContent=game==="math"?"Wrong answer. Try this question again?":"Wrong object. Try choosing again?";
  m.hidden=false;
}
$("incorrect-retry")?.addEventListener("click",()=>{ $("incorrect-modal").hidden=true; if(incorrectRetryAction)incorrectRetryAction(); });
$("incorrect-cancel")?.addEventListener("click",()=>{ $("incorrect-modal").hidden=true; if(incorrectCancelAction)incorrectCancelAction(); });

// Village hidden-object game: tap the matching tiny objects.
const villageObjectSets=[
 {emoji:"🪣",name:"buckets",count:4,others:["🌻","🍎","🐓","🪵","🧺","🥕","🐈","🪴","🪚"]},
 {emoji:"🍎",name:"apples",count:5,others:["🪣","🌻","🐓","🪵","🧺","🥕","🐈","🪴","🍐"]},
 {emoji:"🐓",name:"chickens",count:4,others:["🪣","🌻","🍎","🪵","🧺","🥕","🐈","🪴","🐇"]},
 {emoji:"🌻",name:"sunflowers",count:5,others:["🪣","🍎","🐓","🪵","🧺","🥕","🐈","🪴","🌷"]}
];
let villageFound=0,villageNeed=3,villageTarget="🪣";
function newVillage(){
 villageFound=0;const set=villageObjectSets[Math.floor(Math.random()*villageObjectSets.length)];
 villageTarget=set.emoji;villageNeed=set.count;$("village-target").textContent=`${set.emoji} ${set.name} × ${set.count}`;
 $("village-feedback").textContent=`Find all ${set.count} ${set.name}.`;
 const scene=$("village-scene");scene.innerHTML="";
 const items=Array.from({length:48},()=>set.others[Math.floor(Math.random()*set.others.length)]);
 const slots=new Set();while(slots.size<set.count)slots.add(Math.floor(Math.random()*items.length));
 slots.forEach(i=>items[i]=set.emoji);items.sort(()=>Math.random()-.5).forEach(emoji=>{
  const item=document.createElement("button");item.className="village-object";item.textContent=emoji;item.setAttribute("aria-label","Village object");
  item.addEventListener("click",()=>{if(item.disabled)return;if(emoji===villageTarget){item.disabled=true;item.classList.add("found");villageFound++;$("village-feedback").textContent=`Found ${villageFound}/${villageNeed}!`;if(villageFound===villageNeed){$("village-feedback").textContent="All objects found! 🎉";openGameReward("village");}}else showIncorrect("village",()=>{item.disabled=false;item.classList.remove("found");},()=>{$("village-feedback").textContent="Keep searching for the remaining objects.";});});
  scene.append(item);
 });
}

// Ensure the village challenge reset button is wired up.
document.getElementById("village-reset")?.addEventListener("click", () => newVillage());
