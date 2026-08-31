// Cloud references live in memory only. Browser-local bookmarks are a separate,
// explicitly imported library and must never become an implicit upload queue.
const validKey=key=>typeof key==="string" && /^(dataset|research|method|doc):[a-z0-9][a-z0-9-]{0,159}$/.test(key);
const cleanKeys=value=>Array.isArray(value)?[...new Set(value.filter(validKey))].slice(0,500):[];
export function createBookmarkLibrary({request,storage}) {
  let local=[];
  try {local=cleanKeys(JSON.parse(storage.getItem("td-bookmarks")||"[]"));} catch { /* inaccessible storage is not a cloud error */ }
  let state={mode:"checking",keys:[],userId:null,status:"loading",error:"",localCount:local.length};
  let epoch=0,controller=null,context="",listeners=new Set();
  const publish=patch=>{state={...state,...patch,localCount:local.length};listeners.forEach(listener=>listener());};
  async function cloud(endpoint,init={}) {
    controller?.abort(); controller=new AbortController();
    const generation=++epoch,userId=state.userId,signal=controller.signal;
    publish({status:"loading",error:""});
    try {
      const payload=await request(endpoint,{...init,signal,expectedIdentity:userId});
      if(generation!==epoch || signal.aborted) return;
      const library=payload?.bookmarks;
      if(library?.user_id!==userId || !Array.isArray(library.keys) || library.keys.length>500 || library.keys.some(key=>!validKey(key))) throw new Error("library_unconfirmed");
      publish({keys:cleanKeys(library.keys),status:"ready",error:""});
    } catch(error) {
      if(generation!==epoch || signal.aborted) return;
      // Hide unverifiable account contents after any failed operation. Retry reads
      // the server; no optimistic success and no automatic mutation replay.
      publish({keys:[],status:"error",error:error.message||"library_unconfirmed"});
    }
  }
  return {
    subscribe(listener) {listeners.add(listener);return()=>listeners.delete(listener);},
    snapshot:()=>state,
    setContext(account,viewState) {
      const mode=viewState==="checking"?"checking":viewState==="unavailable"?"blocked":account?.identity_kind==="email" && account.capabilities?.library===true?"cloud":"local";
      const userId=mode==="cloud"?account.user_id:null;
      const next=`${mode}:${userId||""}`; if(context===next) return;
      context=next; ++epoch;controller?.abort();
      publish({mode,userId,keys:mode==="local"?[...local]:[],status:["checking","cloud"].includes(mode)?"loading":mode==="blocked"?"error":"ready",error:""});
      if(mode==="cloud") return cloud("bookmarks");
    },
    toggle(key) {
      if(!validKey(key) || state.status!=="ready") return;
      const remove=state.keys.includes(key);
      if(state.mode==="cloud") return cloud("bookmarks/item",{method:remove?"DELETE":"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({key})});
      if(state.mode!=="local") return;
      if(!remove && local.length>=500) {publish({error:"library_full"});return;}
      const next=remove?local.filter(value=>value!==key):[...local,key];
      try {storage.setItem("td-bookmarks",JSON.stringify(next));}
      catch {publish({error:"local_unavailable"});return;}
      local=next;publish({keys:[...local],error:""});
    },
    importLocal() {
      if(state.mode!=="cloud" || state.status!=="ready") return;
      const keys=local.filter(key=>!state.keys.includes(key)).slice(0,100);
      if(keys.length) return cloud("bookmarks/import",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({keys})});
    },
    importCount:()=>local.filter(key=>!state.keys.includes(key)).length,
    refresh() {if(state.mode==="cloud") return cloud("bookmarks");},
    dispose() {++epoch;controller?.abort();listeners.clear();},
  };
}
