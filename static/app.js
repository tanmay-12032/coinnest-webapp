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
// Replace this with the numeric Reward block ID from your AdsGram publisher dashboard.
const ADSGRAM_BLOCK_ID = "YOUR_ADSGRAM_BLOCK_ID";
let adController = null;
try {
  if (window.Adsgram && ADSGRAM_BLOCK_ID !== "YOUR_ADSGRAM_BLOCK_ID") {
    adController = window.Adsgram.init({ blockId: ADSGRAM_BLOCK_ID });
  }
} catch (e) { console.error("AdsGram initialization failed", e); }

$("watch-btn").addEventListener("click", async () => {
  const btn = $("watch-btn");
  if (ADSGRAM_BLOCK_ID === "YOUR_ADSGRAM_BLOCK_ID") {
    toast("Add your AdsGram Reward Block ID in static/app.js first.");
    return;
  }
  if (!window.Adsgram) { toast("AdsGram script is not loaded. Please retry."); return; }
  try {
    adController = adController || window.Adsgram.init({ blockId: ADSGRAM_BLOCK_ID });
    btn.disabled = true; btn.textContent = "Loading ad…";
    await adController.show();
    // AdsGram's rewarded SDK resolves after the rewarded ad completes.
    const data = await api("/api/claim-ad", { method: "POST", body: "{}" });
    toast(data.message || "Reward added!");
    await refresh();
  } catch (e) {
    toast(e.message || "Ad was not completed. No coins were added.");
  } finally {
    btn.disabled = false; btn.textContent = "Watch ads";
  }
});
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
  if(btn.dataset.game==="maze"){ball={r:1,c:1};mazeRewardPrompted=false;$("maze-feedback").textContent="";drawMaze();}
  if(btn.dataset.game==="village") newVillage();
}));
document.querySelectorAll("[data-close-game]").forEach(btn=>btn.addEventListener("click",()=>{
  btn.closest(".game-panel").hidden=true;
}));

let mathAnswer=0, mathScore=0, mathRound=0;
function nextMath(){
  const a=Math.floor(Math.random()*20)+1,b=Math.floor(Math.random()*20)+1;
  const op=Math.random()>.5?"+":"−";
  mathAnswer=op==="+"?a+b:a-b;
  $("math-question").textContent=`${a} ${op} ${b} = ?`;
  const choices=new Set([mathAnswer,mathAnswer+Math.ceil(Math.random()*5),mathAnswer-Math.ceil(Math.random()*5),mathAnswer+Math.ceil(Math.random()*10)]);
  const arr=[...choices].sort(()=>Math.random()-.5).slice(0,4);
  if(!arr.includes(mathAnswer)) arr[0]=mathAnswer;
  $("math-answers").innerHTML="";
  arr.sort(()=>Math.random()-.5).forEach(n=>{
    const b=document.createElement("button");b.className="answer-button";b.textContent=n;
    b.addEventListener("click",()=>{
      if(n===mathAnswer){mathScore++;$("math-feedback").textContent=`Correct! Score: ${mathScore}`;}
      else $("math-feedback").textContent=`Not quite — correct answer: ${mathAnswer}. Score: ${mathScore}`;
      mathRound++; if(mathRound<10) nextMath(); else {$("math-question").textContent=`Quiz complete! Final score: ${mathScore}/10`; $("math-answers").innerHTML="";}
    });$("math-answers").append(b);
  });
}
$("math-start")?.addEventListener("click",()=>{mathScore=0;mathRound=0;$("math-feedback").textContent="";nextMath()});

// Small fixed maze; # are walls, S is start, E is exit.
const mazeMap=["#########","#S#.....#","#.#.###.#","#...#...#","###.#.#E#","#.....#.#","#########"];
let ball={r:1,c:1};
let mazeRewardPrompted=false;
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
  const delta={up:[-1,0],down:[1,0],left:[0,-1],right:[0,1]}[dir];if(!delta)return;
  const r=ball.r+delta[0],c=ball.c+delta[1];
  if(!mazeMap[r]||mazeMap[r][c]==="#"||!mazeMap[r][c])return;
  ball={r,c};drawMaze();
  if(mazeMap[r][c]==="E"){
    $("maze-feedback").textContent="You escaped the maze! 🎉";
    if(!mazeRewardPrompted){mazeRewardPrompted=true;openMazeReward();}
  }
}
function openMazeReward(){
  const modal=$("maze-reward-modal");
  if(!modal)return;
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
    const result=await api("/api/claim-game-reward",{method:"POST",body:JSON.stringify({game:"maze"})});
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
document.querySelectorAll("[data-move]").forEach(b=>b.addEventListener("click",()=>moveBall(b.dataset.move)));
document.addEventListener("keydown",e=>{if(!$("game-maze")?.hidden){const d={ArrowUp:"up",ArrowDown:"down",ArrowLeft:"left",ArrowRight:"right"}[e.key];if(d){e.preventDefault();moveBall(d)}}});

// Village hidden-object game: tap the matching tiny objects.
const villageItems=["🪣","🌻","🍎","🪣","🐓","🪵","🪣","🍎","🌻","🐓","🪵","🍎","🌻","🐓","🪵","🍎","🌻","🐓","🪵","🍎","🌻","🐓","🪵","🍎"];
let villageFound=0,villageNeed=3;
function newVillage(){
  villageFound=0;villageNeed=3;$("village-target").textContent="🪣 bucket × 3";$("village-feedback").textContent="Tap all 3 buckets hidden in the village.";
  const scene=$("village-scene");scene.innerHTML="";
  // shuffle positions so the scene is different each round
  villageItems.slice().sort(()=>Math.random()-.5).forEach((emoji,i)=>{
    const item=document.createElement("button");item.className="village-object";item.textContent=emoji;item.setAttribute("aria-label","Village object");
    item.addEventListener("click",()=>{
      if(item.disabled)return;
      if(emoji==="🪣"){item.disabled=true;item.classList.add("found");villageFound++;$("village-feedback").textContent=`Found ${villageFound}/${villageNeed} buckets!`;if(villageFound===villageNeed)$("village-feedback").textContent="All buckets found! Great job 🎉";}
      else {$("village-feedback").textContent="Not that one — keep searching!";}
    });scene.append(item);
  });
}
