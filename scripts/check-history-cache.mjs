import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createHistoryCache } from '../frontend/src/historyCache.js'

const page = (count=500, watermark=1) => ({stream_id:'test-stream',watermark,daily_watermark:0,interval_watermark:0,
  candles:Array.from({length:count},(_,i)=>({timestamp:String(i).padStart(5,'0'),open:10,high:10,low:10,close:10,volume:null})),
  status:Array.from({length:count},(_,i)=>({timestamp:String(i).padStart(5,'0'),interval_ended:true})),next_before:'older'})

test('recent requests are bounded and identical in-flight reads coalesce',async()=>{
  let release, calls=0
  const cache=createHistoryCache(async(url)=>{
    calls++
    assert.equal(new URL(url,'http://local').searchParams.get('limit'),'500')
    await new Promise(resolve=>{release=resolve})
    return {ok:true,json:async()=>page()}
  })
  const first=cache.load('AAPL','5m'),second=cache.load('AAPL','5m')
  release()
  await Promise.all([first,second])
  assert.equal(calls,1)
  cache.dispose()
})

test('live revisions replace by timestamp, preserve unknown volume and beat stale HTTP',()=>{
  const cache=createHistoryCache()
  cache.put('AAPL','1m',page())
  const candle={...page(1).candles[0],timestamp:'00499',close:11}
  cache.update('AAPL','1m',{candle,completion:{timestamp:'00499',interval_ended:false},watermark:2})
  cache.put('AAPL','1m',page(500,1))
  assert.equal(cache.get('AAPL','1m').candles.at(-1).close,11)
  assert.equal(cache.get('AAPL','1m').candles.at(-1).volume,null)
  assert.equal(cache.get('AAPL','1m').status.at(-1).interval_ended,false)
  assert.equal(cache.get('AAPL','5m'),undefined)
  cache.dispose()
})

test('cache keeps only 500 recent bars and ten symbol/interval entries',()=>{
  const cache=createHistoryCache()
  cache.put('AAPL','1m',page(1950))
  assert.equal(cache.get('AAPL','1m').candles.length,500)
  assert.equal(cache.get('AAPL','1m').status.length,500)
  assert.equal(cache.get('AAPL','1m').next_before,'01450')
  for(let i=0;i<10;i++) cache.put(`TEST${i}`,'1m',page(1))
  assert.equal(cache.get('AAPL','1m'),undefined)
  cache.dispose()
})

test('prefetch reads SQLite only, runs serially and leaves foreground requests unqueued',async()=>{
  const calls=[]
  let release
  const cache=createHistoryCache(async(url)=>{
    const query=new URL(url,'http://local').searchParams
    calls.push([query.get('timeframe'),query.get('recent')])
    if(query.get('timeframe')==='5m') await new Promise(resolve=>{release=resolve})
    return {ok:true,json:async()=>page()}
  })
  cache.prefetch('AAPL',['5m','15m'])
  const deadline=Date.now()+1500
  while(!release && Date.now()<deadline) await new Promise(resolve=>setTimeout(resolve,10))
  assert.ok(release)
  await cache.load('AAPL','1h',true)
  assert.deepEqual(calls,[['5m','false'],['1h','true']])
  cache.cancelPrefetch()
  release()
  await new Promise(resolve=>setTimeout(resolve,20))
  assert.equal(calls.length,2)
  cache.dispose()
})
