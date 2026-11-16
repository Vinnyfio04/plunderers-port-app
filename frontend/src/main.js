import { createApp, h, onBeforeUnmount, onMounted, ref } from 'vue'
import { createCandleChart } from './chartAdapter.js'
import { createHistoryCache, INITIAL_HISTORY_BARS } from './historyCache.js'
import brandLogo from './assets/treasure-map.png'
import './style.css'

const DEFAULT_SYMBOL = 'AAPL'
const TIMEFRAMES = [
  ['1m', '1 minute'],
  ['5m', '5 minutes'],
  ['15m', '15 minutes'],
  ['1h', 'Hourly'],
  ['1d', 'Daily'],
]
const EMPTY_REPLAY_MESSAGE = 'This selection has no recorded observations.'

function newRequestId() {
  return `paper-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function formatCandleTimestamp(timestamp) {
  const date = new Date(timestamp)
  return {
    date: new Intl.DateTimeFormat('en-US', {
      dateStyle: 'long',
      timeZone: 'UTC',
    }).format(date),
    time: `${new Intl.DateTimeFormat('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
      timeZone: 'UTC',
    }).format(date)} UTC`,
  }
}

function utcInputValue(timestamp) {
  return timestamp ? new Date(timestamp).toISOString().slice(0, 19) : ''
}

function utcRequestValue(value) {
  return value ? `${value}Z` : ''
}

function detailItem(label, value, testId) {
  return h('div', { class: 'detail-item' }, [
    h('dt', label),
    h('dd', { 'data-testid': testId }, String(value)),
  ])
}

function feedItem(label, value, testId) {
  return h('div', { class: 'feed-item' }, [
    h('span', label),
    h('strong', { 'data-testid': testId }, value),
  ])
}

function formatAge(seconds) {
  if (seconds === null) return 'No live observation yet'
  if (seconds < 1) return '<1 second'
  return `${Math.floor(seconds)} seconds`
}

function formatMoney(value) {
  if (value === null || value === undefined) return 'Unavailable'
  const amount = Number(value)
  return amount < 0 ? `-$${Math.abs(amount).toFixed(2)}` : `$${amount.toFixed(2)}`
}

createApp({
  setup() {
    const chartContainer = ref(null)
    const candles = ref([])
    const selectedCandle = ref(null)
    const mode = ref('live')
    const symbol = ref(DEFAULT_SYMBOL)
    const timeframe = ref('1m')
    const status = ref('Loading 1m candles…')
    const error = ref('')
    const source = ref('Yahoo Finance history')
    const historyLoading = ref(false)
    const historyMessage = ref('')
    const historyEarliest = ref(null)
    const historyPolicy = ref(null)
    const historyKind = ref('recorded')
    const marketState = ref(null)
    const historyFetch = ref(null)
    const liveCandleSource = ref(null)
    const lastLiveCandleTime = ref(null)
    const feedStatus = ref('connecting')
    const feedDetail = ref('')
    const backendSocketStatus = ref('connecting')
    const sourceAgeSeconds = ref(null)
    const completion = ref(null)
    const candleStatusByTime = ref({})
    const replaySelections = ref([])
    const watchlistError = ref('')
    const replayStart = ref('')
    const replayEnd = ref('')
    const replayObservationTime = ref(null)
    const replayReceiptTime = ref(null)
    const replayProgress = ref('Not started')
    const replayStoredCount = ref(null)
    const replaySelectionLoading = ref(false)
    const indicatorTypes = ref([])
    const indicators = ref([])
    const indicatorType = ref('sma')
    const indicatorName = ref('')
    const indicatorWindow = ref('2')
    const indicatorError = ref('')
    const indicatorNotice = ref('')
    const chartContextLoading = ref(true)
    const indicatorWindowDraft = ref({})
    const paperAccount = ref(null)
    const paperQuantity = ref('1')
    const paperRequestId = ref(newRequestId())
    const paperFixturePrice = ref('100')
    const paperValuationEventKey = ref(`fixture-candle-${Date.now()}`)
    const paperError = ref('')
    const paperNotice = ref('')
    const decisionSnapshot = ref(null)
    const decisionResult = ref(null)
    const decisionImage = ref('')
    const decisionError = ref('')
    const decisionLoading = ref(false)
    const savedDecisions = ref([])
    const voiceDecisionId = ref('')
    const voiceStatus = ref('Idle')
    const voiceError = ref('')
    const microphoneActive = ref(false)
    const voiceInputTranscript = ref('')
    const voiceOutputTranscript = ref('')
    const voiceAudio = ref(null)
    let voicePeer = null
    let voiceEvents = null
    let voiceMicrophone = null
    let voiceAbort = null
    let voiceCloseTimer = null
    let voiceReadyTimer = null
    let voiceGeneration = 0
    const automation = ref(null)
    const automationError = ref('')
    const automationSize = ref('1')
    const automationEvent = ref(null)
    const automationSeen = new Set()
    let automationTimer = null
    let chartAdapter = null
    let socket = null
    let requestGeneration = 0
    let sourceAgeBase = null
    let sourceAgeMeasuredAt = null
    let ageTimer = null
    let replayIndicatorGeneration = 0
    let reconnectTimer = null
    let reconnectDelay = 1000
    let nextBefore = null
    let olderLoading = false
    let lastWatermark = 0
    let followingLatest = true
    let indicatorMutationVersion = 0
    const historyCache = createHistoryCache()
    let historyRetryTimer = null
    let historyRetryDelay = 2000

    const chartBarBudget = () => historyPolicy.value?.bar_budget ?? 6000

    const loadEarliestHistory = async () => {
      if (mode.value!=='live' || !historyEarliest.value || olderLoading) return
      olderLoading = true
      const generation = requestGeneration
      try {
        const query = new URLSearchParams({symbol:symbol.value,timeframe:timeframe.value,oldest:'true',limit:'2000'})
        const response = await fetch(`/api/history?${query}`,{signal:AbortSignal.timeout(15000)})
        if (!response.ok) throw new Error('Earliest interval history could not be loaded')
        const page = await response.json()
        if (generation!==requestGeneration) return
        followingLatest = false
        nextBefore = page.next_before
        candles.value = page.candles
        candleStatusByTime.value = Object.fromEntries(page.status.map(s=>[s.timestamp,s]))
        selectedCandle.value = page.candles[0] ?? null
        chartAdapter?.setCandles(page.candles,false)
        status.value = `${page.candles.length} ${timeframe.value} candles · earliest available ${page.history_earliest?.slice(0,10) ?? 'unknown'} · UTC`
        if (page.candles.length) {
          const before = new Date(Date.parse(page.candles.at(-1).timestamp)+1000).toISOString()
          const response = await fetch(`/api/indicators?${new URLSearchParams({symbol:symbol.value,timeframe:timeframe.value,before})}`)
          if (!response.ok) throw new Error('Historical indicator values could not be loaded')
          const payload = await response.json()
          if (generation===requestGeneration) { indicators.value=payload.instances; chartAdapter?.setIndicators(indicators.value) }
        }
      } catch (failure) { if(generation===requestGeneration) error.value=failure.message }
      finally { olderLoading = false }
    }

    const loadOlder = async () => {
      if (mode.value !== 'live' || !nextBefore || olderLoading) return
      olderLoading = true
      const generation = requestGeneration
      try {
        const before = nextBefore
        const query = new URLSearchParams({symbol:symbol.value,timeframe:timeframe.value,before,limit:'2000'})
        const response = await fetch(`/api/history?${query}`)
        if (!response.ok) throw new Error('Earlier history could not be loaded')
        const page = await response.json()
        if (generation !== requestGeneration) return
        nextBefore = page.next_before
        const merged = new Map([...page.candles,...candles.value].map((c) => [c.timestamp,c]))
        const ordered = [...merged.values()].sort((a,b) => a.timestamp.localeCompare(b.timestamp))
        followingLatest = ordered.length <= chartBarBudget()
        candles.value = ordered.slice(0,chartBarBudget())
        candleStatusByTime.value = {...Object.fromEntries(page.status.map((s) => [s.timestamp,s])),...candleStatusByTime.value}
        chartAdapter?.setCandles(candles.value)
        const indicatorResponse = await fetch(`/api/indicators?${query}`)
        if (indicatorResponse.ok && generation === requestGeneration) {
          const previous = (await indicatorResponse.json()).instances
          const times = new Set(candles.value.map((c) => c.timestamp))
          indicators.value = indicators.value.map((item) => {
            const older = previous.find((p) => p.indicator_id === item.indicator_id)
            const values = new Map([...(older?.values ?? []),...item.values].map((point) => [point.timestamp,point]))
            return {...item,values:[...values.values()].filter((p) => times.has(p.timestamp)).sort((a,b) => a.timestamp.localeCompare(b.timestamp))}
          })
          chartAdapter?.setIndicators(indicators.value)
        }
      } catch (failure) { error.value = failure.message }
      finally { olderLoading = false }
    }

    const selectCandle = (timestamp) => {
      selectedCandle.value =
        candles.value.find((candle) => candle.timestamp === timestamp) ?? null
    }

    const resetChart = (history = [], candleStatus = []) => {
      candles.value = history
      candleStatusByTime.value = Object.fromEntries(
        candleStatus.map((item) => [item.timestamp, item]),
      )
      selectedCandle.value = history.length ? history[history.length - 1] : null
      if (chartAdapter) {
        chartAdapter.setCandles(history,'latest')
        chartAdapter.setIndicators(indicators.value)
        return
      }
      chartAdapter = createCandleChart(
        chartContainer.value,
        history,
        (candle) => {
          selectedCandle.value = candle
        },
        loadOlder,
      )
      chartAdapter.setIndicators(indicators.value)
    }

    const replaceOrAppendCandle = (candle) => {
      const index = candles.value.findIndex(
        (existing) => existing.timestamp === candle.timestamp,
      )
      const next = [...candles.value]
      if (index >= 0) next[index] = candle
      else {
        next.push(candle)
        next.sort((left, right) => left.timestamp.localeCompare(right.timestamp))
      }
      candles.value = next
      if (next.length > chartBarBudget()) {
        candles.value = next.slice(-chartBarBudget())
        chartAdapter?.setCandles(candles.value)
      }
      selectedCandle.value = candle
      chartAdapter?.updateCandle(candle)
    }

    const analyzeCandle = async (selected, automated = false) => {
      if (decisionLoading.value) {
        if (automated) throw new Error('Another chart analysis is already running.')
        return
      }
      decisionError.value = ''
      decisionResult.value = null
      decisionSnapshot.value = null
      decisionImage.value = ''
      decisionLoading.value = true
      try {
        if (chartContextLoading.value) throw new Error('Chart settings are loading. Wait for the indicator panel, then retry.')
        if (!selected) throw new Error('Select a candle before asking about the chart.')
        if (!candleStatusByTime.value[selected.timestamp]?.interval_ended) {
          throw new Error('Select a completed candle, then recapture the chart.')
        }
        if (!chartAdapter) throw new Error('The chart is unavailable; reload and recapture.')
        const frozenSymbol = symbol.value
        const frozenInterval = timeframe.value
        const frozenCutoff = selected.timestamp
        const frozenAdapter = chartAdapter
        const generation = requestGeneration
        const frozenCandles = candles.value
          .filter((candle) => candle.timestamp <= frozenCutoff && candleStatusByTime.value[candle.timestamp]?.interval_ended)
          .slice(-200)
          .map((candle) => ({ ...candle }))
        const snapshotResponse = await fetch('/api/decision-snapshots', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          signal: AbortSignal.timeout(15000),
          body: JSON.stringify({
            symbol: frozenSymbol,
            timeframe: frozenInterval,
            cutoff: frozenCutoff,
            candles: frozenCandles,
          }),
        })
        const snapshot = await snapshotResponse.json()
        if (!snapshotResponse.ok) {
          throw new Error(snapshot.detail || 'Decision snapshot could not be created.')
        }
        if (generation !== requestGeneration || frozenAdapter !== chartAdapter) {
          throw new Error('The chart changed before capture. Select a completed candle and try again.')
        }
        const imageDataUrl = await frozenAdapter.captureThrough(
          frozenCutoff,
          snapshot.indicators,
          snapshot.candles,
        )
        decisionSnapshot.value = snapshot
        decisionImage.value = imageDataUrl

        const decisionResponse = await fetch('/api/decisions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          signal: AbortSignal.timeout(75000),
          body: JSON.stringify({
            snapshot_id: snapshot.snapshot_id,
            symbol: frozenSymbol,
            timeframe: frozenInterval,
            cutoff: frozenCutoff,
            image_data_url: imageDataUrl,
          }),
        })
        const decision = await decisionResponse.json()
        if (!decisionResponse.ok) {
          throw new Error(decision.detail || 'Chart analysis failed; recapture the chart.')
        }
        decisionResult.value = decision
        voiceDecisionId.value = decision.decision_id
        loadSavedDecisions().catch((failure) => { voiceError.value = failure.message })
        return decision
      } catch (requestError) {
        decisionError.value = requestError.name === 'TimeoutError'
          ? 'Chart analysis timed out. Check the backend connection, then try again.' : requestError.message
        if (automated) throw requestError
      } finally {
        decisionLoading.value = false
      }
    }

    const askAboutChart = () => analyzeCandle(selectedCandle.value)

    const loadSavedDecisions = async () => {
      const response = await fetch(`/api/saved-decisions?symbol=${encodeURIComponent(symbol.value)}`)
      if (!response.ok) return
      savedDecisions.value = await response.json()
      if (!voiceDecisionId.value && savedDecisions.value.length) {
        voiceDecisionId.value = savedDecisions.value[0].decision_id
      }
    }

    const releaseVoice = () => {
      voiceGeneration += 1
      if (voiceCloseTimer !== null) window.clearTimeout(voiceCloseTimer)
      if (voiceReadyTimer !== null) window.clearTimeout(voiceReadyTimer)
      voiceCloseTimer = null
      voiceReadyTimer = null
      voiceAbort?.abort()
      voiceAbort = null
      const events = voiceEvents
      const peer = voicePeer
      const microphone = voiceMicrophone
      voiceEvents = null
      voicePeer = null
      voiceMicrophone = null
      microphone?.getTracks().forEach((track) => track.stop())
      events?.close()
      peer?.close()
      if (voiceAudio.value) {
        voiceAudio.value.pause()
        voiceAudio.value.srcObject = null
      }
      microphoneActive.value = false
    }

    const endVoice = () => {
      if (voiceEvents?.readyState === 'open' && voiceStatus.value === 'Connected') {
        voiceStatus.value = 'Ending…'
        voiceEvents.send(JSON.stringify({ type: 'session.close' }))
        voiceMicrophone?.getTracks().forEach((track) => track.stop())
        microphoneActive.value = false
        voiceCloseTimer = window.setTimeout(() => {
          voiceStatus.value = 'Ended; provider close confirmation timed out.'
          releaseVoice()
        }, 15000)
      } else {
        releaseVoice()
        voiceStatus.value = 'Ended'
      }
    }

    const startVoice = async () => {
      const decisionId = voiceDecisionId.value
      if (!decisionId) return
      releaseVoice()
      const generation = voiceGeneration
      voiceError.value = ''
      voiceInputTranscript.value = ''
      voiceOutputTranscript.value = ''
      voiceStatus.value = 'Requesting microphone…'
      try {
        if (!navigator.mediaDevices?.getUserMedia) throw new Error('Microphone access requires localhost or HTTPS.')
        const microphone = await navigator.mediaDevices.getUserMedia({ audio: true })
        if (generation !== voiceGeneration) {
          microphone.getTracks().forEach((track) => track.stop())
          return
        }
        voiceMicrophone = microphone
        microphoneActive.value = true
        const peer = new RTCPeerConnection()
        voicePeer = peer
        peer.addEventListener('track', (event) => {
          if (generation !== voiceGeneration || !voiceAudio.value) return
          voiceAudio.value.srcObject = new MediaStream([event.track])
          voiceAudio.value.play().catch(() => {
            voiceStatus.value = 'Connected; press play on the audio control.'
          })
        })
        peer.addEventListener('connectionstatechange', () => {
          if (generation !== voiceGeneration) return
          if (['failed', 'disconnected', 'closed'].includes(peer.connectionState)) {
            voiceStatus.value = 'Disconnected'
            releaseVoice()
          }
        })
        for (const track of microphone.getAudioTracks()) peer.addTrack(track, microphone)
        const events = peer.createDataChannel('oai-events')
        voiceEvents = events
        events.addEventListener('message', ({ data }) => {
          if (generation !== voiceGeneration) return
          let message
          try { message = JSON.parse(data) } catch { return }
          if (message.type === 'session.started') {
            if (voiceReadyTimer !== null) window.clearTimeout(voiceReadyTimer)
            voiceReadyTimer = null
            voiceStatus.value = 'Connected'
          }
          if (message.type === 'session.input_transcript.delta' && typeof message.delta === 'string') {
            voiceInputTranscript.value += message.delta
          }
          if (message.type === 'session.output_transcript.delta' && typeof message.delta === 'string') {
            voiceOutputTranscript.value += message.delta
          }
          if (message.type === 'session.closed') {
            voiceStatus.value = 'Ended'
            releaseVoice()
          }
        })
        events.addEventListener('close', () => {
          if (generation !== voiceGeneration) return
          voiceStatus.value = 'Disconnected'
          releaseVoice()
        })
        voiceStatus.value = 'Connecting…'
        const offer = await peer.createOffer()
        await peer.setLocalDescription(offer)
        if (peer.iceGatheringState !== 'complete') {
          await new Promise((resolve, reject) => {
            const timer = window.setTimeout(() => {
              peer.removeEventListener('icegatheringstatechange', check)
              reject(new Error('Timed out gathering WebRTC candidates.'))
            }, 10000)
            function check() {
              if (peer.iceGatheringState !== 'complete') return
              window.clearTimeout(timer)
              peer.removeEventListener('icegatheringstatechange', check)
              resolve()
            }
            peer.addEventListener('icegatheringstatechange', check)
            check()
          })
        }
        if (generation !== voiceGeneration) return
        voiceAbort = new AbortController()
        const response = await fetch('/api/voice-sessions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ decision_id: decisionId, offer_sdp: peer.localDescription?.sdp }),
          signal: voiceAbort.signal,
        })
        const result = await response.json()
        if (!response.ok) throw new Error(result.detail || 'Voice connection failed.')
        if (generation !== voiceGeneration) return
        await peer.setRemoteDescription({ type: 'answer', sdp: result.answer_sdp })
        if (voiceStatus.value !== 'Connected') {
          voiceReadyTimer = window.setTimeout(() => {
            if (generation !== voiceGeneration || voiceStatus.value === 'Connected') return
            voiceError.value = 'Voice session did not start before the timeout.'
            voiceStatus.value = 'Failed'
            releaseVoice()
          }, 20000)
        }
        // POST starts the session; session.started arrives on the event channel.
      } catch (error) {
        if (generation !== voiceGeneration) return
        voiceError.value = error.name === 'NotAllowedError'
          ? 'Microphone permission was denied. Allow microphone access and retry.'
          : error.message
        voiceStatus.value = 'Failed'
        releaseVoice()
      }
    }

    const loadAutomation = async () => {
      const query = new URLSearchParams({ symbol: symbol.value, timeframe: timeframe.value })
      const response = await fetch(`/api/paper-automation?${query}`)
      if (response.ok) {
        automation.value = await response.json()
        automationEvent.value = automation.value.events?.[0] ?? null
      }
    }

    const setAutomation = async (enabled) => {
      automationError.value = ''
      try {
        const response = await fetch('/api/paper-automation', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ symbol: symbol.value, timeframe: timeframe.value,
            enabled, order_size: Number(automationSize.value) }),
        })
        const result = await response.json()
        if (!response.ok) throw new Error(result.detail || 'Automation control failed.')
        automation.value = result
        if (enabled) {
          for (const [timestamp, state] of Object.entries(candleStatusByTime.value)) {
            if (state.interval_ended) automationSeen.add(`${symbol.value}|${timeframe.value}|${timestamp}`)
          }
        }
      } catch (error) { automationError.value = error.message }
    }

    const automateCompleted = async (candle) => {
      const config = automation.value
      if (!config?.enabled || mode.value !== 'live') return
      const key = `${symbol.value}|${timeframe.value}|${candle.timestamp}`
      if (automationSeen.has(key)) return
      automationSeen.add(key)
      const frozen = { symbol: symbol.value, timeframe: timeframe.value,
        cutoff: candle.timestamp, generation: config.generation }
      try {
        const claimResponse = await fetch('/api/paper-automation/claim', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(frozen),
        })
        const claim = await claimResponse.json()
        if (!claimResponse.ok) throw new Error(claim.detail || 'Candle claim failed.')
        if (!claim.claimed) {
          automationEvent.value = claim.event
          return
        }
        const decision = await analyzeCandle(candle, true)
        const response = await fetch('/api/paper-automation/execute', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...frozen, decision_id: decision.decision_id }),
        })
        const result = await response.json()
        if (!response.ok) throw new Error(result.detail || 'Automation submission failed.')
        automationEvent.value = result.event
        paperAccount.value = result.account
        await loadAutomation()
      } catch (error) {
        automationError.value = error.message
        const response = await fetch('/api/paper-automation/skip', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...frozen, reason: error.message }),
        })
        if (response.ok) automationEvent.value = (await response.json()).event
        await loadAutomation()
      }
    }

    const pollAutomation = async () => {
      if (!automation.value?.enabled || mode.value !== 'live') return
      const query = new URLSearchParams({ symbol: symbol.value, timeframe: timeframe.value })
      const response = await fetch(`/api/history?${query}`)
      if (!response.ok) return
      const history = await response.json()
      for (const candle of history.candles ?? []) {
        const state = history.status?.find((item) => item.timestamp === candle.timestamp)
        if (!state?.interval_ended) continue
        const key = `${symbol.value}|${timeframe.value}|${candle.timestamp}`
        if (!automationSeen.has(key)) {
          candleStatusByTime.value = { ...candleStatusByTime.value, [candle.timestamp]: state }
          replaceOrAppendCandle(candle)
          await loadIndicators()
          await automateCompleted(candle)
        }
      }
      await loadAutomation()
      await loadPaperAccount()
    }

    const connectCandleStream = (generation) => {
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer)
      reconnectTimer = null
      socket?.close()
      backendSocketStatus.value = 'connecting'
      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const url = new URL(`${protocol}://${window.location.host}/ws/candles`)
      url.searchParams.set('symbol', symbol.value)
      url.searchParams.set('timeframe', timeframe.value)
      url.searchParams.set('limit',String(INITIAL_HISTORY_BARS))
      const cached = historyCache.get(symbol.value,timeframe.value)
      if (cached?.stream_id) {
        url.searchParams.set('stream_id',cached.stream_id)
        for (const [name,field] of [['since','watermark'],['daily_since','daily_watermark'],['interval_since','interval_watermark']]) {
          url.searchParams.set(name,String(cached[field] ?? 0))
        }
      }
      const activeSocket = new WebSocket(url)
      socket = activeSocket
      let retryScheduled = false
      const retry = () => {
        if (retryScheduled || generation !== requestGeneration || socket !== activeSocket || mode.value !== 'live') return
        retryScheduled = true
        backendSocketStatus.value = 'disconnected'
        feedStatus.value = 'unavailable'
        reconnectTimer = window.setTimeout(() => {
          if (generation === requestGeneration && mode.value === 'live') connectCandleStream(generation)
        }, reconnectDelay)
        reconnectDelay = Math.min(30000,reconnectDelay*2)
      }
      // A failed proxy upgrade can leave CONNECTING open without delivering close.
      const connectionDeadline = window.setTimeout(() => {
        if (generation === requestGeneration && socket === activeSocket && activeSocket.readyState !== WebSocket.OPEN) {
          retry()
          activeSocket.close()
        }
      }, 5000)

      activeSocket.addEventListener('open', () => {
        window.clearTimeout(connectionDeadline)
        reconnectDelay = 1000
        if (generation === requestGeneration) backendSocketStatus.value = 'connected'
      })
      activeSocket.addEventListener('message', (event) => {
        if (generation !== requestGeneration) return
        const message = JSON.parse(event.data)
        if (message.symbol !== symbol.value || message.interval !== timeframe.value) return
        if (message.market) marketState.value = message.market
        if (message.history_fetch) historyFetch.value = message.history_fetch
        if (message.type === 'history') {
          historyCache.put(symbol.value,timeframe.value,message)
          historyEarliest.value = message.history_earliest ?? message.daily_earliest ?? null
          historyPolicy.value = message.history_policy ?? null
          nextBefore = message.next_before
          lastWatermark = message.watermark ?? 0
          candles.value = message.candles
          candleStatusByTime.value = Object.fromEntries(message.status.map((s) => [s.timestamp,s]))
          selectedCandle.value = candles.value.at(-1) ?? null
          completion.value = message.status.at(-1) ?? null
          source.value = message.source
          historyKind.value = message.data_kind ?? 'recorded'
          historyMessage.value = message.message ?? ''
          historyLoading.value = false
          status.value = candles.value.length ? `${candles.value.length} ${timeframe.value} candles · UTC` : 'Recent history unavailable · retrying'
          if (candles.value.length) error.value = ''
          chartAdapter?.setCandles(candles.value)
          for (const item of message.status) {
            if (item.interval_ended) automationSeen.add(`${symbol.value}|${timeframe.value}|${item.timestamp}`)
          }
          chartAdapter?.setIndicators(indicators.value)
          return
        }
        historyCache.update(symbol.value,timeframe.value,message)
        source.value = message.source
        feedStatus.value = message.feed_status
        feedDetail.value = message.detail ?? ''
        if (message.source_age_seconds !== null && message.source_age_seconds !== undefined) {
          sourceAgeBase = message.source_age_seconds
          sourceAgeMeasuredAt = Date.now()
          sourceAgeSeconds.value = sourceAgeBase
        }
        if (message.type === 'candle') {
          if (message.watermark && message.watermark < lastWatermark) return
          lastWatermark = message.watermark ?? lastWatermark
          if (!followingLatest && message.candle.timestamp > candles.value.at(-1)?.timestamp) return
          if (candles.value.length && message.candle.timestamp < candles.value[0].timestamp) return
          const priorLatest = candles.value.at(-1)?.timestamp
          liveCandleSource.value = message.source
          lastLiveCandleTime.value = message.candle.timestamp
          const wasEnded = candleStatusByTime.value[message.candle.timestamp]?.interval_ended
          completion.value = message.completion
          candleStatusByTime.value = {
            ...candleStatusByTime.value,
            [message.candle.timestamp]: message.completion,
          }
          replaceOrAppendCandle(message.candle)
          if (message.completion?.interval_ended && !wasEnded && (!priorLatest || message.candle.timestamp >= priorLatest)
              && (!message.market || message.market.status === 'open')) automateCompleted(message.candle)
          status.value = `${candles.value.length} ${timeframe.value} candles · UTC`
          loadIndicators(generation).catch((failure) => { indicatorError.value = failure.message })
          loadPaperAccount()
        }
      })
      activeSocket.addEventListener('error', () => {
        window.clearTimeout(connectionDeadline)
        retry()
        activeSocket.close()
      })
      activeSocket.addEventListener('close', () => {
        window.clearTimeout(connectionDeadline)
        retry()
      })
    }

    const loadIndicators = async (generation = requestGeneration) => {
      const version = indicatorMutationVersion
      const query = new URLSearchParams({
        symbol: symbol.value,
        timeframe: timeframe.value,
        limit:String(Math.min(2000,Math.max(INITIAL_HISTORY_BARS,candles.value.length))),
      })
      const [typesResponse, instancesResponse] = await Promise.all([
        fetch('/api/indicator-types'),
        fetch(`/api/indicators?${query}`),
      ])
      if (!typesResponse.ok || !instancesResponse.ok) {
        throw new Error('Indicator configuration could not be loaded')
      }
      const typesPayload = await typesResponse.json()
      const instancesPayload = await instancesResponse.json()
      if (generation !== requestGeneration || version !== indicatorMutationVersion) return
      indicatorTypes.value = typesPayload.types
      indicators.value = instancesPayload.instances
      indicatorWindowDraft.value = Object.fromEntries(
        indicators.value.map((instance) => [instance.indicator_id, String(instance.settings.window)]),
      )
      chartAdapter?.setIndicators(indicators.value)
    }

    const evaluateReplayIndicators = async () => {
      if (mode.value !== 'replay') return
      const generation = ++replayIndicatorGeneration
      const response = await fetch('/api/indicators/evaluate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: symbol.value, timeframe: timeframe.value,
          candles: candles.value, status: Object.values(candleStatusByTime.value) }),
      })
      const result = await response.json()
      if (!response.ok) throw new Error(result.detail || 'Replay indicators could not be calculated.')
      if (generation !== replayIndicatorGeneration || mode.value !== 'replay') return
      indicators.value = result.instances
      chartAdapter?.setIndicators(indicators.value)
    }

    const createIndicator = async (event) => {
      indicatorMutationVersion += 1
      event.preventDefault()
      indicatorError.value = ''
      indicatorNotice.value = ''
      const windowSize = Number(indicatorWindow.value)
      try {
        const response = await fetch('/api/indicators', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            symbol: symbol.value,
            timeframe: timeframe.value,
            type: indicatorType.value,
            name: indicatorName.value,
            settings: { window: windowSize },
          }),
        })
        const payload = await response.json()
        if (!response.ok) {
          throw new Error(payload.detail || 'Indicator could not be created')
        }
        indicators.value = payload.instances
        chartAdapter?.setIndicators(indicators.value)
        indicatorWindowDraft.value = Object.fromEntries(
          indicators.value.map((instance) => [instance.indicator_id, String(instance.settings.window)]),
        )
        if (mode.value === 'replay') await evaluateReplayIndicators()
        indicatorNotice.value = `${payload.created.name} saved for ${timeframe.value}.`
        indicatorName.value = ''
      } catch (requestError) {
        indicatorError.value = requestError.message
      }
    }

    const updateIndicator = async (instance) => {
      indicatorMutationVersion += 1
      indicatorError.value = ''
      indicatorNotice.value = ''
      try {
        const response = await fetch(`/api/indicators/${instance.indicator_id}`, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ settings: { window: Number(indicatorWindowDraft.value[instance.indicator_id]) } }),
        })
        const result = await response.json()
        if (!response.ok) throw new Error(result.detail || 'Indicator window could not be changed.')
        indicators.value = result.instances
        if (mode.value === 'replay') await evaluateReplayIndicators()
        else chartAdapter?.setIndicators(indicators.value)
        indicatorNotice.value = `${instance.name} window updated.`
      } catch (failure) { indicatorError.value = failure.message }
    }

    const loadPaperAccount = async () => {
      try {
        const response = await fetch(`/api/paper-account?symbol=${encodeURIComponent(symbol.value)}`)
        if (!response.ok) throw new Error('Paper account could not be loaded')
        paperAccount.value = await response.json()
      } catch (requestError) {
        paperError.value = requestError.message
      }
    }

    const submitPaperAction = async (action) => {
      paperError.value = ''
      paperNotice.value = ''
      try {
        const response = await fetch('/api/paper-orders', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            request_id: paperRequestId.value,
            symbol: symbol.value,
            action,
            quantity: Number(paperQuantity.value),
          }),
        })
        const payload = await response.json()
        if (!response.ok) throw new Error(payload.detail || 'Paper action failed')
        paperAccount.value = payload.account
        paperNotice.value = payload.result.message
      } catch (requestError) {
        paperError.value = requestError.message
      }
    }

    const supplyPaperPrice = async () => {
      paperError.value = ''
      paperNotice.value = ''
      try {
        const response = await fetch('/api/paper-fixture-price', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            symbol: symbol.value,
            price: Number(paperFixturePrice.value),
          }),
        })
        const payload = await response.json()
        if (!response.ok) throw new Error(payload.detail || 'Fixture price failed')
        paperAccount.value = payload.account
        paperNotice.value = `${payload.source}: $${Number(paperFixturePrice.value).toFixed(2)} arrived.`
      } catch (requestError) {
        paperError.value = requestError.message
      }
    }

    const supplyPaperValuation = async () => {
      paperError.value = ''
      paperNotice.value = ''
      try {
        const response = await fetch('/api/paper-fixture-valuation', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            symbol: symbol.value,
            price: Number(paperFixturePrice.value),
            event_key: paperValuationEventKey.value,
          }),
        })
        const payload = await response.json()
        if (!response.ok) throw new Error(payload.detail || 'Fixture valuation failed')
        paperAccount.value = payload.account
        paperNotice.value = payload.pnl_row
          ? `${payload.source}: ${formatMoney(payload.pnl_row.price)} recorded.`
          : 'No P&L row was recorded because there is no open position.'
        paperValuationEventKey.value = `fixture-candle-${Date.now()}`
      } catch (requestError) {
        paperError.value = requestError.message
      }
    }

    const loadDashboard = async (nextTimeframe) => {
      if (historyRetryTimer !== null) window.clearTimeout(historyRetryTimer)
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer)
      socket?.close()
      socket = null
      followingLatest = true
      const generation = ++requestGeneration
      mode.value = 'live'
      timeframe.value = nextTimeframe
      symbol.value = DEFAULT_SYMBOL
      error.value = ''
      status.value = `Loading ${nextTimeframe} candles…`
      feedStatus.value = 'connecting'
      feedDetail.value = ''
      source.value = 'Yahoo Finance history'
      historyLoading.value = true
      chartContextLoading.value = true
      historyMessage.value = ''
      liveCandleSource.value = null
      lastLiveCandleTime.value = null
      replayObservationTime.value = null
      sourceAgeBase = null
      sourceAgeMeasuredAt = null
      sourceAgeSeconds.value = null
      historyCache.cancelPrefetch()
      const cached = historyCache.get(symbol.value,nextTimeframe)
      nextBefore = cached?.next_before ?? null
      historyEarliest.value = cached?.history_earliest ?? cached?.daily_earliest ?? null
      historyPolicy.value = cached?.history_policy ?? null
      completion.value = cached?.status.at(-1) ?? null
      indicators.value = []
      resetChart(cached?.candles ?? [], cached?.status ?? [])
      if (cached?.candles.length) {
        status.value = `${cached.candles.length} cached ${nextTimeframe} candles · refreshing · UTC`
        source.value = cached.source ?? 'Recorded SQLite history'
        historyKind.value = cached.data_kind ?? 'recorded'
        marketState.value = cached.market ?? null
        historyFetch.value = cached.history_fetch ?? null
        historyMessage.value = 'Showing cached history while checking the latest saved candles.'
        if (cached.latest_source_time) {
          sourceAgeBase = Math.max(0,(Date.now()-Date.parse(cached.latest_source_time))/1000)
          sourceAgeMeasuredAt = Date.now()
          sourceAgeSeconds.value = sourceAgeBase
        }
      }

      try {
        const historyResponse = await historyCache.load(symbol.value,nextTimeframe)
        if (generation !== requestGeneration) return
        const history = historyResponse.candles
        historyEarliest.value = historyResponse.history_earliest ?? historyResponse.daily_earliest ?? null
        historyPolicy.value = historyResponse.history_policy ?? null
        nextBefore = historyResponse.next_before
        lastWatermark = historyResponse.watermark ?? 0
        if (!Array.isArray(history)) throw new Error('Invalid candle history response')
        historyRetryDelay = 2000
        historyMessage.value = historyResponse.message ?? ''
        historyKind.value = historyResponse.data_kind ?? 'test'
        marketState.value = historyResponse.market ?? null
        historyFetch.value = historyResponse.history_fetch ?? null
        source.value = historyResponse.source ?? 'TEST DATA — configured CSV fixture'
        feedDetail.value = historyResponse.volume_note ?? 'Explicit test fixture; not live market history.'
        if (historyResponse.latest_source_time) {
          sourceAgeBase = Math.max(0, (Date.now() - Date.parse(historyResponse.latest_source_time)) / 1000)
          sourceAgeMeasuredAt = Date.now()
          sourceAgeSeconds.value = sourceAgeBase
        }
        completion.value = historyResponse.status[historyResponse.status.length - 1]
        resetChart(history, historyResponse.status)
        for (const item of historyResponse.status) {
          if (item.interval_ended) automationSeen.add(`${symbol.value}|${timeframe.value}|${item.timestamp}`)
        }
        status.value = history.length ? `${history.length} ${historyResponse.timeframe} candles · UTC`
          : 'No recorded candles · waiting for feed'
        if (historyResponse.live_feed_enabled === false) {
          socket?.close()
          backendSocketStatus.value = 'disconnected'
          feedStatus.value = 'disabled'
        } else connectCandleStream(generation)
        historyCache.prefetch(symbol.value,TIMEFRAMES.map(([value])=>value).filter(value=>value!==nextTimeframe))
        if (historyResponse.daily_download_pending || historyResponse.interval_download_pending || historyResponse.minute_download_pending) {
          historyMessage.value = `Loading Yahoo ${timeframe.value} history; saved candles remain available.`
          if (!history.length) historyRetryTimer = window.setTimeout(()=>{
            if (generation===requestGeneration && mode.value==='live') loadDashboard(nextTimeframe)
          },4000)
        }
        // Supporting panels cannot block a usable market chart or its live socket.
        loadIndicators(generation)
          .catch((failure) => { if (generation === requestGeneration) indicatorError.value = `Indicator configuration could not be loaded: ${failure.message}` })
          .finally(() => { if (generation === requestGeneration) chartContextLoading.value = false })
        loadPaperAccount().catch((failure) => { paperError.value = failure.message })
        loadAutomation().catch((failure) => { automationError.value = failure.message })
      } catch (requestError) {
        if (generation === requestGeneration) {
          error.value = `${requestError.message}. Retrying recent history; check that FastAPI is running.`
          status.value = candles.value.length ? `${candles.value.length} saved candles · retrying history` : 'Recent history unavailable · retrying'
          connectCandleStream(generation)
          historyRetryTimer = window.setTimeout(() => {
            if (generation === requestGeneration && mode.value === 'live') loadDashboard(nextTimeframe)
          }, historyRetryDelay)
          historyRetryDelay = Math.min(30000,historyRetryDelay*2)
        }
      } finally {
        if (generation === requestGeneration) historyLoading.value = false
      }
    }

    const applyReplaySelection = (nextSymbol) => {
      symbol.value = nextSymbol
      const selection = replaySelections.value.find((item) => item.ticker === nextSymbol)
      if (!selection) return
      replayStart.value = utcInputValue(selection.first_source_time)
      replayEnd.value = utcInputValue(
        new Date(new Date(selection.last_source_time).getTime() + 1000).toISOString(),
      )
      replayStoredCount.value = selection.observations
    }

    const loadWatchlist = async () => {
      try {
        const response = await fetch('/api/replay/selections')
        if (!response.ok) throw new Error('Recorded symbols are unavailable.')
        replaySelections.value = (await response.json()).selections
        watchlistError.value = ''
      } catch (requestError) {
        watchlistError.value = requestError.message
      }
    }

    const loadReplaySelections = async (preferredSymbol = null) => {
      historyCache.cancelPrefetch()
      chartContextLoading.value = true
      replaySelectionLoading.value = true
      const generation = ++requestGeneration
      socket?.close()
      mode.value = 'replay'
      error.value = ''
      source.value = 'Recorded SQLite session'
      feedStatus.value = 'disconnected'
      backendSocketStatus.value = 'disconnected'
      sourceAgeSeconds.value = null
      replayObservationTime.value = null
      replayReceiptTime.value = null
      replayProgress.value = 'Not started'
      status.value = 'Loading recorded sessions…'
      resetChart([])
      indicators.value = []
      try {
        const response = await fetch('/api/replay/selections')
        if (!response.ok) throw new Error(`Replay selections failed with status ${response.status}`)
        const payload = await response.json()
        if (generation !== requestGeneration) return
        replaySelections.value = payload.selections
        if (!payload.selections.length) {
          error.value = EMPTY_REPLAY_MESSAGE
          status.value = 'No replay data'
          return
        }
        applyReplaySelection(
          payload.selections.find((item) => item.ticker === preferredSymbol)?.ticker
            ?? payload.selections[0].ticker,
        )
        await loadIndicators(generation)
        status.value = 'Choose a saved range, then start Replay'
      } catch (requestError) {
        if (generation === requestGeneration) {
          error.value = requestError.message
          status.value = 'Replay unavailable'
        }
      } finally {
        if (generation === requestGeneration) { replaySelectionLoading.value = false; chartContextLoading.value = false }
      }
    }

    const startReplay = () => {
      const generation = ++requestGeneration
      socket?.close()
      error.value = ''
      source.value = 'Recorded SQLite session'
      feedStatus.value = 'disconnected'
      feedDetail.value = 'Replay is read-only; Yahoo live feed is not used.'
      backendSocketStatus.value = 'connecting'
      replayObservationTime.value = null
      replayReceiptTime.value = null
      replayProgress.value = 'Starting'
      completion.value = null
      resetChart([])

      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const url = new URL(`${protocol}://${window.location.host}/ws/replay`)
      url.searchParams.set('symbol', symbol.value)
      url.searchParams.set('timeframe', timeframe.value)
      url.searchParams.set('start', utcRequestValue(replayStart.value))
      url.searchParams.set('end', utcRequestValue(replayEnd.value))
      url.searchParams.set('speed', '100')
      const activeSocket = new WebSocket(url)
      socket = activeSocket

      activeSocket.addEventListener('open', () => {
        if (generation === requestGeneration) backendSocketStatus.value = 'connected'
      })
      activeSocket.addEventListener('message', (event) => {
        if (generation !== requestGeneration) return
        const message = JSON.parse(event.data)
        if (message.type === 'replay_started') {
          status.value = `Replay started · ${message.total} recorded arrivals`
          return
        }
        if (message.type === 'replay_empty') {
          error.value = message.message || EMPTY_REPLAY_MESSAGE
          status.value = 'No replay data'
          replayProgress.value = 'Empty selection'
          return
        }
        if (message.type === 'replay_error') {
          error.value = message.message
          status.value = 'Replay failed'
          return
        }
        if (message.type === 'replay_observation') {
          replayObservationTime.value = message.replay_observation_time
          replayReceiptTime.value = message.replay_receipt_time
          replayProgress.value = `${message.sequence} of ${message.total}`
          for (const update of message.updates) {
            completion.value = update.completion
            candleStatusByTime.value = {
              ...candleStatusByTime.value,
              [update.candle.timestamp]: update.completion,
            }
            replaceOrAppendCandle(update.candle)
          }
          status.value = `Replay ${message.sequence} of ${message.total}`
          evaluateReplayIndicators().catch((failure) => { indicatorError.value = failure.message })
          loadPaperAccount()
          return
        }
        if (message.type === 'replay_complete') {
          replayStoredCount.value = message.stored_observation_count_after
          status.value = `Replay complete · ${candles.value.length} ${timeframe.value} candles`
          replayProgress.value = 'Complete'
          feedDetail.value = `Read-only check: ${message.stored_observation_count_before} observations before, ${message.stored_observation_count_after} after.`
          evaluateReplayIndicators().catch((failure) => { indicatorError.value = failure.message })
        }
      })
      activeSocket.addEventListener('error', () => {
        if (generation === requestGeneration) backendSocketStatus.value = 'error'
      })
      activeSocket.addEventListener('close', () => {
        if (generation === requestGeneration) backendSocketStatus.value = 'disconnected'
      })
    }

    const changeTimeframe = (nextTimeframe) => {
      timeframe.value = nextTimeframe
      if (mode.value === 'replay') startReplay()
      else loadDashboard(nextTimeframe)
    }

    onMounted(() => {
      loadDashboard('1m')
      loadWatchlist()
      loadSavedDecisions().catch((failure) => { voiceError.value = failure.message })
      ageTimer = window.setInterval(() => {
        if (sourceAgeBase !== null && sourceAgeMeasuredAt !== null) {
          sourceAgeSeconds.value = sourceAgeBase + (Date.now() - sourceAgeMeasuredAt) / 1000
        }
      }, 1000)
      automationTimer = window.setInterval(() => { pollAutomation().catch((error) => { automationError.value = error.message }) }, 5000)
    })

    onBeforeUnmount(() => {
      historyCache.dispose()
      if (historyRetryTimer !== null) window.clearTimeout(historyRetryTimer)
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer)
      releaseVoice()
      requestGeneration += 1
      socket?.close()
      chartAdapter?.destroy()
      if (ageTimer !== null) window.clearInterval(ageTimer)
      if (automationTimer !== null) window.clearInterval(automationTimer)
    })

    return () => {
      const selected = selectedCandle.value
      const displayTime = selected ? formatCandleTimestamp(selected.timestamp) : null
      const inspectedCompletion = selected ? candleStatusByTime.value[selected.timestamp] : completion.value
      const candleState = inspectedCompletion
        ? inspectedCompletion.interval_ended
          ? inspectedCompletion.coverage_complete
            ? 'Complete'
            : 'Ended · partial coverage'
          : 'Still forming'
        : 'Waiting for candle status'
      const replayTime = replayObservationTime.value
        ? `${formatCandleTimestamp(replayObservationTime.value).date} ${formatCandleTimestamp(replayObservationTime.value).time}`
        : 'Waiting for Replay'
      const latestCandleTime = candles.value.at(-1)?.timestamp
      const latestCandleLabel = latestCandleTime
        ? `${formatCandleTimestamp(latestCandleTime).date} ${formatCandleTimestamp(latestCandleTime).time}`
        : 'Unavailable'
      const selectedIndicatorValues = selected
        ? indicators.value.map((instance) => ({
            ...instance,
            selectedValue: instance.values.find(
              (point) => point.timestamp === selected.timestamp,
            )?.value ?? null,
          }))
        : []
      const decisionAnswers = Object.fromEntries(
        (decisionResult.value?.answers ?? []).map((answer) => [answer.name, answer.choice]),
      )
      const selectedVoiceDecision = savedDecisions.value.find(
        (item) => item.decision_id === voiceDecisionId.value,
      )

      const indicatorPanel = h('section', { class: 'indicator-panel', 'aria-labelledby': 'indicator-title' }, [
            h('div', { class: 'indicator-heading' }, [
              h('div', [
                h('p', { class: 'eyebrow' }, 'Python indicators'),
                h('h2', { id: 'indicator-title' }, 'Configured indicators'),
              ]),
              h('p', `${indicators.value.length} saved for ${symbol.value} ${timeframe.value}`),
            ]),
            h('form', { class: 'indicator-form', onSubmit: createIndicator }, [
              h('label', [
                h('span', 'Indicator type'),
                h('select', {
                  'aria-label': 'Indicator type',
                  value: indicatorType.value,
                  onChange: (event) => { indicatorType.value = event.target.value },
                }, indicatorTypes.value.map((item) =>
                  h('option', { value: item.type }, item.label),
                )),
              ]),
              h('label', [
                h('span', 'Indicator name'),
                h('input', {
                  'aria-label': 'Indicator name',
                  required: true,
                  maxlength: '80',
                  value: indicatorName.value,
                  onInput: (event) => { indicatorName.value = event.target.value },
                }),
              ]),
              h('label', [
                h('span', 'Window'),
                h('input', {
                  'aria-label': 'Indicator window',
                  type: 'number',
                  step: '1',
                  min: '0',
                  required: true,
                  value: indicatorWindow.value,
                  onInput: (event) => { indicatorWindow.value = event.target.value },
                }),
              ]),
              h('button', { class: 'replay-button', type: 'submit', disabled: chartContextLoading.value }, 'Add indicator'),
            ]),
            indicatorError.value
              ? h('p', { class: 'error', role: 'alert', 'data-testid': 'indicator-error' }, indicatorError.value)
              : null,
            indicatorNotice.value
              ? h('p', { class: 'indicator-notice', 'aria-live': 'polite' }, indicatorNotice.value)
              : null,
            h('div', { class: 'indicator-list' }, indicators.value.map((instance) => {
              const definition = indicatorTypes.value.find((item) => item.type === instance.type)
              return h('article', { class: 'indicator-card' }, [
                h('strong', instance.name),
                h('span', `${definition?.label ?? instance.type} · window ${instance.settings.window}`),
                h('small', definition?.description ?? ''),
                h('label', [
                  'Change window ',
                  h('input', { type: 'number', min: '1', step: '1',
                    'aria-label': `${instance.name} window`,
                    value: indicatorWindowDraft.value[instance.indicator_id] ?? String(instance.settings.window),
                    onInput: (event) => { indicatorWindowDraft.value = {
                      ...indicatorWindowDraft.value, [instance.indicator_id]: event.target.value,
                    } },
                  }),
                ]),
                h('button', { type: 'button', class: 'replay-button',
                  onClick: () => updateIndicator(instance) }, `Update ${instance.name}`),
              ])
            })),
          ])

      const account = paperAccount.value
      const paperPanel = h('section', { class: 'paper-panel', 'aria-labelledby': 'paper-title' }, [
        h('div', { class: 'paper-heading' }, [
          h('div', [
            h('p', { class: 'eyebrow' }, 'Long-only simulation'),
            h('h2', { id: 'paper-title' }, 'Paper account'),
          ]),
          h('p', account?.fill_rule ?? 'Loading paper account…'),
        ]),
        h('div', { class: 'account-summary' }, [
          detailItem('Cash balance', account ? `$${account.cash.toFixed(2)}` : 'Loading', 'paper-cash'),
          detailItem('Shares held', account?.shares ?? 'Loading', 'paper-shares'),
          detailItem('Average cost', account ? formatMoney(account.average_cost) : 'Loading', 'paper-average-cost'),
          detailItem('Realized P&L', account ? formatMoney(account.valuation?.realized) : 'Loading', 'paper-realized'),
          detailItem('Unrealized P&L', account ? formatMoney(account.valuation?.unrealized) : 'Loading', 'paper-unrealized'),
          detailItem('Total P&L', account ? formatMoney(account.valuation?.total_pnl) : 'Loading', 'paper-total-pnl'),
        ]),
        account && !account.valuation?.valuation_available
          ? h('p', { class: 'valuation-unavailable', 'data-testid': 'valuation-unavailable' },
              account.valuation?.message ?? 'No usable valuation price is available for the open position.')
          : null,
        h('div', { class: 'automation-box' }, [
          h('div', { class: 'section-subheading' }, [
            h('h3', 'Paper automation'),
            h('span', { class: automation.value?.enabled ? 'state-badge state-on' : 'state-badge' },
              automation.value?.enabled ? 'Running' : 'Stopped'),
          ]),
          h('p', 'Approved decisions can create pending paper orders for the next observed price.'),
          h('label', { class: 'compact-field' }, [
            'Order size (whole shares)',
            h('input', { type: 'number', min: '1', step: '1', value: automationSize.value,
              'aria-label': 'Automation order size',
              onInput: (event) => { automationSize.value = event.target.value } }),
          ]),
          h('div', { class: 'paper-actions' }, [
            h('button', { type: 'button', disabled: automation?.value?.enabled || mode.value !== 'live',
              onClick: () => setAutomation(true) }, 'Start paper automation'),
            h('button', { type: 'button', disabled: !automation?.value?.enabled,
              onClick: () => setAutomation(true) }, 'Update order size'),
            h('button', { type: 'button', disabled: !automation?.value?.enabled,
              onClick: () => setAutomation(false) }, 'Stop paper automation'),
          ]),
          h('p', `Account ${automation.value?.account_id ?? 1} · ${symbol.value} ${timeframe.value}`),
          automationError.value ? h('p', { class: 'error', role: 'alert' }, automationError.value) : null,
          automationEvent.value ? h('div', { class: 'automation-trace', 'data-testid': 'automation-trace' }, [
            h('p', `Candle: ${automationEvent.value.candle_utc} · decision: ${automationEvent.value.decision_id ?? 'analysis failed'} · ${automationEvent.value.status}`),
            h('p', automationEvent.value.reason ?? `Paper order: ${automationEvent.value.order_id ?? 'none'}`),
            automationEvent.value.order_id ? h('p', `Fill: ${paperAccount.value?.orders?.find((order) => order.order_id === automationEvent.value.order_id)?.fill?.fill_id ?? 'pending'} · cash: ${paperAccount.value?.cash ?? 'loading'} · shares: ${paperAccount.value?.shares ?? 'loading'}`) : null,
          ]) : null,
        ]),
        h('div', { class: 'paper-controls' }, [
          h('label', [
            h('span', 'Request ID'),
            h('input', {
              'aria-label': 'Paper request ID',
              value: paperRequestId.value,
              onInput: (event) => { paperRequestId.value = event.target.value },
            }),
          ]),
          h('button', {
            class: 'secondary-button',
            type: 'button',
            onClick: () => { paperRequestId.value = newRequestId() },
          }, 'New request ID'),
          h('label', [
            h('span', 'Whole shares'),
            h('input', {
              'aria-label': 'Paper share quantity',
              type: 'number',
              step: '1',
              value: paperQuantity.value,
              onInput: (event) => { paperQuantity.value = event.target.value },
            }),
          ]),
          h('div', { class: 'paper-actions' }, [
            h('button', { type: 'button', onClick: () => submitPaperAction('buy') }, 'Buy'),
            h('button', { type: 'button', onClick: () => submitPaperAction('sell') }, 'Sell'),
            h('button', { type: 'button', onClick: () => submitPaperAction('close') }, 'Close position'),
            h('button', { type: 'button', onClick: () => submitPaperAction('hold') }, 'Hold'),
            h('button', { type: 'button', onClick: () => submitPaperAction('wait') }, 'Wait'),
          ]),
        ]),
        account?.fixture_enabled
          ? h('div', { class: 'fixture-price' }, [
              h('strong', 'TEST DATA — paper account browser fixture'),
              h('label', [
                h('span', 'Next observed price'),
                h('input', {
                  'aria-label': 'Next observed price',
                  type: 'number',
                  step: '0.01',
                  value: paperFixturePrice.value,
                  onInput: (event) => { paperFixturePrice.value = event.target.value },
                }),
              ]),
              h('div', { class: 'paper-actions' }, [
                h('button', { type: 'button', onClick: supplyPaperPrice }, 'Supply observed price'),
                h('button', { type: 'button', onClick: supplyPaperValuation }, 'Value at completed candle'),
              ]),
            ])
          : null,
        paperError.value
          ? h('p', { class: 'error', role: 'alert', 'data-testid': 'paper-error' }, paperError.value)
          : null,
        paperNotice.value
          ? h('p', { class: 'indicator-notice', 'aria-live': 'polite' }, paperNotice.value)
          : null,
        h('div', { class: 'order-history' }, [
          h('h3', 'Order history'),
          account?.orders.length
            ? h('div', { class: 'order-list' }, account.orders.map((order) =>
                h('article', { class: `order-card order-${order.status}` }, [
                  h('strong', `#${order.order_id} ${order.side.toUpperCase()} ${order.quantity ?? 'invalid'} ${order.symbol}`),
                  h('span', `${order.status} · request ${order.request_id}`),
                  order.decision_id ? h('small', `Decision ${order.decision_id}`) : null,
                  h('small', `Submitted ${order.submission_time}`),
                  order.fill
                    ? h('small', `Filled $${order.fill.price.toFixed(2)} · observation ${order.fill.observation_id} · ${order.fill.execution_time}`)
                    : null,
                  order.rejection_reason ? h('small', order.rejection_reason) : null,
                ]),
              ))
            : h('p', 'No orders yet.'),
        ]),
        h('div', { class: 'pnl-history' }, [
          h('h3', 'Profit and loss history'),
          account?.pnl_history.length
            ? h('div', { class: 'table-scroll' }, [
                h('table', { 'data-testid': 'pnl-history-table' }, [
                  h('thead', [h('tr', [
                    'Time', 'Event', 'Price / source', 'Cash', 'Shares',
                    'Avg cost', 'Realized', 'Unrealized', 'Total P&L',
                  ].map((label) => h('th', { scope: 'col' }, label)))]),
                  h('tbody', account.pnl_history.map((row) => h('tr', {
                    'data-testid': `pnl-row-${row.pnl_id}`,
                  }, [
                    h('td', row.timestamp),
                    h('td', row.event_type === 'fill'
                      ? `Fill #${row.fill_id}${row.decision_id ? ` · ${row.decision_id}` : ''}`
                      : 'Completed candle'),
                    h('td', [h('strong', formatMoney(row.price)), h('small', row.valuation_source)]),
                    h('td', formatMoney(row.cash)),
                    h('td', String(row.shares)),
                    h('td', formatMoney(row.average_cost)),
                    h('td', formatMoney(row.realized)),
                    h('td', formatMoney(row.unrealized)),
                    h('td', formatMoney(row.total_pnl)),
                  ]))),
                ]),
              ])
            : h('p', 'No P&L events yet.'),
        ]),
      ])

      const replayControls = mode.value === 'replay'
        ? h('section', { class: 'replay-controls', 'aria-label': 'Replay selection' }, [
            h('div', { class: 'replay-label' }, [
              h('strong', 'Replay'),
              h('span', 'Read only · live Yahoo feed disconnected'),
            ]),
            h('label', { class: 'timeframe-picker' }, [
              h('span', 'Saved symbol'),
              h('select', {
                'aria-label': 'Select saved symbol',
                value: symbol.value,
                onChange: (event) => applyReplaySelection(event.target.value),
              }, replaySelections.value.map((item) => h('option', { value: item.ticker }, item.ticker))),
            ]),
            h('label', { class: 'timeframe-picker' }, [
              h('span', 'Start UTC'),
              h('input', {
                'aria-label': 'Replay start UTC',
                type: 'datetime-local',
                step: '1',
                value: replayStart.value,
                onInput: (event) => { replayStart.value = event.target.value },
              }),
            ]),
            h('label', { class: 'timeframe-picker' }, [
              h('span', 'End UTC (exclusive)'),
              h('input', {
                'aria-label': 'Replay end UTC',
                type: 'datetime-local',
                step: '1',
                value: replayEnd.value,
                onInput: (event) => { replayEnd.value = event.target.value },
              }),
            ]),
            h('button', { class: 'replay-button', type: 'button', onClick: startReplay,
              disabled: replaySelectionLoading.value || !replayStart.value || !replayEnd.value }, 'Start Replay'),
          ])
        : null

      const decisionPanel = h('section', {
        class: 'decision-panel',
        'aria-labelledby': 'decision-title',
      }, [
        h('div', { class: 'decision-heading' }, [
          h('div', [
            h('p', { class: 'eyebrow' }, 'Advisory analysis only'),
            h('h2', { id: 'decision-title' }, 'Ask about chart'),
          ]),
          h('button', {
            class: 'replay-button',
            type: 'button',
            disabled: decisionLoading.value || chartContextLoading.value || !selected,
            onClick: askAboutChart,
            'data-testid': 'ask-about-chart',
          }, decisionLoading.value ? 'Analyzing…' : 'Ask about chart'),
        ]),
        h('p', 'Analyze up to 200 completed candles through the selected cutoff. The frozen preview shows exactly what the agents see. Analysis does not place an order.'),
        h('p', `Paper automation: ${automation.value?.enabled ? 'running' : 'stopped'} · account ${automation.value?.account_id ?? 1} · ${symbol.value} ${timeframe.value}`),
        decisionError.value
          ? h('p', { class: 'error', role: 'alert', 'data-testid': 'decision-error' }, decisionError.value)
          : null,
        decisionSnapshot.value && decisionImage.value
          ? h('div', { class: 'decision-capture' }, [
              h('img', {
                src: decisionImage.value,
                alt: `Captured ${decisionSnapshot.value.symbol} ${decisionSnapshot.value.interval} chart through ${decisionSnapshot.value.cutoff}`,
                'data-testid': 'decision-preview',
              }),
              h('dl', { class: 'decision-metadata' }, [
                detailItem('Snapshot', decisionSnapshot.value.snapshot_id, 'decision-snapshot-id'),
                detailItem('Symbol', decisionSnapshot.value.symbol, 'decision-symbol'),
                detailItem('Interval', decisionSnapshot.value.interval, 'decision-interval'),
                detailItem('Cutoff', decisionSnapshot.value.cutoff, 'decision-cutoff'),
                detailItem(
                  'Chart range',
                  `${decisionSnapshot.value.chart_range.start} – ${decisionSnapshot.value.chart_range.end}`,
                  'decision-range',
                ),
                detailItem(
                  'Python crossover',
                  decisionSnapshot.value.python_crossover.signal,
                  'decision-python-crossover',
                ),
              ]),
            ])
          : null,
        decisionResult.value
          ? h('div', { class: 'decision-response', 'data-testid': 'decision-response' }, [
              h('h3', `Decision ${decisionResult.value.decision_id}`),
              h('p', `Provider: ${decisionResult.value.provider} · model: ${decisionResult.value.model}`),
              h('h4', 'Analyst proposal'),
              h('div', { class: 'decision-grid' }, decisionResult.value.questions.map((question) =>
                h('article', { class: 'decision-card' }, [
                  h('strong', question.name),
                  h('p', question.instructions),
                  h('small', `Choices: ${question.choices.map((choice) => choice.value).join(', ')}`),
                  h('span', { 'data-testid': `decision-answer-${question.name}` },
                    `Answer: ${decisionAnswers[question.name] ?? 'Missing'}`),
                ]),
              )),
              h('p', { class: 'decision-comparison', 'data-testid': 'decision-comparison' },
                `Visual crossover: ${decisionAnswers.crossover ?? 'Missing'} · Python crossover: ${decisionSnapshot.value.python_crossover.signal}`),
              h('h4', 'Independent reviewer'),
              h('p', `Reviewer model: ${decisionResult.value.reviewer_model ?? 'No valid response'}`),
              h('p', { 'data-testid': 'reviewer-verdict' },
                `Verdict: ${decisionResult.value.reviewer_answers?.find((answer) => answer.name === 'verdict')?.choice ?? 'Missing'}`),
              h('p', `Review choices: ${decisionResult.value.review_questions?.[0]?.choices.map((choice) => choice.value).join(', ') ?? 'Unavailable'}`),
              h('h4', 'Python final check'),
              h('p', { 'data-testid': 'decision-facts' },
                `Cash: $${decisionResult.value.final_check?.facts?.cash ?? 'unknown'} · One-share price: $${decisionResult.value.final_check?.facts?.price ?? 'unknown'} · Shares: ${decisionResult.value.final_check?.facts?.shares ?? 'unknown'} · Crossover: ${decisionResult.value.final_check?.facts?.python_crossover?.signal ?? 'unknown'}`),
              h('p', `Python account and strategy rules: ${decisionResult.value.final_check?.rules_passed ? 'passed' : 'failed'}`),
              h('p', {
                class: decisionResult.value.eligible_for_automation ? 'decision-eligible' : 'decision-ineligible',
                'data-testid': 'decision-eligibility',
              }, decisionResult.value.eligible_for_automation
                ? 'Analysis passed review. Any paper order appears in the automation trace above.'
                : `Ineligible for automated execution: ${decisionResult.value.eligibility_reasons.join(' ')}`),
              h('p', `Paper orders unchanged during analysis: ${decisionResult.value.paper_orders_unchanged ? 'yes' : 'no'}`),
            ])
          : null,
        h('section', { class: 'voice-panel', 'aria-labelledby': 'voice-title' }, [
          h('h3', { id: 'voice-title' }, 'Talk about a saved decision'),
          h('label', [
            'Selected decision ',
            h('select', {
              'aria-label': 'Selected paper decision',
              value: voiceDecisionId.value,
              disabled: microphoneActive.value,
              onChange: (event) => { voiceDecisionId.value = event.target.value },
            }, [
              h('option', { value: '' }, 'Choose a decision'),
              ...savedDecisions.value.map((item) => h('option', { value: item.decision_id },
                `${item.symbol} ${item.cutoff_utc} · ${item.decision_id}`)),
            ]),
          ]),
          selectedVoiceDecision ? h('div', { 'data-testid': 'voice-decision-summary' }, [
            h('p', `${selectedVoiceDecision.symbol} ${selectedVoiceDecision.interval} · ${selectedVoiceDecision.cutoff_utc}`),
            h('p', `Analyst: ${selectedVoiceDecision.analyst.action ?? 'no proposal'} · reviewer: ${selectedVoiceDecision.reviewer.verdict ?? 'no verdict'}`),
            h('p', `Paper outcome: ${selectedVoiceDecision.paper_outcome.status}${selectedVoiceDecision.paper_outcome.reason ? ` · ${selectedVoiceDecision.paper_outcome.reason}` : ''}`),
            selectedVoiceDecision.paper_outcome.fill_id
              ? h('p', `Fill ${selectedVoiceDecision.paper_outcome.fill_id}: ${selectedVoiceDecision.paper_outcome.order_quantity} shares at $${selectedVoiceDecision.paper_outcome.fill_price} · cash $${selectedVoiceDecision.paper_outcome.cash_after_fill} · shares ${selectedVoiceDecision.paper_outcome.shares_after_fill}`)
              : h('p', 'No recorded fill for this decision.'),
          ]) : h('p', 'No saved decision selected.'),
          h('div', { class: 'paper-actions' }, [
            h('button', { type: 'button', disabled: !voiceDecisionId.value || !['Idle', 'Ended', 'Failed', 'Disconnected'].includes(voiceStatus.value),
              onClick: startVoice, 'data-testid': 'start-voice' }, 'Start voice'),
            h('button', { type: 'button', disabled: ['Idle', 'Ended', 'Failed', 'Disconnected', 'Ending…'].includes(voiceStatus.value),
              onClick: endVoice, 'data-testid': 'end-voice' }, 'End voice'),
          ]),
          h('p', { 'data-testid': 'voice-status', 'aria-live': 'polite' },
            `Voice: ${voiceStatus.value} · microphone ${microphoneActive.value ? 'active' : 'off'}`),
          voiceError.value ? h('p', { class: 'error', role: 'alert' }, voiceError.value) : null,
          voiceInputTranscript.value ? h('p', { 'data-testid': 'voice-question' }, `You said: ${voiceInputTranscript.value}`) : null,
          voiceOutputTranscript.value ? h('p', { 'data-testid': 'voice-answer' }, `Voice answer: ${voiceOutputTranscript.value}`) : null,
          h('audio', { ref: voiceAudio, controls: true, autoplay: true, 'aria-label': 'Voice answer' }),
        ]),
      ])

      const watchlistPanel = h('section', { class: 'watchlist-panel', 'aria-label': 'Watchlist symbols' }, [
        h('p', { class: 'sidebar-note' }, 'Symbols available from this local workspace.'),
        h('p', { class: 'watchlist-group' }, 'LIVE / HISTORY'),
        h('button', { type: 'button', class: `watchlist-row ${mode.value === 'live' ? 'is-selected' : ''}`,
          'data-testid': 'watchlist-AAPL',
          onClick: () => loadDashboard(timeframe.value) }, [
          h('span', { class: 'symbol-mark' }, 'A'),
          h('span', { class: 'watchlist-name' }, [h('strong', 'AAPL'), h('small', 'Apple · local history')]),
          h('span', { class: 'watchlist-value' }, selected && mode.value === 'live' ? String(selected.close) : 'Open'),
        ]),
        h('p', { class: 'watchlist-group' }, 'RECORDED SESSIONS'),
        replaySelections.value.length
          ? replaySelections.value.map((item) => h('button', {
              type: 'button',
              class: `watchlist-row ${mode.value === 'replay' && symbol.value === item.ticker ? 'is-selected' : ''}`,
              onClick: () => loadReplaySelections(item.ticker),
            }, [
              h('span', { class: 'symbol-mark recorded-mark' }, 'R'),
              h('span', { class: 'watchlist-name' }, [h('strong', item.ticker), h('small', 'Saved replay')]),
              h('span', { class: 'watchlist-value' }, `${item.observations} rows`),
            ]))
          : h('p', { class: 'sidebar-note' }, watchlistError.value || 'No recorded symbols yet.'),
      ])

      return h('main', { class: 'market-shell' }, [
        h('header', { class: 'market-header' }, [
          h('div', { class: 'brand-lockup' }, [
            h('img', { class: 'brand-mark', src: brandLogo, alt: '', width: 38, height: 38 }),
            h('span', { class: 'brand-name' }, "Plunderer's Port"),
          ]),
          h('div', { class: 'header-controls' }, [
            h('div', { class: 'toolbar-symbol' }, [
              h('strong', symbol.value),
              h('span', mode.value === 'replay' ? 'Recorded session' : 'Market chart'),
            ]),
            h('label', { class: 'timeframe-picker' }, [
              h('span', 'Interval'),
              h('select', {
                'aria-label': 'Select chart timeframe',
                value: timeframe.value,
                onChange: (event) => changeTimeframe(event.target.value),
              }, TIMEFRAMES.map(([value, label]) => h('option', { value }, label))),
            ]),
            h('button', { class: 'toolbar-button', type: 'button', onClick: () => loadDashboard(timeframe.value) }, 'Latest · UTC'),
            mode.value==='live'
              ? h('button',{class:'toolbar-button',type:'button',onClick:loadEarliestHistory,
                  disabled:!historyEarliest.value,'data-testid':timeframe.value==='1d' ? 'earliest-daily' : 'earliest-history',
                  title:historyEarliest.value ? `Earliest saved record in this chart range: ${historyEarliest.value}` : 'History is loading or unavailable'},
                  historyEarliest.value ? `Earliest · ${historyEarliest.value.slice(0,10)}` : historyKind.value==='test' ? 'Earliest · fixture range' : historyFetch.value?.status==='unavailable' ? 'Earliest · unavailable' : 'Earliest · loading') : null,
            h('button', { class: 'toolbar-button', type: 'button', onClick: () => {
              const dock = document.querySelector('.indicator-dock')
              if (dock) { dock.open = true; dock.scrollIntoView({ behavior: 'smooth', block: 'nearest' }) }
            } }, `Indicators · ${indicators.value.length}`),
            h('label', { class: 'timeframe-picker mode-picker' }, [
              h('span', 'Workspace'),
              h('select', {
                'aria-label': 'Select dashboard mode',
                value: mode.value,
                onChange: (event) => event.target.value === 'replay' ? loadReplaySelections() : loadDashboard(timeframe.value),
              }, [h('option', { value: 'live' }, 'Live'), h('option', { value: 'replay' }, 'Replay')]),
            ]),
          ]),
          h('p', { class: 'status-chip', 'aria-live': 'polite' }, status.value),
        ]),
        h('div', { class: 'workspace-grid' }, [
          h('aside', { class: 'workspace-sidebar', 'aria-label': 'Market tools' }, [
            h('div', { class: 'sidebar-topline' }, [
              h('span', 'WORKSPACE'),
              h('strong', mode.value === 'replay' ? 'Replay' : 'Live market'),
            ]),
            h('details', { class: 'sidebar-section', open: true }, [
              h('summary', [h('span', 'Watchlist'), h('small', `${1 + replaySelections.value.length}`)]),
              watchlistPanel,
            ]),
            h('details', { class: 'sidebar-section', open: true }, [
              h('summary', [h('span', 'Decision Analysis'), h('small', 'Advisory')]),
              decisionPanel,
            ]),
            h('details', { class: 'sidebar-section', open: true }, [
              h('summary', [h('span', 'Paper Trading'), h('small', 'Simulation')]),
              paperPanel,
            ]),
          ]),
          h('div', { class: 'workspace-main' }, [
            h('div', { class: 'instrument-strip' }, [
              h('div', [
                h('p', { class: 'eyebrow' }, mode.value === 'replay'
                  ? 'RECORDED MARKET SESSION'
                  : liveCandleSource.value
                    ? `${liveCandleSource.value.toUpperCase()} OBSERVATIONS`
                    : historyKind.value === 'recorded' ? 'RECORDED MARKET OBSERVATIONS' : 'LABELED TEST FIXTURE'),
                h('h1', `${symbol.value} ${mode.value === 'replay' ? 'Replay' : 'Chart'}`),
              ]),
              selected ? h('div', { class: 'ohlc-strip' }, [
                h('span', `O ${selected.open}`), h('span', `H ${selected.high}`),
                h('span', `L ${selected.low}`), h('strong', {
                  class: selected.close >= selected.open ? 'price-up' : 'price-down',
                }, `C ${selected.close}`),
                h('span', `Vol ${selected.volume === null ? 'Unknown' : selected.volume}`),
              ]) : null,
              h('span', { class: completion.value?.interval_ended ? 'state-badge' : 'state-badge state-on' }, candleState),
            ]),
            replayControls,
            mode.value === 'live' && candles.value.length
              ? h('p', { class: 'sample-notice', 'data-testid': 'history-freshness', role: 'status' },
                  liveCandleSource.value
                    ? `Latest candle: ${latestCandleLabel}. Completed minutes reconcile with Yahoo reported OHLCV; provisional volume may be unknown.`
                    : `Yahoo recorded history: latest candle ${latestCandleLabel}. ${marketState.value?.label ?? 'Waiting for feed'}.`)
              : null,
            mode.value === 'live' && marketState.value
              ? h('p', { class: 'market-session-notice', 'data-testid': 'market-session' },
                  `${marketState.value.label} · Regular session · Next open ${marketState.value.next_open}. Prices retain their source timestamps.`) : null,
            historyFetch.value?.message
              ? h('p', { class: 'error', role: 'status', 'data-testid': 'history-fetch-error' }, historyFetch.value.message) : null,
            historyMessage.value && candles.value.length
              ? h('p',{class:'sample-notice',role:'status'},historyMessage.value) : null,
            mode.value === 'live' && !candles.value.length
              ? h('p', { class: 'sample-notice', role: 'status' }, historyLoading.value
                  ? 'Loading recent trading-session history. Market-closed hours do not prevent historical candles from loading.'
                  : historyMessage.value || 'Recent history is unavailable. Retrying the backend; the market does not need to be open.') : null,
            feedDetail.value ? h('p', { class: 'feed-detail', 'data-testid': 'feed-detail' }, feedDetail.value) : null,
            error.value ? h('p', { class: 'error', role: 'alert' }, error.value) : null,
            h('section', { class: 'chart-panel', 'aria-label': mode.value === 'replay' ? 'Replay chart' : 'Market chart' }, [
              mode.value === 'replay' ? h('div', { class: 'chart-mode-banner' }, 'Replay · recorded observations') : null,
              h('div', { ref: chartContainer, class: 'chart-container', 'data-testid': 'market-chart',
                title: 'Scroll to zoom. Hold Shift and scroll to move left or right.' }),
            ]),
            h('section', { class: 'feed-panel', 'aria-label': 'Feed status' }, [
              feedItem('Mode', mode.value === 'replay' ? 'Replay · read only' : 'Live', 'feed-mode'),
              feedItem('Symbol', symbol.value, 'feed-symbol'),
              feedItem('Interval', timeframe.value, 'feed-interval'),
              mode.value==='live' && historyPolicy.value ? feedItem('History range',historyPolicy.value.label,'history-range') : null,
              feedItem('Market session', marketState.value?.label ?? 'Fixture / replay', 'market-status'),
              feedItem('Chart data', mode.value === 'replay' ? 'Recorded replay' : historyKind.value === 'recorded' ? 'Recorded market data' : 'TEST DATA'),
              feedItem('Source', source.value, 'feed-source'),
              feedItem(mode.value === 'replay' ? 'Replay observation' : 'Source age', mode.value === 'replay' ? replayTime : formatAge(sourceAgeSeconds.value), 'feed-age'),
              feedItem('Upstream feed', feedStatus.value, 'feed-status'),
              feedItem('FastAPI socket', backendSocketStatus.value, 'socket-status'),
              feedItem('Candle', candleState, 'candle-state'),
              mode.value === 'replay' ? feedItem('Replay progress', replayProgress.value, 'replay-progress') : null,
              mode.value === 'replay' ? feedItem('Stored observations', replayStoredCount.value ?? 'Unknown', 'replay-count') : null,
            ].filter(Boolean)),
            mode.value === 'replay' && replayReceiptTime.value
              ? h('p', { class: 'receipt-time', 'data-testid': 'replay-receipt-time' }, `Original backend receipt time: ${replayReceiptTime.value}`)
              : null,
            h('section', { class: 'inspector', 'aria-labelledby': 'inspector-title' }, [
              h('div', { class: 'inspector-heading' }, [
                h('div', [h('p', { class: 'eyebrow' }, 'CROSSHAIR DETAILS'), h('h2', { id: 'inspector-title' }, 'Inspect a candle')]),
                h('label', { class: 'minute-picker' }, [
                  h('span', 'UTC candle'),
                  h('select', {
                    'aria-label': 'Inspect candle by UTC timestamp',
                    value: selected?.timestamp ?? '',
                    onChange: (event) => selectCandle(event.target.value),
                  }, candles.value.map((candle) => h('option', { value: candle.timestamp }, candle.timestamp))),
                ]),
              ]),
              selected
                ? h('div', [
                    h('dl', { class: 'detail-grid', 'data-testid': 'candle-details' }, [
                      detailItem('Date', displayTime.date, 'detail-date'),
                      detailItem('Time', displayTime.time, 'detail-time'),
                      detailItem('Open', selected.open, 'detail-open'),
                      detailItem('High', selected.high, 'detail-high'),
                      detailItem('Low', selected.low, 'detail-low'),
                      detailItem('Close', selected.close, 'detail-close'),
                      detailItem('Volume', selected.volume === null ? 'Unknown' : `${selected.volume} shares`, 'detail-volume'),
                    ]),
                    h('section', { class: 'indicator-values', 'aria-label': 'Indicator values' }, [
                      h('h3', 'Indicator values'),
                      selectedIndicatorValues.length
                        ? h('dl', { class: 'indicator-value-grid' }, selectedIndicatorValues.map((instance) =>
                            detailItem(instance.name, instance.selectedValue === null
                              ? 'Warm-up gap' : `${instance.selectedValue} ${instance.units}`,
                            `indicator-value-${instance.indicator_id}`)))
                        : h('p', 'No indicators configured for this chart.'),
                    ]),
                  ])
                : h('p', mode.value === 'replay' ? 'Start Replay to inspect its recorded candles.' : 'Move the crosshair over a candle or choose a timestamp.'),
            ]),
            h('details', { class: 'indicator-dock', open: true }, [
              h('summary', `Indicators · ${indicators.value.length} configured`),
              indicatorPanel,
            ]),
            h('footer', { class: 'attribution' }, [
              h('p', 'TradingView Lightweight Charts™ Copyright (с) 2025 TradingView, Inc.'),
              h('a', { href: 'https://www.tradingview.com/', target: '_blank', rel: 'noreferrer' }, 'Visit TradingView'),
              h('a', { href: 'https://tradingview.github.io/lightweight-charts/docs', target: '_blank', rel: 'noreferrer' }, 'Lightweight Charts documentation'),
            ]),
          ]),
        ]),
      ])
    }
  },
}).mount('#app')
