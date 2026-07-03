#!/usr/bin/env node
// isaac-claw MCP stdio server: exposes Isaac control-server actions as dedicated
// named tools the local model can call cleanly (vs the generic exec/code bridge).
//
// NOTHING IS HARDCODED: the valid environments / robots / task ids are fetched
// LIVE from the control server (GET /templates,/robots,/envs) when the model asks
// for the tool list, and baked into the tool schemas as enums. Change your
// catalog.yaml / environments.yaml / envs_registry.json and it just shows up.
//
// TRANSPORT NOTE: the gateway spawns this MCP server WITHOUT http_proxy/https_proxy
// set (only NEMOCLAW_PROXY_HOST/PORT), and in a network namespace where a DIRECT
// connection to host.openshell.internal:5561 may be firewall-dropped. So we do our
// own transport with raw node:http (not fetch — fetch is proxy-patched/guarded and
// flaky here): TRY THE EGRESS PROXY FIRST (built from NEMOCLAW_PROXY_HOST/PORT),
// then FALL BACK TO DIRECT. Whichever path the serving netns allows wins.
import http from "node:http";
import fs from "node:fs";

const HOST = "host.openshell.internal";
const PORT = 5561;
const PROXY_HOST = process.env.NEMOCLAW_PROXY_HOST
  || (process.env.http_proxy||process.env.HTTP_PROXY||"").replace(/^https?:\/\//,"").split(":")[0]
  || "10.200.0.1";
const PROXY_PORT = parseInt(process.env.NEMOCLAW_PROXY_PORT
  || (process.env.http_proxy||process.env.HTTP_PROXY||"").split(":").pop()
  || "3128", 10);

function logErr(o){ try{ fs.appendFileSync("/sandbox/.openclaw/isaac-mcp-err.log", new Date().toISOString()+" "+JSON.stringify(o)+"\n"); }catch{} }

// One raw node:http request. useProxy=true → connect to the egress proxy and send
// an absolute-form request (origin-style forward proxy for http URLs).
function once(useProxy, method, path, data){
  return new Promise((resolve, reject)=>{
    const target = `http://${HOST}:${PORT}${path}`;
    const opts = useProxy
      ? { host: PROXY_HOST, port: PROXY_PORT, method, path: target,
          agent: new http.Agent({}),
          headers: { Host: `${HOST}:${PORT}`, "Content-Type":"application/json",
                     ...(data ? { "Content-Length": Buffer.byteLength(data) } : {}) } }
      : { host: HOST, port: PORT, method, path,
          agent: new http.Agent({}),
          headers: { "Content-Type":"application/json",
                     ...(data ? { "Content-Length": Buffer.byteLength(data) } : {}) } };
    const req = http.request(opts, (res)=>{
      let b=""; res.on("data",d=>b+=d);
      res.on("end",()=>{ (res.statusCode>=200 && res.statusCode<400) ? resolve(b)
                         : reject(new Error(`HTTP ${res.statusCode} via ${useProxy?"proxy":"direct"}`)); });
    });
    req.setTimeout(8000, ()=>req.destroy(new Error("timeout")));
    req.on("error", reject);
    if (data) req.write(data);
    req.end();
  });
}

async function fetchCS(method, path, body){
  const data = body ? JSON.stringify(body) : null;
  try { return await once(true, method, path, data); }        // proxy first
  catch (e1) {
    try { return await once(false, method, path, data); }     // then direct
    catch (e2) {
      const info = { error:"unreachable", proxyErr:String(e1&&(e1.message||e1)), directErr:String(e2&&(e2.message||e2)),
                     url:`http://${HOST}:${PORT}${path}`, proxy:`${PROXY_HOST}:${PROXY_PORT}` };
      logErr(info); return JSON.stringify(info);
    }
  }
}

// ---- LIVE catalog (fetched once per process/session; MCP restarts per session) ----
let _cat;
async function catalog(){
  if (_cat) return _cat;
  const getj = async (p)=>{ try{ const o=JSON.parse(await fetchCS("GET",p)); return (o&&o.error)?null:o; }catch{ return null; } };
  const [tpl, rob, env] = await Promise.all([getj("/templates"), getj("/robots"), getj("/envs")]);
  _cat = {
    envs:   tpl && tpl.environments ? Object.keys(tpl.environments) : null,
    robots: Array.isArray(rob) ? rob : (rob && Array.isArray(rob.robots) ? rob.robots : null),
    tasks:  env && Array.isArray(env.environments) ? env.environments.map(e=>e.id).filter(Boolean) : null,
  };
  return _cat;
}
// string field, with a live enum when we have the list (else free string + hint)
const S = (description, list)=> (list && list.length) ? { type:"string", description, enum:list } : { type:"string", description };

async function buildTools(){
  const c = await catalog();
  return [
    { name:"open_scene", description:"Open an Isaac Sim environment and launch the simulator with an optional robot placed in it. ANY robot works in ANY environment — mix freely (e.g. 'open hospital with agibot_a2d'). One GPU job at a time (close any running job first). Cloud scenes (office/hospital/grid_room/warehouse_full) stream from NVIDIA and take ~1-2 min to become ready.",
      inputSchema:{ type:"object", properties:{
        env: S("environment to open (live list from isaac__list_templates)", c.envs),
        robot: S("optional robot key (live list from isaac__list_robots); omit for an empty scene. Note: a few catalog entries are props/sensors, not drivable robots.", c.robots),
        anchor:{ type:"string", description:"optional named spawn location within the env (e.g. pick_station/entrance/center/dock); omit for the env default" } },
        required:["env"] } },
    { name:"list_robots", description:"List available robot keys from the live catalog.", inputSchema:{type:"object",properties:{}} },
    { name:"list_environments", description:"List available RL training task/environment ids (live).", inputSchema:{type:"object",properties:{}} },
    { name:"list_scenes", description:"List built scene USDs on disk.", inputSchema:{type:"object",properties:{}} },
    { name:"list_templates", description:"List openable environments and composite templates (live).", inputSchema:{type:"object",properties:{}} },
    { name:"sim_status", description:"Get the current sim/GPU job status (sim or training) — coarse: running, kind, pid, elapsed.", inputSchema:{type:"object",properties:{}} },
    { name:"training_status", description:"DETAILED training/job status: job info PLUS the tail of the live log (iterations, episode rewards, total timesteps, iteration time, ETA). Use whenever asked about training progress / 'how is the training going' / 'training status'. Report the latest iteration, key reward terms, timesteps, and ETA from the log.", inputSchema:{type:"object",properties:{lines:{type:"integer",description:"log lines to include (default 60)"}}} },
    { name:"train_task", description:"Start RL training for a task id. ONE GPU job at a time — close any running job first. AMP dance tasks (id contains 'AMP-Dance') REQUIRE backend='skrl' and algorithm='amp'. gui=true opens a visible window (few envs); headless is faster with many envs.",
      inputSchema:{ type:"object", properties:{
        task: S("RL task id (live list from isaac__list_environments)", c.tasks),
        backend:{ type:"string", description:"rsl_rl | skrl | cusrl (default rsl_rl); AMP dance needs skrl" },
        algorithm:{ type:"string", description:"skrl algorithm entry point, e.g. 'amp' for AMP dance" },
        num_envs:{ type:"integer", description:"parallel envs (gui default 64, headless 4096)" },
        gui:{ type:"boolean", description:"open a visible window (default false = headless)" },
        max_iterations:{ type:"integer" }, seed:{ type:"integer" },
        params:{ type:"object", description:"advised hyperparameters (rsl_rl/cusrl), friendly names -> values, e.g. {learning_rate:1e-3, entropy_coef:0.015, gamma:0.99, num_steps_per_env:24, reward_feet_air_time:2.5}. Get valid knobs+ranges from isaac__tuning_guide. reward_* weights are best-effort (a task may re-pin them)." },
        overrides:{ type:"array", items:{type:"string"}, description:"raw Hydra overrides for any backend (incl. skrl), e.g. [\"agent.algorithm.learning_rate=1e-3\"]" } },
        required:["task"] } },
    { name:"tuning_guide", description:"Get the research/repo-advised hyperparameter tuning guide for a backend (safe ranges + symptom->knob table + friendly-knob->Hydra map). Read this BEFORE choosing params for a tuned training run so values come from real guidance, not guesses.",
      inputSchema:{ type:"object", properties:{ backend:{ type:"string", description:"rsl_rl | cusrl | skrl | rl_games | sb3 | robomimic (default rsl_rl)" } } } },
    { name:"play_policy", description:"Play/visualize (INFERENCE for) a trained RL policy for a task, optionally from a checkpoint.",
      inputSchema:{ type:"object", properties:{
        task: S("RL task id (live list from isaac__list_environments)", c.tasks),
        backend:{ type:"string" }, checkpoint:{ type:"string" }, num_envs:{ type:"integer" } },
        required:["task"] } },
    { name:"eval_policy", description:"Evaluate a trained RL policy for a task, optionally from a checkpoint.",
      inputSchema:{ type:"object", properties:{
        task: S("RL task id (live list from isaac__list_environments)", c.tasks),
        backend:{ type:"string" }, checkpoint:{ type:"string" }, num_envs:{ type:"integer" } },
        required:["task"] } },
    { name:"close_sim", description:"Stop the running SIM and free the GPU.", inputSchema:{type:"object",properties:{}} },
    { name:"stop_training", description:"Stop the running TRAINING/eval/play job (any GPU job) and free the GPU. Use for 'stop training', 'cancel the run', 'kill the job'.", inputSchema:{type:"object",properties:{}} },
  ];
}

async function call(name, a){
  a = a || {};
  if (name==="open_scene"){ const b={env:a.env,gui:true}; if(a.robot) b.robot=a.robot; if(a.anchor) b.anchor=a.anchor; return fetchCS("POST","/open",b); }
  if (name==="list_robots") return fetchCS("GET","/robots");
  if (name==="list_environments") return fetchCS("GET","/envs");
  if (name==="list_scenes") return fetchCS("GET","/scenes");
  if (name==="list_templates") return fetchCS("GET","/templates");
  if (name==="sim_status") return fetchCS("GET","/status");
  if (name==="training_status"){
    const pj = (t)=>{ try{ return JSON.parse(t); }catch{ return t; } };
    const n = Number(a.lines) || 200;
    const [st, lg] = await Promise.all([ fetchCS("GET","/status"), fetchCS("GET","/logs?lines="+n) ]);
    const status = pj(st);
    const logObj = pj(lg);
    let text = (logObj && typeof logObj.lines === "string") ? logObj.lines
             : Array.isArray(logObj && logObj.lines) ? logObj.lines.join("\n")
             : (typeof logObj === "string" ? logObj : "");
    const lines = text.split(/\r?\n/);
    const last = (re, grp=1)=>{ for(let i=lines.length-1;i>=0;i--){ const m=lines[i].match(re); if(m) return m[grp]; } return null; };
    const rewards = {};
    for (const l of lines){ const m=l.match(/Episode_Reward\/(\S+):\s*(-?\d[\d.eE+-]*)/); if(m) rewards[m[1]]=parseFloat(m[2]); }
    const summary = {
      iteration: last(/(?:Learning iteration|Iteration)\s*[:#]?\s*([\d]+\s*\/\s*[\d]+|[\d]+)/),
      total_timesteps: last(/Total timesteps:\s*([\d]+)/),
      iteration_time_s: last(/Iteration time:\s*([\d.]+)/),
      eta: last(/ETA:\s*([\d:]+)/),
      mean_reward: last(/[Mm]ean (?:episode )?reward:?\s*(-?[\d.]+)/),
      fps: last(/(?:fps|FPS|steps\/s)[:=]?\s*([\d.]+)/),
      reward_terms: rewards,
    };
    return JSON.stringify({ status, summary, log_file: logObj && logObj.log_file, log_tail: lines.slice(-25).join("\n") }, null, 2);
  }
  if (name==="close_sim" || name==="stop_training") return fetchCS("POST","/stop",{});
  if (name==="train_task"){
    const b={task:a.task};
    if(a.backend) b.backend=a.backend;
    if(a.algorithm) b.algorithm=a.algorithm;
    if(a.num_envs!=null) b.num_envs=a.num_envs;
    if(a.gui) b.gui=true;
    if(a.max_iterations!=null) b.max_iterations=a.max_iterations;
    if(a.seed!=null) b.seed=a.seed;
    if(a.params && typeof a.params==="object") b.params=a.params;
    if(Array.isArray(a.overrides)) b.overrides=a.overrides;
    return fetchCS("POST","/train",b);
  }
  if (name==="tuning_guide") return fetchCS("GET","/tuning?backend="+encodeURIComponent(a.backend||"rsl_rl"));
  if (name==="play_policy" || name==="eval_policy"){
    const b={task:a.task};
    if(a.backend) b.backend=a.backend;
    if(a.checkpoint) b.checkpoint=a.checkpoint;
    if(a.num_envs!=null) b.num_envs=a.num_envs;
    return fetchCS("POST", name==="play_policy"?"/play":"/eval", b);
  }
  return JSON.stringify({error:"unknown tool "+name});
}

const send = o => process.stdout.write(JSON.stringify(o)+"\n");
let buf="";
process.stdin.on("data", async d => {
  buf += d.toString(); let i;
  while((i = buf.indexOf("\n")) >= 0){
    const line = buf.slice(0,i).trim(); buf = buf.slice(i+1);
    if(!line) continue;
    let m; try{ m = JSON.parse(line); }catch{ continue; }
    const { id, method, params } = m;
    if(method==="initialize") send({jsonrpc:"2.0",id,result:{protocolVersion:"2024-11-05",capabilities:{tools:{}},serverInfo:{name:"isaac",version:"1.3.0"}}});
    else if(method==="tools/list") send({jsonrpc:"2.0",id,result:{tools: await buildTools()}});
    else if(method==="tools/call"){ const text = await call(params&&params.name, params&&params.arguments); send({jsonrpc:"2.0",id,result:{content:[{type:"text",text}]}}); }
    else if(method==="ping") send({jsonrpc:"2.0",id,result:{}});
    else if(method && method.startsWith("notifications/")){ /* no response */ }
    else if(id!==undefined) send({jsonrpc:"2.0",id,error:{code:-32601,message:"method not found: "+method}});
  }
});
process.stdin.resume();
