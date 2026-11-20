import assert from 'node:assert/strict'
import test from 'node:test'
import { evaluateSmaStrategy } from '../frontend/src/smaStrategy.js'

const times = ['14:30','14:31','14:32','14:33'].map((time) => `2026-11-09T${time}:00Z`)
const candles = [10,12,9,13].map((close,i) => ({timestamp:times[i],close}))
const values = (prices) => prices.map((value,i) => ({timestamp:times[i],value}))
const instances = [
  {indicator_id:1,name:'Fast',type:'sma',settings:{window:1},values:values([10,12,9,13])},
  {indicator_id:2,name:'Slow',type:'sma',settings:{window:2},values:values([null,11,10.5,11])},
  {indicator_id:3,name:'Other',type:'sma',settings:{window:3},values:values([null,null,10.33,11.33])},
]
const status = Object.fromEntries(times.map((timestamp) => [timestamp,{interval_ended:true,coverage_complete:true}]))
const config = {fastId:'1',slowId:'2',quantity:'2'}
const signals = {fast_id:1,slow_id:2,quantity:2,points:[
  {timestamp:times[0],available:false,signal:'none'},
  {timestamp:times[1],available:false,signal:'none'},
  {timestamp:times[2],available:true,signal:'downward',fastValue:9,slowValue:10.5,price:9,estimated_cost_cents:1800},
  {timestamp:times[3],available:true,signal:'upward',fastValue:13,slowValue:11,price:13,estimated_cost_cents:2600},
]}
const run = (overrides={}) => evaluateSmaStrategy({config,instances,signals,cutoff:times[3],account:{cash:1000,cash_cents:100000,shares:0},...overrides})

test('selected pair controls markers and upward entry with quantity',()=>{
  const result=run()
  assert.deepEqual([result.fastWindow,result.slowWindow,result.signal,result.action,result.actionQuantity],[1,2,'upward','buy',2])
  assert.deepEqual(result.markers,[{timestamp:times[2],signal:'downward'},{timestamp:times[3],signal:'upward'}])
})
test('downward closes entire holding; flat waits',()=>{
  assert.equal(run({cutoff:times[2]}).action,'wait')
  const result=run({cutoff:times[2],account:{cash:600,cash_cents:60000,shares:4}})
  assert.deepEqual([result.action,result.actionQuantity],['close',4])
})
test('no additional buying while invested; no repeated upward entry',()=>{
  assert.equal(run({account:{cash:600,cash_cents:60000,shares:4}}).action,'hold')
  assert.equal(run({cutoff:times[1]}).available,false,'needs two comparable SMA pairs')
})
test('cash must cover full entry quantity',()=>{
  assert.equal(run({account:{cash:25,cash_cents:2500,shares:0}}).action,'wait')
  assert.equal(run({account:{cash:26,cash_cents:2600,shares:0}}).action,'buy')
  const quoted = {...signals,points:signals.points.map(point=>({...point,price:1.005,estimated_cost_cents:202}))}
  assert.equal(run({signals:quoted,account:{cash:2.01,cash_cents:201,shares:0}}).action,'wait','use shared HALF_UP quote, not browser floating rounding')
  assert.equal(run({signals:quoted,account:{cash:2.02,cash_cents:202,shares:0}}).action,'buy')
})
test('invalid pairs and quantities cannot produce actions',()=>{
  for (const invalid of [null,{...config,fastId:2,slowId:1},{...config,fastId:1,slowId:1},
    {...config,quantity:0},{...config,quantity:1.5},{...config,quantity:'bad'}, {...config,slowId:99}]) {
    const result=run({config:invalid})
    assert.equal(result.available,false)
    assert.equal(result.action,null)
    assert.deepEqual(result.markers,[])
  }
})
test('missing, unavailable and mismatched server signals cannot become an action',()=>{
  for (const invalid of [null,{...signals,fast_id:99},{...signals,points:[]},
    {...signals,points:signals.points.map(point=>({...point,available:false}))}]) {
    assert.equal(run({signals:invalid}).available,false)
  }
  const untrusted = instances.map(item=>({...item,values:values([999,999,999,999])}))
  assert.equal(run({instances:untrusted}).fastValue,13,'browser does not recalculate or override Python values')
})
test('missing account cannot make a preview order actionable',()=>{
  assert.equal(run({account:null}).available,false)
})
