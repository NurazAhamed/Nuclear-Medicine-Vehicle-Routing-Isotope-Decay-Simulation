import React, { useState, useEffect, useMemo } from 'react'
import {
    MapContainer, TileLayer, Marker, CircleMarker, Popup, Polyline, useMap, useMapEvents
} from 'react-leaflet'
import L from 'leaflet'
import {
    Activity, AlertTriangle, Navigation,
    Truck, Wifi, Clock, Zap, XCircle, Crosshair,
    BrainCircuit, ShieldCheck, ShieldAlert, ShieldX, Ban, DollarSign
} from 'lucide-react'

const API = 'http://localhost:8000'

/* ─── Physics ─────────────────────────────────────────────────── */
const LAMBDA = 0.1155
const INITIAL_ACTIVITY = 100.0
const DOSE_VALUE = 1500

const calcPotency = (t_min) => INITIAL_ACTIVITY * Math.exp(-LAMBDA * (t_min / 60.0))

/* ─── Geometry ────────────────────────────────────────────────── */
function closestPtOnSeg(p, a, b) {
    const x = p.lat, y = p.lng, x1 = a[0], y1 = a[1], x2 = b[0], y2 = b[1]
    const A = x - x1, B = y - y1, C = x2 - x1, D = y2 - y1
    const dot = A * C + B * D, len2 = C * C + D * D
    const t = len2 !== 0 ? Math.max(0, Math.min(1, dot / len2)) : 0
    return { lat: x1 + t * C, lng: y1 + t * D }
}
function dist2(a, b) { return (a.lat - b.lat) ** 2 + (a.lng - b.lng) ** 2 }

/* ─── Styling ─────────────────────────────────────────────────── */
const COLORS = ['#10b981', '#3b82f6', '#f59e0b', '#8b5cf6']
const routeColor = (v) => COLORS[v % COLORS.length]
const tierColor = (t) => ({ 0: '#fbbf24', 1: '#10b981', 2: '#60a5fa', 3: '#ef4444' }[t] ?? '#94a3b8')

/* ═══════════════════════════════════════════════════════════════
   Icons
   ═══════════════════════════════════════════════════════════════ */
const anstoIcon = L.divIcon({
    className: '', iconSize: [32, 32], iconAnchor: [16, 16],
    html: `<div style="position:relative;width:32px;height:32px"><div class="ansto-pulse-ring"></div>
    <div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center">
      <div style="width:14px;height:14px;border-radius:50%;background:#fbbf24;border:2px solid #fef3c7;
      box-shadow:0 0 12px rgba(251,191,36,0.6)"></div></div></div>` })

const tier3Icon = L.divIcon({
    className: '', iconSize: [24, 24], iconAnchor: [12, 12],
    html: `<div style="position:relative;width:24px;height:24px"><div class="tier3-hazard-ring"></div>
    <div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center">
      <div style="width:10px;height:10px;border-radius:50%;background:#ef4444;border:2px solid #fca5a5;
      box-shadow:0 0 8px rgba(239,68,68,0.7)"></div></div></div>` })

const alertIcon = L.divIcon({
    className: '', iconSize: [32, 32], iconAnchor: [16, 28],
    html: `<div style="display:flex;align-items:center;justify-content:center;width:32px;height:32px;
    background:#ef4444;border-radius:50%;border:2px solid #fff;box-shadow:0 0 15px rgba(239,68,68,0.8);
    animation:pulse 1s infinite;cursor:pointer;">
    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none"
    stroke="white" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
    <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>
    <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg></div>` })

const canceledIcon = L.divIcon({
    className: '', iconSize: [80, 38], iconAnchor: [40, 12],
    html: `<div style="display:flex;flex-direction:column;align-items:center">
    <div style="width:14px;height:14px;border-radius:50%;background:#475569;border:2px solid #64748b;
    position:relative"><div style="position:absolute;inset:0;display:flex;align-items:center;
    justify-content:center;color:#ef4444;font-size:16px;font-weight:bold">×</div></div>
    <div style="font-size:8px;color:#ef4444;font-weight:bold;background:rgba(15,23,42,0.95);
    padding:1px 5px;border-radius:3px;margin-top:2px;white-space:nowrap;border:1px solid #7f1d1d;
    letter-spacing:0.5px">CANCELLED</div></div>` })

/* ═══════════════════════════════════════════════════════════════
   Map Helpers
   ═══════════════════════════════════════════════════════════════ */
function Recenter({ routes }) {
    const map = useMap()
    useEffect(() => {
        if (!routes?.length) return
        const pts = routes.flatMap(r => r.geometry?.length ? r.geometry : r.steps.map(s => [s.lat, s.lon]))
        if (!pts.length) return
        map.fitBounds(L.latLngBounds(pts).pad(0.15), { maxZoom: 13, duration: 0.8 })
    }, [routes, map])
    return null
}

function MapClickHandler({ onClick }) {
    useMapEvents({ click(e) { onClick(e.latlng) } })
    return null
}

/* ═══════════════════════════════════════════════════════════════
   VanCard — Clinical Triage + Financial Impact + Potency Deltas
   ═══════════════════════════════════════════════════════════════ */
function VanCard({ route, baselineRoutes }) {
    const color = routeColor(route.vehicle_id)
    const stops = route.steps.filter(s => s.tier !== 0)
    const canceled = route.canceled || []
    const fin = route.financial || {}
    const hasCanceled = canceled.length > 0

    const getBaseline = (name) => {
        if (!baselineRoutes) return null
        for (const r of baselineRoutes) {
            const m = r.steps?.find(s => s.name === name)
            if (m) return m.potency ?? null
        }
        return null
    }

    return (
        <div className={`border rounded-xl p-4 transition-all duration-300
      ${hasCanceled ? 'bg-red-950/30 border-red-500/60 shadow-[0_0_20px_rgba(239,68,68,0.1)]'
                : 'bg-slate-900/70 border-slate-800 hover:border-slate-600'}`}>

            {/* Header */}
            <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                    <Truck size={15} style={{ color }} />
                    <span className="text-xs font-bold text-slate-200 tracking-wide">
                        VAN {String(route.vehicle_id + 1).padStart(2, '0')}
                    </span>
                </div>
                <span className={`inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded-full
          ${stops.length ? 'bg-emerald-900/50 text-emerald-400 border border-emerald-700'
                        : 'bg-slate-800 text-slate-500 border border-slate-700'}`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${stops.length ? 'bg-emerald-400 animate-pulse' : 'bg-slate-600'}`} />
                    {stops.length ? 'EN ROUTE' : 'IDLE'}
                </span>
            </div>

            {/* Financial Bar */}
            {fin.mission_value > 0 && (
                <div className="flex items-center justify-between text-[9px] font-mono mb-3 px-1">
                    <span className="text-slate-500">MISSION VALUE</span>
                    <span className="text-emerald-400 font-bold">${fin.preserved_value?.toLocaleString()}</span>
                    <span className="text-slate-600">/</span>
                    <span className="text-slate-400">${fin.mission_value?.toLocaleString()}</span>
                    {fin.waste_value > 0 && (
                        <span className="text-red-400 text-[8px]">-${fin.waste_value?.toLocaleString()} waste</span>
                    )}
                </div>
            )}

            {stops.length === 0 && canceled.length === 0 ? (
                <p className="text-[11px] text-slate-600 italic pl-1">No deliveries assigned.</p>
            ) : (
                <div className="relative space-y-3">
                    <div className="absolute left-[5px] top-1 bottom-1 w-px bg-slate-800" />

                    {/* Viable Stops */}
                    {stops.map((s, i) => {
                        const pct = s.potency ?? calcPotency(s.arrival_time_min)
                        const triage = s.triage ?? (pct >= 70 ? 'OPTIMAL' : pct >= 35 ? 'DEGRADED' : 'FUTILE')
                        const Icon = triage === 'OPTIMAL' ? ShieldCheck : triage === 'DEGRADED' ? ShieldAlert : ShieldX
                        const tc = triage === 'OPTIMAL' ? 'text-emerald-400' : triage === 'DEGRADED' ? 'text-amber-400' : 'text-red-400'
                        const label = triage === 'OPTIMAL' ? 'Cardiac/Oncology' : triage === 'DEGRADED' ? 'Bone/Renal Only' : 'WASTE PREDICTED'

                        const baseline = getBaseline(s.name)
                        const delta = baseline != null ? (pct - baseline) : null
                        const stopValue = ((pct / 100) * DOSE_VALUE).toFixed(0)

                        return (
                            <div key={i} className="relative z-10 pl-3">
                                <div className="absolute left-[-4px] top-1 w-2.5 h-2.5 rounded-full border-2"
                                    style={{
                                        borderColor: triage === 'FUTILE' ? '#ef4444' : '#475569',
                                        background: triage === 'FUTILE' ? '#450a0a' : '#0f172a'
                                    }} />
                                <div className="flex justify-between items-start">
                                    <span className="text-[11px] font-medium text-slate-300 truncate max-w-[100px]">{s.name}</span>
                                    <div className="flex items-center gap-1.5">
                                        {delta != null && Math.abs(delta) > 0.1 && (
                                            <span className={`text-[9px] font-mono ${delta < 0 ? 'text-red-400' : 'text-emerald-400'}`}>
                                                {delta > 0 ? '▲' : '▼'}{Math.abs(delta).toFixed(1)}%
                                            </span>
                                        )}
                                        <span className={`text-[10px] font-mono font-bold ${tc}`}>
                                            {typeof pct === 'number' ? pct.toFixed(1) : pct}%
                                        </span>
                                    </div>
                                </div>
                                <div className="flex items-center justify-between mt-0.5">
                                    <span className="text-[10px] text-slate-500 font-mono">ETA: +{Math.round(s.arrival_time_min)}m</span>
                                    <span className="text-[9px] text-slate-600 font-mono">${stopValue}</span>
                                </div>
                                <div className={`flex items-center gap-1.5 mt-1 text-[9px] font-bold uppercase tracking-wide ${tc}
                  ${triage === 'FUTILE' ? 'animate-pulse' : ''}`}>
                                    <Icon size={10} />
                                    <span>{triage} ({label})</span>
                                </div>
                            </div>
                        )
                    })}

                    {/* Canceled Stops */}
                    {canceled.map((c, i) => (
                        <div key={`c-${i}`} className="relative z-10 pl-3 opacity-70">
                            <div className="absolute left-[-4px] top-1 w-2.5 h-2.5 rounded-full border-2 border-red-800 bg-red-950" />
                            <div className="flex justify-between items-start">
                                <span className="text-[11px] font-medium text-slate-500 line-through truncate max-w-[100px]">{c.name}</span>
                                <span className="text-[10px] font-mono font-bold text-red-500">{c.potency}%</span>
                            </div>
                            <div className="flex items-center justify-between mt-0.5">
                                <span className="text-[10px] text-slate-600 font-mono">ETA: +{Math.round(c.arrival_time_min)}m</span>
                                <span className="text-[9px] text-red-500 font-mono">-${DOSE_VALUE.toLocaleString()} lost</span>
                            </div>
                            <div className="flex items-center gap-1.5 mt-1 text-[9px] font-bold text-red-500 uppercase tracking-wide animate-pulse">
                                <Ban size={10} /> MISSION CANCELED — Diverting to viable targets
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}


/* ═══════════════════════════════════════════════════════════════
   AI Recommendation
   ═══════════════════════════════════════════════════════════════ */
function AIRecommendation({ analytics, baselineAnalytics, incident, routes }) {
    if (!analytics) return null
    const { fleet_avg_potency, fleet_stops_served, incident_active, snapped_road } = analytics

    let deltaMsg = ''
    if (baselineAnalytics && incident_active) {
        const d = fleet_avg_potency - baselineAnalytics.fleet_avg_potency
        deltaMsg = d < 0
            ? `Fleet potency dropped ${Math.abs(d).toFixed(1)}% due to incident.`
            : `Rerouting recovered ${d.toFixed(1)}% medical utility.`
    }

    const allStops = routes.flatMap(r => r.steps.filter(s => s.tier !== 0))
    const worst = allStops.reduce((w, s) => (s.potency ?? 100) < (w?.potency ?? 100) ? s : w, null)

    let rec = ''
    if (incident_active && worst) {
        const road = snapped_road ? ` on ${snapped_road}` : ''
        if (worst.potency < 35) rec = `Incident${road} has rendered ${worst.name} delivery futile at ${worst.potency}%. Recommend: Cancel and redistribute dose.`
        else if (worst.potency < 70) rec = `Incident${road} has degraded ${worst.name} potency to ${worst.potency}%. Rerouted via alternative roads. Viable for Bone/Renal only.`
        else rec = `All deliveries remain clinically optimal despite incident${road}. Rerouting successful.`
    } else {
        rec = `Fleet operating nominally. ${fleet_stops_served} hospitals served at ${fleet_avg_potency}% avg potency.`
    }

    return (
        <div className={`rounded-xl p-4 border transition-all duration-300
      ${incident_active ? 'bg-gradient-to-br from-amber-950/30 to-red-950/20 border-amber-500/30'
                : 'bg-gradient-to-br from-emerald-950/20 to-slate-900/50 border-emerald-500/20'}`}>
            <div className="flex items-center gap-2 mb-3">
                <BrainCircuit size={14} className={incident_active ? 'text-amber-400' : 'text-emerald-400'} />
                <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400">AI Dispatch Recommendation</span>
            </div>
            <p className="text-[11px] text-slate-200 leading-relaxed font-medium">{rec}</p>
            {deltaMsg && <p className="text-[10px] text-amber-400/80 mt-2 font-mono">{deltaMsg}</p>}
            <div className="grid grid-cols-3 gap-2 mt-3">
                <div className="bg-slate-900/50 rounded-lg p-2 text-center">
                    <div className="text-[10px] text-slate-500 font-mono">AVG POTENCY</div>
                    <div className={`text-sm font-bold ${fleet_avg_potency >= 70 ? 'text-emerald-400' : fleet_avg_potency >= 35 ? 'text-amber-400' : 'text-red-400'}`}>
                        {fleet_avg_potency}%</div>
                </div>
                <div className="bg-slate-900/50 rounded-lg p-2 text-center">
                    <div className="text-[10px] text-slate-500 font-mono">STOPS</div>
                    <div className="text-sm font-bold text-slate-200">{fleet_stops_served}</div>
                </div>
                <div className="bg-slate-900/50 rounded-lg p-2 text-center">
                    <div className="text-[10px] text-slate-500 font-mono">CARDIAC</div>
                    <div className="text-sm font-bold text-emerald-400">{analytics.clinical_outcomes?.cardiac_ready ?? '—'}</div>
                </div>
            </div>
        </div>
    )
}


/* ═══════════════════════════════════════════════════════════════
   Clinical Outcomes + Financial Impact
   ═══════════════════════════════════════════════════════════════ */
function ClinicalOutcomes({ analytics }) {
    const co = analytics?.clinical_outcomes
    const fin = analytics?.financial
    if (!co || !fin) return null

    const preservedPct = fin.total_mission_value > 0
        ? ((fin.total_preserved_value / fin.total_mission_value) * 100).toFixed(0)
        : 100

    return (
        <div className="rounded-xl border border-slate-700 bg-gradient-to-br from-slate-900/80 to-slate-950 overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-800 flex items-center gap-2">
                <DollarSign size={14} className="text-cyan-400" />
                <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400">Clinical Outcomes &amp; Financial Impact</span>
            </div>

            <div className="grid grid-cols-3 gap-2 p-4">
                <div className="bg-emerald-950/20 border border-emerald-900/30 rounded-lg p-3 text-center">
                    <div className="text-[9px] text-emerald-500/70 font-mono uppercase tracking-wider">Doses Saved</div>
                    <div className="text-2xl font-black text-emerald-400 mt-1">{co.doses_saved}</div>
                    <div className="text-[9px] text-slate-500 mt-0.5">&gt;60% potency</div>
                </div>
                <div className="bg-cyan-950/20 border border-cyan-900/30 rounded-lg p-3 text-center">
                    <div className="text-[9px] text-cyan-500/70 font-mono uppercase tracking-wider">Value Preserved</div>
                    <div className="text-xl font-black text-cyan-400 mt-1">${fin.total_preserved_value?.toLocaleString()}</div>
                    <div className="text-[9px] text-slate-500 mt-0.5">{preservedPct}% of mission</div>
                </div>
                <div className="bg-red-950/20 border border-red-900/30 rounded-lg p-3 text-center">
                    <div className="text-[9px] text-red-500/70 font-mono uppercase tracking-wider">Avoided Waste</div>
                    <div className="text-xl font-black text-red-400 mt-1">${fin.total_waste_value?.toLocaleString()}</div>
                    <div className="text-[9px] text-slate-500 mt-0.5">{co.avoided_waste_count} futile</div>
                </div>
            </div>

            {co.canceled_missions?.length > 0 && (
                <div className="px-4 pb-4 space-y-2">
                    {co.canceled_missions.map((m, i) => (
                        <div key={i} className="flex items-start gap-2 bg-red-950/20 border border-red-900/30 rounded-lg px-3 py-2">
                            <XCircle size={14} className="text-red-400 shrink-0 mt-0.5" />
                            <p className="text-[10px] text-red-300 leading-relaxed">
                                <span className="font-bold">MISSION CANCELED for {m.name}:</span>{' '}
                                Arrival potency {m.potency}% insufficient for clinical use.
                                Diverting resources to viable targets.
                            </p>
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}


/* ═══════════════════════════════════════════════════════════════
   MAIN APP
   ═══════════════════════════════════════════════════════════════ */
export default function App() {
    const [hospitals, setHospitals] = useState([])
    const [routes, setRoutes] = useState([])
    const [analytics, setAnalytics] = useState(null)
    const [baselineAnalytics, setBaselineAnalytics] = useState(null)
    const [baselineRoutes, setBaselineRoutes] = useState(null)
    const [loading, setLoading] = useState(null)
    const [time, setTime] = useState(new Date())

    const [incident, setIncident] = useState(null)
    const [incidentMode, setIncidentMode] = useState(false)
    const [toast, setToast] = useState(null)

    const [startTime, setStartTime] = useState(null)
    const [elapsed, setElapsed] = useState(0)

    useEffect(() => {
        const sr = localStorage.getItem('routes')
        const ss = localStorage.getItem('startTime')
        const si = localStorage.getItem('incident')
        const sa = localStorage.getItem('analytics')
        const sb = localStorage.getItem('baselineAnalytics')
        const sbr = localStorage.getItem('baselineRoutes')
        if (sr) setRoutes(JSON.parse(sr))
        if (ss) setStartTime(parseInt(ss, 10))
        if (si) setIncident(JSON.parse(si))
        if (sa) setAnalytics(JSON.parse(sa))
        if (sb) setBaselineAnalytics(JSON.parse(sb))
        if (sbr) setBaselineRoutes(JSON.parse(sbr))
        fetch(`${API}/hospitals`).then(r => r.json()).then(setHospitals).catch(console.error)
    }, [])

    useEffect(() => {
        const id = setInterval(() => {
            setTime(new Date())
            if (startTime) setElapsed(Math.floor((Date.now() - startTime) / 1000))
        }, 1000)
        return () => clearInterval(id)
    }, [startTime])

    useEffect(() => {
        if (toast) { const t = setTimeout(() => setToast(null), 4000); return () => clearTimeout(t) }
    }, [toast])

    const canceledNames = useMemo(() => {
        const s = new Set()
        analytics?.clinical_outcomes?.canceled_missions?.forEach(m => s.add(m.name))
        return s
    }, [analytics])

    const handleOptimize = async (targetIncident = incident) => {
        setLoading('optimize')
        try {
            const ts = Date.now()
            setStartTime(ts); setElapsed(0)
            localStorage.setItem('startTime', ts.toString())

            const headers = { 'Content-Type': 'application/json' }
            const body = targetIncident
                ? JSON.stringify({ avoid_point: { lat: targetIncident.lat, lon: targetIncident.lng } })
                : null

            const r = await fetch(`${API}/optimize`, { method: 'POST', headers, body })
            if (!r.ok) throw new Error('Optimization failed')
            const data = await r.json()

            const rd = data.routes ?? data
            const an = data.analytics ?? null
            setRoutes(rd); setAnalytics(an)
            localStorage.setItem('routes', JSON.stringify(rd))
            if (an) localStorage.setItem('analytics', JSON.stringify(an))

            if (!targetIncident && an) {
                setBaselineAnalytics(an); setBaselineRoutes(rd)
                localStorage.setItem('baselineAnalytics', JSON.stringify(an))
                localStorage.setItem('baselineRoutes', JSON.stringify(rd))
            }

            const cc = an?.clinical_outcomes?.avoided_waste_count ?? 0
            if (cc > 0) setToast(`${cc} futile delivery(s) auto-canceled`)
            else if (targetIncident) setToast('Rerouting complete — all deliveries preserved')

        } catch (e) { console.error(e); setToast('Error: Optimization failed') }
        finally { setLoading(null) }
    }

    const handleMapClick = (latlng) => {
        if (!incidentMode) return
        let minD2 = Infinity, snap = null
        const THRESH = 0.00003

        routes.forEach(r => {
            const pts = r.geometry?.length ? r.geometry : r.steps.map(s => [s.lat, s.lon])
            for (let i = 0; i < pts.length - 1; i++) {
                const p = closestPtOnSeg(latlng, pts[i], pts[i + 1])
                const d = dist2(latlng, p)
                if (d < minD2) { minD2 = d; snap = p }
            }
        })

        if (snap && minD2 < THRESH) {
            setIncident(snap)
            localStorage.setItem('incident', JSON.stringify(snap))
            setToast('Incident placed. Computing detour...')
            handleOptimize(snap)
        } else {
            setToast('Invalid: Not on active route')
        }
    }

    const clearIncident = (e) => {
        L.DomEvent.stopPropagation(e)
        setIncident(null); localStorage.removeItem('incident')
        setToast('Incident cleared. Restoring optimal routes...')
        handleOptimize(null)
    }

    const mins = Math.floor(elapsed / 60)

    return (
        <div className="flex h-screen bg-slate-950 text-slate-100 font-sans overflow-hidden relative">

            {toast && (
                <div className="absolute top-5 left-1/2 -translate-x-1/2 z-[2000] px-6 py-3 rounded-full
          bg-slate-900/90 border border-slate-700 shadow-2xl backdrop-blur-md text-sm font-semibold
          text-slate-200 flex items-center gap-2 animate-[fadeIn_0.3s_ease-out]">
                    {toast.startsWith('Invalid') || toast.startsWith('Error')
                        ? <XCircle size={16} className="text-red-400" />
                        : toast.includes('canceled')
                            ? <Ban size={16} className="text-amber-400" />
                            : <Zap size={16} className="text-emerald-400" />}
                    {toast}
                </div>
            )}

            {/* Sidebar */}
            <aside className="w-[420px] shrink-0 flex flex-col h-full z-10 relative bg-slate-900/80
        backdrop-blur-md border-r border-slate-800 shadow-[4px_0_30px_rgba(0,0,0,0.6)]">

                <div className="px-6 py-5 border-b border-slate-800">
                    <div className="flex items-center gap-3">
                        <div className="bg-emerald-500/10 border border-emerald-500/20 p-2 rounded-lg">
                            <Activity size={20} className="text-emerald-400" />
                        </div>
                        <div>
                            <h1 className="text-base font-extrabold tracking-widest text-slate-100">
                                DISPATCH<span className="text-emerald-500">.AI</span>
                            </h1>
                            <p className="text-[10px] text-slate-500 tracking-widest font-medium uppercase">
                                Prescriptive Nuclear Logistics
                            </p>
                        </div>
                    </div>
                </div>

                <div className="flex items-center justify-between px-6 py-3 border-b border-slate-800
          bg-slate-950/40 text-[10px] font-mono text-slate-500">
                    <span className="flex items-center gap-1.5"><Wifi size={10} className="text-emerald-500" /> ONLINE</span>
                    <span className="flex items-center gap-1.5"><Clock size={10} /> {time.toLocaleTimeString('en-AU', { hour12: false })}</span>
                    <span className="flex items-center gap-1.5 text-slate-300">T+{mins}m</span>
                </div>

                <div className="px-5 py-5 space-y-3 border-b border-slate-800">
                    <button onClick={() => handleOptimize(incident)} disabled={!!loading}
                        className="w-full flex items-center justify-center gap-2.5 py-3 px-4 rounded-xl bg-slate-800
              border border-slate-700 text-slate-200 text-sm font-semibold hover:bg-emerald-900/30
              hover:border-emerald-500/50 hover:text-emerald-300 transition-all duration-200
              shadow-lg shadow-black/30 disabled:opacity-50">
                        <Navigation size={16} className="text-emerald-400" />
                        {loading === 'optimize' ? 'Computing Detour...' : 'Optimise Fleet'}
                    </button>

                    <button onClick={() => setIncidentMode(!incidentMode)}
                        className={`w-full flex items-center justify-between px-4 py-3 rounded-xl border transition-all duration-200
              ${incidentMode ? 'bg-red-900/20 border-red-500/50 text-red-200'
                                : 'bg-slate-800/50 border-slate-700 text-slate-400 hover:bg-slate-800'}`}>
                        <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wide">
                            <Crosshair size={16} /> Manual Incident Mode
                        </div>
                        {incidentMode
                            ? <div className="text-[10px] bg-red-500 text-white px-2 py-0.5 rounded-full font-bold animate-pulse">ACTIVE</div>
                            : <div className="text-[10px] bg-slate-700 text-slate-300 px-2 py-0.5 rounded-full">OFF</div>}
                    </button>

                    {incidentMode && <p className="text-[10px] text-slate-500 text-center animate-pulse">Click on any route to place a disruption.</p>}
                    {incident && (
                        <div className="text-[10px] text-amber-500 flex items-center justify-center gap-1 animate-pulse font-bold">
                            <AlertTriangle size={12} /> Incident Active — Forced Road Diversion Applied
                        </div>
                    )}
                </div>

                <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
                    <AIRecommendation analytics={analytics} baselineAnalytics={baselineAnalytics} incident={incident} routes={routes} />
                    <ClinicalOutcomes analytics={analytics} />

                    <h2 className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Clinical Triage Panel</h2>
                    {routes.map(r => <VanCard key={r.vehicle_id} route={r} baselineRoutes={baselineRoutes} />)}
                </div>
            </aside>

            {/* Map */}
            <main className="flex-1 relative">
                <MapContainer center={[-33.95, 151.1]} zoom={10} scrollWheelZoom zoomControl={false}
                    className={`h-full w-full ${incidentMode ? 'cursor-crosshair' : ''}`}>
                    <TileLayer attribution='&copy; CARTO' url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" />
                    <Recenter routes={routes} />
                    <MapClickHandler onClick={handleMapClick} />

                    {incident && (
                        <Marker position={incident} icon={alertIcon} eventHandlers={{ click: clearIncident }}>
                            <Popup><div className="text-red-400 font-bold">Road Closure</div>
                                <div className="text-xs text-slate-300">Click icon to remove.</div></Popup>
                        </Marker>
                    )}

                    {hospitals.map((h, i) => {
                        if (canceledNames.has(h.name)) {
                            return <Marker key={i} position={[h.lat, h.lon]} icon={canceledIcon}>
                                <Popup><div className="text-red-400 font-bold">{h.name}</div>
                                    <div className="text-xs text-slate-400">MISSION CANCELED — Delivery diverted</div></Popup>
                            </Marker>
                        }
                        if (h.tier === 0) return <Marker key={i} position={[h.lat, h.lon]} icon={anstoIcon} />
                        if (h.tier === 3) return <Marker key={i} position={[h.lat, h.lon]} icon={tier3Icon} />
                        return <CircleMarker key={i} center={[h.lat, h.lon]} radius={5}
                            pathOptions={{ color: tierColor(h.tier), fillColor: tierColor(h.tier), fillOpacity: 0.75, weight: 1 }}>
                            <Popup>{h.name}</Popup></CircleMarker>
                    })}

                    {routes.map(r => (
                        <Polyline key={`${r.vehicle_id}-${routes.length}`}
                            positions={r.geometry?.length ? r.geometry : r.steps.map(s => [s.lat, s.lon])}
                            pathOptions={{
                                color: routeColor(r.vehicle_id), weight: incident ? 3.5 : 2.5,
                                opacity: 0.85, dashArray: incident ? '6 8' : null
                            }} />
                    ))}
                </MapContainer>

                <div className="absolute bottom-6 right-5 z-[1000] bg-slate-900/90 backdrop-blur p-4 rounded-xl border border-slate-700 text-xs shadow-xl">
                    <div className="font-bold text-slate-500 uppercase tracking-widest mb-2">Clinical Triage</div>
                    <div className="space-y-1.5">
                        <div className="flex items-center gap-2"><ShieldCheck size={12} className="text-emerald-400" />OPTIMAL (&gt;70%)</div>
                        <div className="flex items-center gap-2"><ShieldAlert size={12} className="text-amber-400" />DEGRADED (35-70%)</div>
                        <div className="flex items-center gap-2"><ShieldX size={12} className="text-red-400" />FUTILE (&lt;35%)</div>
                        <div className="flex items-center gap-2"><Ban size={12} className="text-red-500" />CANCELLED</div>
                    </div>
                </div>
            </main>
        </div>
    )
}
