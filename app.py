//@version=6
// © UnApologeticallyDeplorableMe
// @strategy_alert_message {{strategy.order.alert_message}}
//
// BUILD MARKER: TFSTACK-ADX4-PAIRPROFILES-V6.5.3-FX — FULL LAB + PIPMAN + CMP2 + RENDER WEBHOOK EXECUTION
// ULTRALEAN COMPILE: removed mapper/forensic/R-matrix/live-display/legacy-diagonal/informational-alert diagnostics only; trade/execution geometry preserved.
// PAIR PROFILE CONTRACT:
//   • MANUAL INPUTS is the default tuning surface: every normal R/G/T input remains authoritative.
//   • AUTO BY SYMBOL is an explicit SAVED-PROFILE LOCK and ignores manual R/G/T tuning inputs by design.
//   • Explicit EURUSD/AUDUSD modes let either saved profile be forced onto any chart for parity testing.
//   • Pair profiles override behavior-changing R/Guardian/Trigger/checkpoint parameters only.
//   • Display controls and live capital/execution controls remain ordinary user inputs.
//   • Unknown symbols fall back to MANUAL INPUTS; they are never silently assigned another pair's profile.
//   • Saved champions include their original 120D validation span; 30D alone is only the 16/16 AUDUSD forward block.
//   • V6.1 compile fix: Pine input `active=` expressions use INPUT-qualified booleans only; saved-profile runtime logic still overrides the historical window downstream.
//
// V6.2 LIVE-SIZING HARDENING — NO TRADE-GEOMETRY CHANGE:
//   • Strategy Tester quantity and LIVE OANDA quantity are named/separated explicitly.
//   • In portfolio-compound mode Pine never sends its Strategy Tester estimate as authoritative live units.
//   • Dynamic entry/flip payload sends units=0/requested_units=0 and requires backend sizing from fresh OANDA account state.
//   • Backend must fail CLOSED if fresh OANDA sizing cannot be completed; tester units may not be used as fallback.
//
// V6.3 AUTO OANDA TESTER MARGIN:
//   • TradingView historical margin defaults to AUTO OANDA TIER.
//   • 50:1 -> 2.0%; 33.3:1 -> 3.0%; 20:1 -> 5.0%.
//   • Manual historical margin remains available as an explicit override/fallback.
//   • LIVE OANDA Target Margin / Funded Trade (%) remains a separate capital-allocation control.
//
// V6.5 FX FRICTION REALISM:
//   • Native Strategy Tester slippage = 9 fractional-pip ticks on every market fill.
//   • That is ~0.9 pip per side / ~1.8 pips round trip, chosen to approximate the
//     current diversified average of OANDA US published spreads across 10 popular pairs (~1.85 pips).
//   • OANDA US spread-only pricing embeds commission in the spread, so no extra native
//     commission is added here. Live backend spread rejection remains authoritative.
//   • AUTO CHART TF maps 5m->R9, 15m->R8, 4H->R6, etc., preserving same-timeframe ZAG tests.
//
// V6.4.2 ZAG VISUAL REGISTRY FIX — DISPLAY ONLY:
//   • Root cause: the old ZAG renderer reused the shared ray registry, which is intentionally
//     trimmed to only a small number of recent R turns across ALL ten R sources. A slow source
//     (especially R1/R2) could therefore trade perfectly while having zero retained vertices to draw.
//   • Adds an independent deep ZAG-turn visual registry. It does NOT feed entries, exits, rays,
//     Guardian, Trigger, sizing, alerts, or the working-rail state machine.
//   • The exact traded source is still forced visible when ZAG FLIP is ON.
//
// V6.4.1 ZAG SOURCE-PLOT LOCK — DISPLAY ONLY:
//   • When ZAG FLIP is ON, the exact traded ZAG source is forced visible by default.
//   • Adds a right-edge source badge (R slot / timeframe / MA family / length).
//   • No ZAG turn math, source-selection logic, orders, sizing, alerts or historical results changed.
//
// V6.4 ZAG FLIP v1 — PURE ISOLATION TEST:
//   • Exclusive toggle: when ON, legacy Pivot-Ray and Leg-Shuttle order engines are disabled.
//   • Selected/visible R ZAG valley-turn confirmation -> LONG; peak-turn confirmation -> SHORT.
//   • Opposite confirmed ZAG turn atomically reverses the position; no Guardian, ADX, dot, ray-target, TP or stop filter.
//   • Orders execute on the CURRENT confirmation update, never retroactively at the visually plotted prior-bar vertex.
//   • Entry guards that protect live execution (pair eligibility, spread policy, DD lock, 5PM rollover) remain intact.
//
// GT47 CONTRACT:
//   • Gold control defaults are baked from the supplied EURUSD Strategy Tester export:
//       47 closed / 47 winners / 0 losers, plus 1 open trade at export time.
//   • Route/checkpoint geometry is unchanged. Independent Guardian/Trigger profiles NEVER cast route rays.
//   • Guardian and Trigger may use the same R/timeframe while using different RAW MA family/length.
//   • Both role overrides default OFF, so the first compile must reproduce the existing 47/47 control.
//   • TradingView historical sizing is isolated from LIVE OANDA portfolio sizing.
//   • Realtime fresh entries are blocked 5:00–5:59 PM America/New_York; exits remain active.
//   • LIVE payload now carries per-trade target margin %, portfolio ceiling %, and funded-position cap.
// TFSTACK-ADX1 ARCHITECTURE
// R1..R10 are now FIXED timeframe bays aligned 1:1 with the existing H/W/K/E + ADX regime ladder:
// R1=1W, R2=1D, R3=12H, R4=8H, R5=6H, R6=4H, R7=1H, R8=15m, R9=5m, R10=1m.
// Each R keeps selectable HMA/WMA/KS/EMA, length, RAW/ZAG, rays and role participation.
// Each R also owns an OPTIONAL ADX/DI trade qualifier. Default OFF = zero behavior change.
// The 25/25 champion is migrated by TIMEFRAME, not discarded:
// old R5 1D KS27 RAW -> R2; old R6 15m HMA27 RAW -> R8;
// old R7 5m KS27 RAW -> R9; old R8 1m KS27 ZAG -> R10.
// Guardian migrates R6 -> R8. Trigger migrates R5 -> R2.
// This keeps the actual champion geometry while making slot identity = timeframe identity.
//
// PARITY25 CONTROL — runtime settings baked from the user's 25/25 EURUSD instance.
// Acceptance target on the same 1D chart/session/window: 25/25 total, with the
// latest 30-day forensic block 8/8 as shown in the supplied screenshot.
// This file intentionally preserves the original F6.10.5 trade engine.
// It changes defaults/properties only; no entry/exit/ray/checkpoint algorithm was rewritten.
//
// TGIM v12.44F6.10.5 — PARAMETER MAPPER / WALK-FORWARD
//
// Purpose:
//   Tune pair-specific R values on a CALIBRATION window, then FREEZE the selected
//   R5/R6 profile and test it untouched on a separate FORWARD window.
//
// This does NOT invent a fake simplified sweeper for the checkpoint engine.
// It uses the actual TGIM strategy logic and actual Strategy Tester orders.
//
// Added:
//   • Mapper Mode:
//       OFF
//       CALIBRATION ONLY
//       FROZEN FORWARD ONLY
//       CAL + FORWARD AUDIT
//   • Calibration Days (default 90)
//   • Forward Days (default 30)
//   • Forward Block Offset
//   • Frozen R5/R6 profile fields
//   • Optional hard block if Forward mode no longer matches the frozen profile
//   • Mapper table: calibration vs forward trades / W-L / Win% / PF / MAE / hold
//
// Immediate requested updates:
//   • Backtest Window default = Last 30 Days.
//   • "Historical R Turns To Scan" minimum selectable value = 3 (was 20).
//
// All F6.10.4 presets remain intact:
//   One Leg Only / Guardian R6 / Direction Flip / Trigger R5
//   R5 4H KS2 ZAG / R6 15m KS27 ZAG
//   ZAG segments default 12 / max 99
//   Diagonal ray plotting OFF
//   No Guardian / rail-departure exit once a trade is open.
//
// TGIM v12.44F6.10.4 — REQUESTED DEFAULTS PATCH
//
// NO trade-logic change from F6.10.3.
// Defaults changed only:
//   After Target Exit = One Leg Only
//   Guardian Rail Slot = R6
//   Guardian Break Definition = Guardian Direction Flip
//   Trigger / Traveler Rail Slot = R5
//   R5 = ON / 4H / KS 2 / Working Rail ZAG
//        Raw dots ON / ZAG ON / Horizontal P/V Rays ON
//        ZAG Segments default 12
//   R6 = ON / 15m / KS 27 / Working Rail ZAG
//        ZAG display remains ON
//   Enable Diagonal Ray Plotting = OFF
//   All R1-R10 ZAG Segment controls: default 12, max selectable 99
//
// TGIM v12.44F6.10.3 — NO-GUARDIAN FORENSIC AUDIT
//
// TRADE LOGIC IS UNCHANGED FROM F6.10.2.
// This build adds diagnostics only, plus an optional 30-day test-block offset.
//
// Added:
//   • Current open-trade age / unrealized P&L / open-trade MAE.
//   • Current stored target + distance to target.
//   • Longest closed hold and worst closed-trade MAE.
//   • Count of long-duration ("stranded") closed trades.
//   • 12 contiguous 30-day forensic blocks: trades, wins, win%, PF,
//     position-open-at-block-end, worst MAE, longest hold.
//   • 30D Block Offset input so "Last 30 Days" can be shifted backward
//     one non-overlapping 30-day block at a time without touching the logic.
//
// IMPORTANT:
//   The rolling 12-block table can only analyze trades that the strategy actually
//   generated. Use Backtest Window = All History to populate all 12 rows at once,
//   or use Last 30 Days + Block Offset to test one block at a time.
//
// TGIM v12.44F6.10.2 — NO GUARDIAN / RAIL-DEPARTURE TRADE EXIT
// ISOLATION TEST — ONE EXECUTION CHANGE ONLY:
//   • Once a position is open, Guardian/working-rail departure can NOT close it.
//   • The stored ray/checkpoint TARGET remains the only normal trade exit.
//   • Guardian direction/side logic is otherwise retained for entry qualification,
//     checkpoint-route qualification, flat-state cancellation/requalification, and display.
//   • No entry rule, target selection, checkpoint logic, sizing, R/ZAG geometry,
//     spread/DD guard, alert payload, or preset was changed.
//
//
// TGIM v12.44F6.10.1 — AUDIT REPAIR
// The F6.10 cleanup removed two multiline status assignments incompletely and also
// removed two variables that still feed live decision text/route logic.
// Repairs:
//   • Removed orphaned F-status continuation.
//   • Removed orphaned closed-trade status continuation.
//   • Restored _entryModeShort because live entry decisions still use it.
//   • Restored _triggerDirState because checkpoint continuation logic still uses it.
// No R/ZAG architecture, trade rules, sizing, market exits, alerts, or presets changed.
//
// TGIM v12.44F6.10 — R-CONTAINED ZAG + AUDITED LEAN
// UI / architecture:
//   • Every R1-R10 now owns its complete rail + ZAG configuration.
//   • Removed global R Zag Segments / R Zag Width controls from DISPLAY.
//   • Each R now has Working Rail = RAW / ZAG.
//   • Each R now owns Show ZAG, ZAG Segments, and ZAG Width.
//   • Guardian / Trigger consume the finished R slot; they do not separately manage ZAG.
//
// Current requested defaults preserved:
//   • ONLY R5 enabled.
//   • R5 = 4H / WMA 2.
//   • R5 Working Rail = ZAG.
//   • R5 ZAG shown, route rays ON.
//   • Guardian = R5.
//   • Trigger / Traveler = R5.
//   • Target scope = Same R.
//   • Flat threshold / ATR slope normalization remain removed.
//
// Conservative runtime audit:
//   • Removed write-only status strings and dead formatting that no table/alert/order reads.
//   • Removed stale forensic-only placeholders/comments left after the forensic table was deleted.
//   • Kept route state, Guardian state booleans, checkpoint logic, diagnostics, ADX/DI,
//     exact OANDA sizing, market ray exits, exact fill labels, and live Pac-Man execution.
//
// TGIM v12.44F6.9.2 — SLOPE COMPILE FIX
// F6.9.1 correctly moved the OANDA sizing helpers, but the ATR-removal cleanup left
// f_slope_angle() with a dead third argument. Passing bare `na` into that untyped
// argument is illegal in Pine v6.
// F6.9.2 removes that unused argument completely and updates every call site.
// No trade logic, R5 preset, OANDA sizing, market exits, or alert behavior changed.
//
// TGIM v12.44F6.9.1 — COMPILE ORDER FIX
// F6.9's OANDA payload helper was declared before the leverage/percent-sizing
// helpers it referenced. Pine requires those references to be resolvable first.
// No trade logic, R5 preset, sizing behavior, Guardian/Trigger rule, or exits changed.
//
// TGIM v12.44F6.9 — R5 PRESET + ZERO-THRESHOLD CLEANUP
// Preset donor requested from the current live setup:
//   • ONLY R5 enabled by default.
//   • R5 = 4H / WMA 2 / ZAG.
//   • Show R5 Zag = ON; Use R5 Zag As Rail = ON.
//   • R5 horizontal P/V rays / route source = ON.
//   • Guardian = R5.
//   • Trigger / Traveler = R5.
//   • Exit Target Ray Scope = Same R, therefore R5 -> R5 opposite checkpoint.
//   • Guardian buffer = 0.
//   • Checkpoint check window = 0.
//   • Must leave checkpoint by = 0.
//   • Active decision checkpoint/zone display = OFF.
//
// Slope cleanup:
//   • Removed Flat / Sideways Threshold input.
//   • Removed ATR Normalization Length input.
//   • No ATR slope normalization remains.
//   • Positive one-bar rail change = UP.
//   • Negative one-bar rail change = DOWN.
//   • Exact zero only = FLAT.
//
// F6.8 exact-unit / percent sizing contract, market ray exits, exact fill labels,
// spread/DD guards, History Bar Tick and Realtime Bar Tick remain intact.
//
// TGIM v12.44F6.8 — EXACT OANDA SIZING CONTRACT
// - Fixes the live-size ambiguity that allowed the backend to reinterpret a 10-unit
//   Pine order as dynamic percent-of-equity sizing.
// - Live Sizing Mode defaults to EXACT FIXED UNITS = 10.
// - Payload explicitly sends sizing_mode, requested_units, risk_pct, leverage tier,
//   margin-rate %, and a hard exact-units request.
// - Optional % mode is preserved for later scaling, but the broker/backend must use
//   CURRENT OANDA NAV as source of truth for percentage sizing.
// - Market ray exits + exact fill labels from F6.7 remain intact.
//
// TGIM v12.44F6.7 — MARKET RAY EXIT + FILL LABELS
// - Entries remain market orders.
// - ALL checkpoint/ray target exits are now MARKET closes triggered when live/history
//   execution price reaches/crosses the stored target ray.
// - No resting strategy.exit(limit=...) take-profit orders remain.
// - Guardian exits remain market closes.
// - Exact TradingView broker-emulator ENTRY and EXIT fill prices are labeled from
//   strategy.opentrades / strategy.closedtrades.
// - Exit labels include signed pips and exit reason.
// - Daily structure + continuous Pac-Man execution from F6.6 remains intact.
//
// TGIM v12.44F6.6 — LEAN CLEANUP
// Preserves F6.5 Daily Structure + Continuous Pac-Man execution.
// LIVE: keep chart/alert interval on 1D; realtime ticks are the traveler clock.
// Strategy defaults: History Bar Tick ON, Realtime Bar Tick ON, Order Fill recalc OFF.
// OANDA trade alert: Order fills only | {{strategy.order.alert_message}}
//
// Removed as dead/non-authoritative:
// - forensic measurement/aggregation engine left behind after its table was deleted
// - unused qualification/checkpoint/guardian/gap telemetry counters
// - abandoned 1-second execution experiment and its period-dedup branches
// - R1-R10 inverse slope-angle/color calculations (inverse RAILS remain)
// - legacy H/W/K/E peak-valley/inverse-cross calculations not consumed anywhere
// - unused original S1 ATR interaction math (diagonal rays remain)
// - assignment-only/declaration-only execution state with no readers
//
strategy("TGIM FOREX ZAG FLIP — V6.5.3 FX FULL LAB WEBHOOK",
     overlay=true,
     max_labels_count=500,
     max_lines_count=500,
     pyramiding=0,
     initial_capital=2500,
     currency=currency.USD,
     default_qty_type=strategy.percent_of_equity,
     default_qty_value=1,
     margin_long=2.0,
     margin_short=2.0,
     slippage=9,
     calc_on_every_tick=true,
     calc_on_every_history_tick=true,
     calc_on_order_fills=false,
     process_orders_on_close=false,
     dynamic_requests=true)

// v12.44F6:
// Original v12.44 remains the visual/execution donor. The unrelated six-pair
// scanner remains removed for Pine compiler headroom; R1-R10, dots, rays,
// clustering/display geometry, remaining tables, and donor execution mode remain intact.
// F adds one faithful shuttle layer on top of finalized v12.44 ray EVENTS:
// confirmed structural legs -> rail check -> MAIN -> fixed RETURN -> next MAIN.
// Intended control: 1D chart, R1 = W / HMA / 2, shuttle Guardian OFF.
// F1 added Guardian Break Definition: PRICE CLOSE vs meaningful GUARDIAN DIRECTION FLIP.
// F2 hardens payment identity, HTF commit identity, cluster isolation, and route recovery after invalid/gap attempts.
// F5 adds R1-R10 causal Zag display/use-as-rail and the 1m→1W default ladder.
// F6 removes challenge/profile sizing, uses exact fixed units, maps every current OANDA US 50/33.3/20 pair, and restores spread + max-DD entry guards.
// F3 added an INTERNAL rolling/custom execution window for normal Strategy Tester.
// F4 removes token-heavy display/foundation extras only: real-candle overlay, compact
// forensic table, competition winner toggle, futures intraday/flat foundation flags,
// and the current-market foundation table. Trade geometry/execution remains unchanged.
// Structural rails/rays/legs keep full-history warm-up; NEW entries are window-gated.

//──────────────────────────────────────────────
// 01 — R-BAY ENGINE
// Legacy global H/W/K/E scanner defaults removed. Each fixed-timeframe R bay
// owns its rail family, length, RAW/ZAG mode, rays and optional ADX/DI gate.

// 02 — Signal source
//──────────────────────────────────────────────
groupSource = "02 — SIGNAL SOURCE"
useHeikinAshiMath = input.bool(false, "Use Heikin-Ashi Math", group=groupSource)
// Real wick-break chart coloring/markers remain available; the separate real-candle
// overlay itself was removed in F4 for compiler headroom.
colorRealWickBreakCandles = input.bool(false, "Color Real Wick Break Candles", group=groupSource)
applyBreakColorsToChartBars = input.bool(false, "Apply Break Colors To Chart Bars", group=groupSource,
     active=colorRealWickBreakCandles)
showBreakMarkers = input.bool(false, "Show Wick Break Markers", group=groupSource,
     active=colorRealWickBreakCandles)
bullCloseBreakColor = input.color(color.rgb(0, 145, 0), "Close Above Previous Real Wick", group=groupSource,
     active=colorRealWickBreakCandles)
bearCloseBreakColor = input.color(color.rgb(145, 0, 0), "Close Below Previous Real Wick", group=groupSource,
     active=colorRealWickBreakCandles)
bullOwnWickBreakColor = input.color(color.rgb(0, 190, 110), "Close Above Prev Wick + Own Upper Wick", group=groupSource,
     active=colorRealWickBreakCandles)
bearOwnWickBreakColor = input.color(color.rgb(190, 0, 90), "Close Below Prev Wick + Own Lower Wick", group=groupSource,
     active=colorRealWickBreakCandles)

useStandardTickerOhlc = input.bool(false, "Use Standard Ticker OHLC Source", group=groupSource,
     tooltip="OFF is replay-safe and uses chart OHLC. ON pulls standard-symbol OHLC, useful only when chart is non-standard/HA and you need real candles.")
standardTickerId = ticker.standard(syminfo.tickerid)
[stdOpen, stdHigh, stdLow, stdClose] = request.security(standardTickerId, timeframe.period,
     [open, high, low, close], barmerge.gaps_off, barmerge.lookahead_off)
realOpen = useStandardTickerOhlc ? stdOpen : open
realHigh = useStandardTickerOhlc ? stdHigh : high
realLow = useStandardTickerOhlc ? stdLow : low
realClose = useStandardTickerOhlc ? stdClose : close

var float haOpen = na
haClose = (realOpen + realHigh + realLow + realClose) / 4.0
haOpen := na(haOpen[1]) ? (realOpen + realClose) / 2.0 : (haOpen[1] + haClose[1]) / 2.0
haHigh = math.max(realHigh, math.max(haOpen, haClose))
haLow = math.min(realLow, math.min(haOpen, haClose))

signalClose = useHeikinAshiMath ? haClose : realClose

prevRealBodyHigh = math.max(realOpen[1], realClose[1])
prevRealBodyLow = math.min(realOpen[1], realClose[1])
realBullCloseBreak = colorRealWickBreakCandles and not na(realHigh[1]) and realClose > prevRealBodyHigh and realClose > realHigh[1]
realBearCloseBreak = colorRealWickBreakCandles and not na(realLow[1]) and realClose < prevRealBodyLow and realClose < realLow[1]
realBullOwnWickBreak = realBullCloseBreak and realHigh > realClose
realBearOwnWickBreak = realBearCloseBreak and realLow < realClose

chartBreakColor = colorRealWickBreakCandles and applyBreakColorsToChartBars ?
     realBullOwnWickBreak ? bullOwnWickBreakColor :
     realBearOwnWickBreak ? bearOwnWickBreakColor :
     realBullCloseBreak ? bullCloseBreakColor :
     realBearCloseBreak ? bearCloseBreakColor : na : na

barcolor(chartBreakColor, title="Real Wick Break Chart Bar Colors")

//──────────────────────────────────────────────
// 03 — SLOPE DIRECTION ENGINE
// No ATR normalization and no configurable flat threshold.
// Rising by any amount = UP.
// Falling by any amount = DOWN.
// Exact zero change only = FLAT.
//──────────────────────────────────────────────



f_tgim_table_position(_p) =>
    switch _p
        "Top Left" => position.top_left
        "Top Center" => position.top_center
        "Top Right" => position.top_right
        "Middle Left" => position.middle_left
        "Middle Center" => position.middle_center
        "Middle Right" => position.middle_right
        "Bottom Left" => position.bottom_left
        "Bottom Center" => position.bottom_center
        => position.bottom_right

//──────────────────────────────────────────────
// 04 — TESTER / LIVE OANDA SIZING + ENTRY GUARDS
// GT47 separates historical Strategy Tester quantity from LIVE OANDA portfolio sizing.
// OANDA margin tiers are recognized internally from the chart pair.
// 50:1 = 2% margin, 33.3:1 = 3%, 20:1 = 5%.
// True OANDA spread and portfolio headroom are authoritative at the live backend.
//──────────────────────────────────────────────
groupLive = "04 — TESTER / LIVE OANDA SIZING + ENTRY GUARDS"

// Historical Strategy Tester margin only. AUTO derives the broker margin basis from
// the current OANDA pair tier; MANUAL remains available as an explicit override/fallback.
testerMarginMode = input.string("AUTO OANDA TIER", "TradingView Historical Margin Mode",
     options=["AUTO OANDA TIER","MANUAL"], group=groupLive,
     tooltip="AUTO OANDA TIER = 50:1 -> 2%, 33.3:1 -> 3%, 20:1 -> 5% based on the current chart pair. MANUAL uses the percentage below. This affects TradingView Strategy Tester sizing only, never live OANDA capital allocation.")

testerMarginAllocationPct = input.float(2.0, "Manual Historical Margin / Trade (%)",
     minval=0.01, maxval=100.0, step=0.1, group=groupLive,
     active=testerMarginMode == "MANUAL",
     tooltip="Manual Strategy Tester margin override/fallback only. Live OANDA sizing remains backend-authoritative.")

liveSizingMode = input.string("% of OANDA Equity as Margin", "Live OANDA Sizing Mode",
     options=["EXACT Fixed Units","% of OANDA Equity as Margin"], group=groupLive,
     tooltip="% mode = backend is the ONLY live sizing authority. Pine sends no dynamic unit request; backend must calculate from fresh OANDA account state immediately before every entry/flip and reject if it cannot.")

liveUnitsPreset = input.string("1", "Exact Fixed Units", options=["1","5","10","25","50","100","250","500","1000","Custom"], group=groupLive,
     active=liveSizingMode == "EXACT Fixed Units",
     tooltip="Literal OANDA units requested when Live OANDA Sizing Mode = EXACT Fixed Units.")
customFixedUnits = input.int(10, "Custom Exact Units", minval=1, step=1, group=groupLive,
     active=liveSizingMode == "EXACT Fixed Units" and liveUnitsPreset == "Custom")

liveOandaPerTradeTargetPct = input.float(10.0, "LIVE OANDA Target Margin / Funded Trade (%)",
     minval=0.1, maxval=100.0, step=0.5, group=groupLive,
     active=liveSizingMode == "% of OANDA Equity as Margin",
     tooltip="Target initial margin allocation for EACH newly funded trade. Example: 25 means use 25% of fresh backend sizing equity as initial margin for that entry. This is margin allocation, not stop-loss risk.")
portfolioMarginCeilingPct = input.float(30.0, "LIVE OANDA Portfolio Margin Ceiling (%)",
     minval=1.0, maxval=100.0, step=0.5, group=groupLive,
     active=liveSizingMode == "% of OANDA Equity as Margin",
     tooltip="Account-wide initial-margin ceiling across all TGIM funded positions. Selectable to 100%; backend hard ceilings still apply.")
portfolioMaxConcurrent = input.int(3, "LIVE OANDA Max Concurrent FUNDED Positions",
     minval=1, maxval=50, group=groupLive,
     active=liveSizingMode == "% of OANDA Equity as Margin",
     tooltip="Funded-position cap only. It does not limit how many charts/pairs may scan and alert.")
portfolioSizingEquityMode = input.string("MIN(Balance,NAV)", "LIVE OANDA Compounding Equity",
     options=["MIN(Balance,NAV)","NAV"], group=groupLive,
     active=liveSizingMode == "% of OANDA Equity as Margin",
     tooltip="MIN(Balance,NAV) compounds realized gains, reduces size for floating losses, and does not borrow against floating profit above Balance.")

int fixedUnits =
     liveUnitsPreset == "1" ? 1 :
     liveUnitsPreset == "5" ? 5 :
     liveUnitsPreset == "10" ? 10 :
     liveUnitsPreset == "25" ? 25 :
     liveUnitsPreset == "50" ? 50 :
     liveUnitsPreset == "100" ? 100 :
     liveUnitsPreset == "250" ? 250 :
     liveUnitsPreset == "500" ? 500 :
     liveUnitsPreset == "1000" ? 1000 : customFixedUnits
restrictToOandaCoreTiers = input.bool(true, "Only OANDA 50:1 / 33.3:1 / 20:1 Pairs", group=groupLive,
     tooltip="ON blocks new entries on symbols outside the current OANDA US 50:1, 33.3:1 and 20:1 FX tiers. Exits are never blocked.")
maxSpreadPips = input.float(7.0, "Max Live Spread (pips)", minval=0.0, step=0.1, group=groupLive,
     tooltip="0 = off. True live OANDA spread belongs in the execution/backend guard. Pine normal-timeframe history cannot reconstruct broker bid/ask spread.")
spreadGuardMode = input.string("Backend Only", "Spread Guard", options=["Backend Only","Manual Spread Input"], group=groupLive,
     tooltip="Backend Only = Pine permits the signal and the OANDA execution layer rejects entries above Max Live Spread. Manual Spread Input can gate Pine entries for a controlled test. Closes are never blocked.")
manualCurrentSpreadPips = input.float(0.0, "Manual Current Spread (pips)", minval=0.0, step=0.1, group=groupLive,
     active=spreadGuardMode == "Manual Spread Input")
blockNy5pmEntryHour = input.bool(true, "Block New Entries 5:00–5:59 PM New York", group=groupLive,
     tooltip="Realtime only. BUY/SELL/FLIP are blocked during the New York rollover hour. Existing positions may always close.")
deferNy5pmQualifiedEntries = input.bool(true, "Remember Qualified 5PM Setups For Post-Rollover Re-entry", group=groupLive,
     tooltip="Realtime only. A structurally valid setup blocked by the 5PM rollover is remembered. After 6PM it is revalidated and retried to the OANDA backend until live spread is acceptable, the target is passed, or structure invalidates.")
deferredRetrySeconds = input.int(15, "Deferred Entry Retry Interval (seconds)", minval=15, maxval=60, group=groupLive, active=deferNy5pmQualifiedEntries)
deferredMaxAgeMinutes = input.int(120, "Deferred Setup Maximum Age (minutes)", minval=1, maxval=720, group=groupLive, active=deferNy5pmQualifiedEntries)
useMaxDDTradeGate = input.bool(true, "Use Max Drawdown Entry Lock", group=groupLive,
     tooltip="Blocks NEW entries after this chart/script's running max drawdown reaches the limit. Existing positions can still exit normally.")
maxDDLimitPct = input.float(2.0, "Max Drawdown % Allowed", minval=0.0, step=0.1, group=groupLive)

liveIntrabarEntries = input.bool(true, "Live Intrabar Entry / Re-entry", group=groupLive,
     tooltip="ON = on the open realtime bar, TGIM may submit fresh qualified entries/re-entries on incoming price ticks instead of waiting for the chart bar to close. Historical behavior still follows TradingView's History Bar Tick setting. Guardian PRICE CLOSE logic remains close-confirmed.")

livePersistentCheckpointEntries = input.bool(true, "Live Pac-Man: Existing Checkpoint Entries", group=groupLive,
     tooltip="ON = while the Daily strategy is flat, incoming realtime price may board from an already-existing route-eligible standalone ray/checkpoint. A brand-new Daily ray is NOT required. Guardian + Trigger must align, and a forward opposite checkpoint must exist.")
liveCheckpointTouchWindow = input.float(0.0, "Live Pac-Man Touch Window (pips/ticks)", minval=0.0, step=0.1, group=groupLive,
     active=livePersistentCheckpointEntries,
     tooltip="0 = exact crossing/touch of the checkpoint by the realtime price segment. Increase only if you intentionally want a tolerance zone around existing checkpoints.")
liveCheckpointSameBarOnce = input.bool(true, "One First-Board Per Checkpoint Per Daily Bar", group=groupLive,
     active=livePersistentCheckpointEntries,
     tooltip="Prevents realtime oscillation around one old checkpoint from repeatedly creating fresh first-board entries on the same Daily bar. Normal paid-checkpoint continuation logic remains separate.")



marketRayExitImmediate = input.bool(true, "Market Ray Exit: Immediate Emulator Close", group=groupLive,
     tooltip="ON = when price reaches the stored ray/checkpoint, strategy.close(... immediately=true) is used so TradingView can fill the modeled market exit on that execution tick. Live OANDA still fills at the broker's available market price and can differ by spread/slippage.")

// Historical bars are always reported as confirmed by Pine, including History Bar Tick
// executions. Realtime intrabar updates are NOT confirmed until the bar closes.
// This gate removes that historical/live mismatch for ENTRY and RE-ENTRY only.
bool executionEntryUpdate = barstate.ishistory or barstate.isconfirmed or (barstate.isrealtime and liveIntrabarEntries)


// Realtime execution clock. bar_index does NOT advance between ticks of a Daily bar,
// so a separate intrabar sequence is required for leave/retest/re-entry sequencing.
varip int liveUpdateSeq = 0
varip float livePrevPrice = na
varip string[] liveSeenRayKeys = array.new_string()
varip string[] liveSeenCheckpointKeys = array.new_string()
varip int liveMapEntriesSubmitted = 0
varip string liveMapStatus = "MAP WARM"
varip float liveMapLastCheckpoint = na

if barstate.isnew
    liveUpdateSeq := 0
    livePrevPrice := realClose
    array.clear(liveSeenRayKeys)
    array.clear(liveSeenCheckpointKeys)
    liveMapEntriesSubmitted := 0
    liveMapStatus := "MAP WATCH"
    liveMapLastCheckpoint := na

if barstate.isrealtime
    liveUpdateSeq += 1

f_live_segment_touches(_price, _tol) =>
    float _a = na(livePrevPrice) ? realClose : livePrevPrice
    float _lo = math.min(_a, realClose)
    float _hi = math.max(_a, realClose)
    _lo <= _price + _tol and _hi >= _price - _tol

f_market_target_reached(_dir, _target) =>
    bool _valid = not na(_target) and (_dir == 1 or _dir == -1)
    _valid and (
         barstate.isrealtime ?
             f_live_segment_touches(_target, 0.0) :
             (_dir == 1 ? realClose >= _target : realClose <= _target)
     )


//──────────────────────────────────────────────
// F6.1 — OANDA ORDER-FILL BRIDGE
// This does NOT change signal/route geometry or sizing.
// It only attaches the established TGIM OANDA JSON contract to actual strategy orders.
// TradingView alert: Order fills only | Message = {{strategy.order.alert_message}}
//──────────────────────────────────────────────
f_oanda_instrument() =>
    _base = str.upper(syminfo.basecurrency)
    _quote = str.upper(syminfo.currency)
    str.length(_base) == 3 and str.length(_quote) == 3 ? _base + "_" + _quote :
         str.replace_all(str.replace_all(str.upper(syminfo.ticker), "OANDA:", ""), ":", "_")




//──────────────────────────────────────────────
// 04B — PAIR PROFILE SELECTOR (declared early so saved champions own their exact test window)
// MANUAL = all ordinary inputs remain authoritative.
// AUTO/forced champion = saved pair profile is authoritative, including the 120-day
// historical validation span that originally produced the 47/47 and 51/51 controls
// (former Mapper 90-day calibration + 30-day forward audit, contiguous).
//──────────────────────────────────────────────
groupPairProfiles = "04B — PAIR PROFILE LIBRARY"
pairProfileMode = input.string("AUTO BY SYMBOL", "Pair Profile Mode",
     options=["MANUAL INPUTS","AUTO BY SYMBOL","EURUSD CHAMPION","AUDUSD CHAMPION"], group=groupPairProfiles,
     tooltip="MANUAL INPUTS = normal R/G/T controls and Backtest Window are live. AUTO/CHAMPION modes LOCK the saved pair profile and its exact 120-day champion validation span.")
showPairProfileStatus = input.bool(true, "Show Pair Profile Status", group=groupPairProfiles)
pairProfileTablePositionInput = input.string("Top Center", "Pair Profile Table Position", options=["Top Left","Top Center","Top Right","Middle Left","Middle Center","Middle Right","Bottom Left","Bottom Center","Bottom Right"], group=groupPairProfiles)

pairProfileSymbolKey = str.upper(syminfo.basecurrency + syminfo.currency)
int pairProfileId =
     pairProfileMode == "MANUAL INPUTS" ? 0 :
     pairProfileMode == "EURUSD CHAMPION" ? 1 :
     pairProfileMode == "AUDUSD CHAMPION" ? 2 :
     pairProfileSymbolKey == "EURUSD" ? 1 :
     pairProfileSymbolKey == "AUDUSD" ? 2 : 0
bool pairProfileActive = pairProfileId != 0
string pairProfileName = pairProfileId == 1 ? "EURUSD CHAMPION V1 47/47" : pairProfileId == 2 ? "AUDUSD CHAMPION V2 51/51" : "MANUAL / TUNING"

//──────────────────────────────────────────────
// 05A — BACKTEST WINDOW
// NORMAL Strategy Tester recent-window filter.
// IMPORTANT: rails, rays, pivots, legs, Guardian, and checkpoint registries keep
// calculating on all loaded history. Only NEW strategy entries are blocked
// outside the selected window, so the selected period keeps proper warm-up.
//──────────────────────────────────────────────
groupBacktestWindow = "05A — BACKTEST WINDOW"
backtestWindowMode = input.string("Last 120 Days", "Backtest Window",
     options=["Last 30 Days","Last 60 Days","Last 90 Days","Last 120 Days","Last 180 Days","Last 365 Days","All History","Custom"],
     group=groupBacktestWindow,
     tooltip="MANUAL mode uses this window. Saved EURUSD/AUDUSD champion modes intentionally lock the historical entry span to 120 calendar days, matching the former 90D calibration + 30D forward union that produced the champion totals.")
backtestCustomStart = input.time(timestamp("01 Jan 2026 00:00 +0000"), "Custom Start", group=groupBacktestWindow,
     active=backtestWindowMode == "Custom")
backtestCustomEnd = input.time(timestamp("31 Dec 2035 23:59 +0000"), "Custom End", group=groupBacktestWindow,
     active=backtestWindowMode == "Custom",
     tooltip="Custom End stops NEW entries after this time. A position already open is allowed to finish by TGIM's existing target logic.")
backtest30dBlockOffset = input.int(0, "30D Block Offset", minval=0, maxval=23, group=groupBacktestWindow,
     active=backtestWindowMode == "Last 30 Days",
     tooltip="Manual-mode forensic offset only. Saved champion profiles ignore this and use their exact 120-day validation span.")

int backtestMsPerDay = 24 * 60 * 60 * 1000
int backtestRollingDays =
     backtestWindowMode == "Last 30 Days" ? 30 :
     backtestWindowMode == "Last 60 Days" ? 60 :
     backtestWindowMode == "Last 90 Days" ? 90 :
     backtestWindowMode == "Last 120 Days" ? 120 :
     backtestWindowMode == "Last 180 Days" ? 180 :
     backtestWindowMode == "Last 365 Days" ? 365 : 0

int backtest30dShiftMs = backtestWindowMode == "Last 30 Days" ? backtest30dBlockOffset * 30 * backtestMsPerDay : 0
int championValidationDays = 120

int backtestWindowStart =
     pairProfileActive ? last_bar_time - championValidationDays * backtestMsPerDay :
     backtestWindowMode == "Custom" ? backtestCustomStart :
     backtestWindowMode == "All History" ? 0 :
     last_bar_time - backtest30dShiftMs - backtestRollingDays * backtestMsPerDay
int backtestWindowEnd =
     pairProfileActive ? last_bar_time :
     backtestWindowMode == "Custom" ? backtestCustomEnd :
     backtestWindowMode == "Last 30 Days" ? last_bar_time - backtest30dShiftMs :
     last_bar_time

bool backtestInWindow = pairProfileActive ?
     (time >= backtestWindowStart and time <= backtestWindowEnd) :
     backtestWindowMode == "All History" or (time >= backtestWindowStart and time <= backtestWindowEnd)
bool backtestCanEnter = backtestInWindow
// ULTRALEAN replacement for the former Mapper gate: champion profiles preserve the exact
// contiguous 120-day entry span without restoring the token-heavy calibration/forward tables.

//──────────────────────────────────────────────

//──────────────────────────────────────────────
// 06 — FOUNDATION DISPLAY removed in F4 for compiler headroom.
//──────────────────────────────────────────────


//──────────────────────────────────────────────
adxDiLength = 14
adxDiSmoothing = 14
adxStrongThreshold = 25.0

// 08A — R1-R10 HORIZONTAL TURN RAYS
// Each enabled R slot can independently show a rail and cast horizontal P/V rays.
// Per-slot ray toggles live in 08B — R1...R10.
// The consolidated ray engine below can use any Route-enabled R source as a checkpoint.
//──────────────────────────────────────────────
groupHmaCrossRays = "08A — R1-R10 HORIZONTAL TURN RAYS"
showHmaCrossingRays = input.bool(true, "Master Show R Horizontal Rays", group=groupHmaCrossRays)

hmaCrossRaysPerSide = input.int(2, "Closest Rays Per Side", minval=1, maxval=50, group=groupHmaCrossRays, active=showHmaCrossingRays,
     tooltip="Shows this many closest consolidated/standalone rays above price AND below price across enabled R slots.")
hmaCrossRegistryLimit = input.int(27, "Historical R Turns To Scan", minval=3, maxval=3000, group=groupHmaCrossRays)

averageShallowHmaClutter = input.bool(false, "Average Shallow Peak/Valley Clutter", group=groupHmaCrossRays,
     tooltip="Tightly grouped mixed peaks/valleys across enabled R sources are replaced by one blue averaged ray.")
hmaCrossClusterMaxBars = input.int(2, "Clutter Maximum Bars", minval=1, maxval=200, group=groupHmaCrossRays,
     active=averageShallowHmaClutter)
hmaCrossClusterMaxSpanPips = input.float(0.0, "Clutter Maximum Price Span (pips/ticks)", minval=0.0, step=0.1, group=groupHmaCrossRays,
     active=averageShallowHmaClutter)

hmaCrossRayWidth = input.int(1, "R Ray Width", minval=1, maxval=5, group=groupHmaCrossRays)
hmaCrossRayStyleInput = input.string("Solid", "R Ray Style", options=["Solid","Dashed","Dotted"], group=groupHmaCrossRays)

railTurnPeakColor = input.color(color.green, "Peak Ray Color", group=groupHmaCrossRays)
railTurnValleyColor = input.color(color.red, "Valley Ray Color", group=groupHmaCrossRays)
railTurnAverageColor = input.color(color.blue, "Averaged Clutter Ray Color", group=groupHmaCrossRays,
     active=averageShallowHmaClutter)

//──────────────────────────────────────────────
// 08A.1 — RAY CONTEXT CLASSIFIER
// Diagnostic only. Does NOT qualify or place trades.
// Structural regime = selected ray source rail across D / 12H / 8H / 6H / 4H.
// 1H is shown separately as the active nested context.
// 15m / 5m / 1m are compressed into a micro context.
// ADX/DI confirms, conflicts with, or is mixed versus the structural regime.
//──────────────────────────────────────────────
groupRayContext = "08A.1 — RAY CONTEXT CLASSIFIER"
enableRayContextClassifier = input.bool(false, "Classify New Visible Rays", group=groupRayContext,
     tooltip="Labels each newly visible peak/valley ray as CONTINUATION, RETRACEMENT, or TRANSITION using the driving rail's higher-timeframe regime. Diagnostic only; it does not create trades.")
structuralRegimeThreshold = input.float(8.0, "Structural Regime Score Threshold", minval=1.0, maxval=32.0, step=1.0, group=groupRayContext,
     tooltip="D/12H/8H/6H/4H are weighted 5/4/3/2/2. A↑/B↓ count as strong states; B↑/A↓ count as transitional states. Higher threshold demands broader agreement before calling BULLISH or BEARISH.")
contextAdxMin = input.float(20.0, "ADX Minimum For Directional Confirmation", minval=0.0, maxval=100.0, step=1.0, group=groupRayContext)

//──────────────────────────────────────────────
// 08A.2A — ZAG FLIP TRADE LOGIC v1
// PURE isolation test. Confirmed ZAG turn only; no Guardian/ADX/dot/ray target/TP/SL.
// AUTO SHOWN ZAG selects the first enabled R whose Show ZAG toggle is ON.
// Manual R1-R10 selection is available when more than one ZAG is displayed.
//──────────────────────────────────────────────
groupZagFlip = "08A.2A — ZAG FLIP TRADE LOGIC"
enableZagFlipTradeLogic = input.bool(true, "Enable ZAG FLIP — Exclusive", group=groupZagFlip,
     tooltip="ON disables the legacy Pivot-Ray and Leg-Shuttle order engines for a clean ZAG-only test. Valley turn -> LONG; peak turn -> SHORT; opposite turn atomically reverses.")
zagFlipRailSlot = input.string("AUTO CHART TF", "ZAG Flip Source",
     options=["AUTO CHART TF","AUTO SHOWN ZAG","R1","R2","R3","R4","R5","R6","R7","R8","R9","R10"], group=groupZagFlip,
     active=enableZagFlipTradeLogic,
     tooltip="AUTO CHART TF matches the chart to its fixed R bay (5m=R9, 15m=R8, 4H=R6). AUTO SHOWN ZAG uses the first enabled displayed ZAG.")
zagFlipAllowLongs = input.bool(true, "Allow LONG On Confirmed Valley Turn", group=groupZagFlip, active=enableZagFlipTradeLogic)
zagFlipAllowShorts = input.bool(true, "Allow SHORT On Confirmed Peak Turn", group=groupZagFlip, active=enableZagFlipTradeLogic)
forcePlotTradedZag = input.bool(true, "Always Plot The ZAG Being Traded", group=groupZagFlip, active=enableZagFlipTradeLogic,
     tooltip="ON forces the exact R ZAG selected by ZAG Flip Source to draw even when that R's ordinary Show ZAG toggle is OFF. Visual only; does not change entries, exits, source selection or sizing.")
showZagFlipMarkers = input.bool(true, "Show ZAG FLIP Trade Plot Labels", group=groupZagFlip, active=enableZagFlipTradeLogic,
     tooltip="DISPLAY ONLY. Labels the current bar/update where the selected ZAG turn is confirmed.")
showOnlyLastTwoZagFlipLabels = input.bool(false, "Only Keep Last 2 ZAG FLIP Trade Labels", group=groupZagFlip,
     active=enableZagFlipTradeLogic and showZagFlipMarkers,
     tooltip="OFF = keep all custom ZAG FLIP labels. ON = retain only the latest two. Orders/statistics are unchanged.")

zagFlipExecutionWebhookEnabled = input.bool(true, "Enable Render Webhook Execution Alerts", group=groupZagFlip,
     tooltip="LIVE EXECUTION. Sends the broker-compatible TGIM JSON payload to TradingView alert() only when the current ZAG flip passes the actual operational entry gates. Use this with a TradingView 'Any alert() function call' alert and your Render /webhook URL.")


//──────────────────────────────────────────────

//──────────────────────────────────────────────
// 08A.2A.1 — PIPMAN PHYSICAL MERGE FILTER
// 0 gap = actual convergence. X-touch alone does NOT count as merge.
//──────────────────────────────────────────────
groupPipmanMerge = "08A.2A.1 — PIPMAN PHYSICAL MERGE FILTER"
pipmanMergeEnable = input.bool(true, "Enable PIPMAN Physical Merge Filter", group=groupPipmanMerge)
pipmanMergeMaxGapTicks = input.float(0.0, "Max RAW↔ZAG Separation (ticks)", minval=0.0, maxval=100.0, step=0.25, group=groupPipmanMerge)
pipmanMergeMaxTrajectoryMismatchTicks = input.float(0.25, "Max Trajectory Mismatch (ticks / bar)", minval=0.0, maxval=100.0, step=0.25, group=groupPipmanMerge)
pipmanMergeRequiredBars = input.int(2, "Required Consecutive Merged Bars BEFORE Turn", minval=1, maxval=20, group=groupPipmanMerge)
pipmanMergeRequireSameTravel = input.bool(true, "Require Same Travel Direction", group=groupPipmanMerge)
pipmanMergeCrossDoesNotCount = input.bool(true, "A Crossing / X-Touch Does NOT Count As Merge", group=groupPipmanMerge)
pipmanMergeShowSkipped = input.bool(true, "Show PIPMAN MERGE SKIP Labels", group=groupPipmanMerge)
pipmanMergeShowTable = input.bool(true, "Show PIPMAN Diagnostic Table", group=groupPipmanMerge)
pipmanMergeTablePositionInput = input.string("Bottom Left", "PIPMAN Table Position", options=["Top Left","Top Center","Top Right","Middle Left","Middle Center","Middle Right","Bottom Left","Bottom Center","Bottom Right"], group=groupPipmanMerge)

//──────────────────────────────────────────────
// 08A.2 — RETAINED RAY / STACK / ROLE ANALYTICS
// Old Pivot-Ray / Previous-Ray / Pac-Man / Leg-Shuttle ORDER language is retired.
// Upstream calculations remain available for research and future refinement.
//──────────────────────────────────────────────
enablePivotRayTradeLogicInput = false
enablePivotRayTradeLogic = false
pivotTargetScope = "Any Route R"
pivotTradeClusters = false
pivotAllowLongs = false
pivotAllowShorts = false
pivotEntryQualification = "Delayed Confirmation"
pivotMinEntryStack = 4
pivotStackLookback = input.int(38, "Ray-Origin Dot Stack Lookback", minval=1, maxval=50, group="08A.2 — RAY / STACK ANALYTICS")
pivotStackTolerance = input.float(2.0, "Ray-Origin Dot Stack Tolerance (pips/ticks)", minval=0.0, step=0.1, group="08A.2 — RAY / STACK ANALYTICS")
showPivotTradeTarget = false
showPivotTradeMarkers = false

checkpointRouteMode = "One Leg Only"
guardianRailSlot = "R1"
guardianIndependentProfile = false
guardianProfileType = "WMA"
guardianProfileLen = 2
guardianBreakDefinition = "Guardian Direction Flip"
triggerRailSlot = "R1"
triggerIndependentProfile = false
triggerProfileType = "WMA"
triggerProfileLen = 2
guardianBreakBuffer = 0.0
checkpointRetestTolerance = 0.0
checkpointLeaveDistance = 0.0
checkpointRequireDiConfirm = false
checkpointRequireAdx = false
checkpointMinAdx = 20.0
showCheckpointDecisionLines = false

// 08B — R1 ... R10 UNIVERSAL RAIL SLOTS
// Every slot can be HMA / WMA / KS / EMA, on its own timeframe and length.
// Every slot owns its RAW rail display, Working Rail choice, ZAG display controls, and horizontal P/V route rays.
// Guardian and Trigger roles are assigned above in 08A.2B; they are NOT hard-coded to HMA.
//──────────────────────────────────────────────
groupR1 = "08B.R1 — 1W RAIL SLOT"
r1_on = input.bool(true, "Enable 1W (R1)", group=groupR1)
string r1_tf = "W"  // FIXED 1W timeframe bay
r1_type = input.string("WMA", "Rail Type", options=["HMA","WMA","KS","EMA"], group=groupR1)
r1_len = input.int(2, "Rail Length", minval=1, group=groupR1)
r1_useAdxDi = input.bool(false, "Use ADX/DI In Trade Logic", group=groupR1,
     tooltip="OFF = no effect. ON = this 1W slot is trade-qualified only when ADX is at/above its minimum and DI direction agrees with the working-rail direction.")
r1_adxMin = input.float(20.0, "ADX Minimum", minval=0.0, maxval=100.0, step=1.0, group=groupR1, active=r1_useAdxDi)
r1_workingRail = input.string("RAW", "Working Rail", options=["RAW","ZAG"], group=groupR1,
     tooltip="RAW = the selected HMA/WMA/KS/EMA rail itself. ZAG = this R slot's causal turn-to-turn ZAG becomes the working rail used by Guardian/Trigger/route logic.")
r1_useZag = r1_workingRail == "ZAG"
r1_showLine = input.bool(true, "Show Raw Rail Line", group=groupR1,
     tooltip="Display only. The working rail choice above controls logic.")
r1_showDots = input.bool(false, "Show Raw Rail Dots", group=groupR1,
     tooltip="Display only.")
r1_dotWidth = input.int(4, "Raw Dot Size", minval=1, maxval=5, group=groupR1, active=r1_showDots)
r1_showZag = input.bool(false, "Show ZAG", group=groupR1,
     tooltip="Display this R slot's confirmed turn-to-turn ZAG plus the causal active projection.")
r1_zagSegments = input.int(16, "ZAG Segments", minval=1, maxval=99, group=groupR1, active=r1_showZag,
     tooltip="How many completed ZAG legs this R slot retains on screen.")
r1_zagWidth = input.int(2, "ZAG Width", minval=1, maxval=4, group=groupR1, active=r1_showZag)
r1_showRays = input.bool(true, "Horizontal P/V Rays / Route Source", group=groupR1,
     tooltip="ON = this R slot casts horizontal peak/valley checkpoints and can participate in route/entry logic.")

groupR2 = "08B.R2 — 1D RAIL SLOT"
r2_on = input.bool(true, "Enable 1D (R2)", group=groupR2)
string r2_tf = "D"  // FIXED 1D timeframe bay
r2_type = input.string("WMA", "Rail Type", options=["HMA","WMA","KS","EMA"], group=groupR2)
r2_len = input.int(2, "Rail Length", minval=1, group=groupR2)
r2_useAdxDi = input.bool(false, "Use ADX/DI In Trade Logic", group=groupR2,
     tooltip="OFF = no effect. ON = this 1D slot is trade-qualified only when ADX is at/above its minimum and DI direction agrees with the working-rail direction.")
r2_adxMin = input.float(20.0, "ADX Minimum", minval=0.0, maxval=100.0, step=1.0, group=groupR2, active=r2_useAdxDi)
r2_workingRail = input.string("RAW", "Working Rail", options=["RAW","ZAG"], group=groupR2,
     tooltip="RAW = the selected HMA/WMA/KS/EMA rail itself. ZAG = this R slot's causal turn-to-turn ZAG becomes the working rail used by Guardian/Trigger/route logic.")
r2_useZag = r2_workingRail == "ZAG"
r2_showLine = input.bool(false, "Show Raw Rail Line", group=groupR2,
     tooltip="Display only. The working rail choice above controls logic.")
r2_showDots = input.bool(false, "Show Raw Rail Dots", group=groupR2,
     tooltip="Display only.")
r2_dotWidth = input.int(4, "Raw Dot Size", minval=1, maxval=5, group=groupR2, active=r2_showDots)
r2_showZag = input.bool(false, "Show ZAG", group=groupR2,
     tooltip="Display this R slot's confirmed turn-to-turn ZAG plus the causal active projection.")
r2_zagSegments = input.int(12, "ZAG Segments", minval=1, maxval=99, group=groupR2, active=r2_showZag,
     tooltip="How many completed ZAG legs this R slot retains on screen.")
r2_zagWidth = input.int(2, "ZAG Width", minval=1, maxval=4, group=groupR2, active=r2_showZag)
r2_showRays = input.bool(true, "Horizontal P/V Rays / Route Source", group=groupR2,
     tooltip="ON = this R slot casts horizontal peak/valley checkpoints and can participate in route/entry logic.")

groupR3 = "08B.R3 — 12H RAIL SLOT"
r3_on = input.bool(false, "Enable 12H (R3)", group=groupR3)
string r3_tf = "720"  // FIXED 12H timeframe bay
r3_type = input.string("HMA", "Rail Type", options=["HMA","WMA","KS","EMA"], group=groupR3)
r3_len = input.int(28, "Rail Length", minval=1, group=groupR3)
r3_useAdxDi = input.bool(false, "Use ADX/DI In Trade Logic", group=groupR3,
     tooltip="OFF = no effect. ON = this 12H slot is trade-qualified only when ADX is at/above its minimum and DI direction agrees with the working-rail direction.")
r3_adxMin = input.float(20.0, "ADX Minimum", minval=0.0, maxval=100.0, step=1.0, group=groupR3, active=r3_useAdxDi)
r3_workingRail = input.string("RAW", "Working Rail", options=["RAW","ZAG"], group=groupR3,
     tooltip="RAW = the selected HMA/WMA/KS/EMA rail itself. ZAG = this R slot's causal turn-to-turn ZAG becomes the working rail used by Guardian/Trigger/route logic.")
r3_useZag = r3_workingRail == "ZAG"
r3_showLine = input.bool(false, "Show Raw Rail Line", group=groupR3,
     tooltip="Display only. The working rail choice above controls logic.")
r3_showDots = input.bool(false, "Show Raw Rail Dots", group=groupR3,
     tooltip="Display only.")
r3_dotWidth = input.int(1, "Raw Dot Size", minval=1, maxval=5, group=groupR3, active=r3_showDots)
r3_showZag = input.bool(false, "Show ZAG", group=groupR3,
     tooltip="Display this R slot's confirmed turn-to-turn ZAG plus the causal active projection.")
r3_zagSegments = input.int(12, "ZAG Segments", minval=1, maxval=99, group=groupR3, active=r3_showZag,
     tooltip="How many completed ZAG legs this R slot retains on screen.")
r3_zagWidth = input.int(2, "ZAG Width", minval=1, maxval=4, group=groupR3, active=r3_showZag)
r3_showRays = input.bool(false, "Horizontal P/V Rays / Route Source", group=groupR3,
     tooltip="ON = this R slot casts horizontal peak/valley checkpoints and can participate in route/entry logic.")

groupR4 = "08B.R4 — 8H RAIL SLOT"
r4_on = input.bool(false, "Enable 8H (R4)", group=groupR4)
string r4_tf = "480"  // FIXED 8H timeframe bay
r4_type = input.string("WMA", "Rail Type", options=["HMA","WMA","KS","EMA"], group=groupR4)
r4_len = input.int(9, "Rail Length", minval=1, group=groupR4)
r4_useAdxDi = input.bool(false, "Use ADX/DI In Trade Logic", group=groupR4,
     tooltip="OFF = no effect. ON = this 8H slot is trade-qualified only when ADX is at/above its minimum and DI direction agrees with the working-rail direction.")
r4_adxMin = input.float(20.0, "ADX Minimum", minval=0.0, maxval=100.0, step=1.0, group=groupR4, active=r4_useAdxDi)
r4_workingRail = input.string("RAW", "Working Rail", options=["RAW","ZAG"], group=groupR4,
     tooltip="RAW = the selected HMA/WMA/KS/EMA rail itself. ZAG = this R slot's causal turn-to-turn ZAG becomes the working rail used by Guardian/Trigger/route logic.")
r4_useZag = r4_workingRail == "ZAG"
r4_showLine = input.bool(false, "Show Raw Rail Line", group=groupR4,
     tooltip="Display only. The working rail choice above controls logic.")
r4_showDots = input.bool(false, "Show Raw Rail Dots", group=groupR4,
     tooltip="Display only.")
r4_dotWidth = input.int(1, "Raw Dot Size", minval=1, maxval=5, group=groupR4, active=r4_showDots)
r4_showZag = input.bool(false, "Show ZAG", group=groupR4,
     tooltip="Display this R slot's confirmed turn-to-turn ZAG plus the causal active projection.")
r4_zagSegments = input.int(12, "ZAG Segments", minval=1, maxval=99, group=groupR4, active=r4_showZag,
     tooltip="How many completed ZAG legs this R slot retains on screen.")
r4_zagWidth = input.int(2, "ZAG Width", minval=1, maxval=4, group=groupR4, active=r4_showZag)
r4_showRays = input.bool(false, "Horizontal P/V Rays / Route Source", group=groupR4,
     tooltip="ON = this R slot casts horizontal peak/valley checkpoints and can participate in route/entry logic.")

groupR5 = "08B.R5 — 6H RAIL SLOT"
r5_on = input.bool(false, "Enable 6H (R5)", group=groupR5)
string r5_tf = "360"  // FIXED 6H timeframe bay
r5_type = input.string("KS", "Rail Type", options=["HMA","WMA","KS","EMA"], group=groupR5)
r5_len = input.int(27, "Rail Length", minval=1, group=groupR5)
r5_useAdxDi = input.bool(false, "Use ADX/DI In Trade Logic", group=groupR5,
     tooltip="OFF = no effect. ON = this 6H slot is trade-qualified only when ADX is at/above its minimum and DI direction agrees with the working-rail direction.")
r5_adxMin = input.float(20.0, "ADX Minimum", minval=0.0, maxval=100.0, step=1.0, group=groupR5, active=r5_useAdxDi)
r5_workingRail = input.string("RAW", "Working Rail", options=["RAW","ZAG"], group=groupR5,
     tooltip="RAW = the selected HMA/WMA/KS/EMA rail itself. ZAG = this R slot's causal turn-to-turn ZAG becomes the working rail used by Guardian/Trigger/route logic.")
r5_useZag = r5_workingRail == "ZAG"
r5_showLine = input.bool(false, "Show Raw Rail Line", group=groupR5,
     tooltip="Display only. The working rail choice above controls logic.")
r5_showDots = input.bool(false, "Show Raw Rail Dots", group=groupR5,
     tooltip="Display only.")
r5_dotWidth = input.int(3, "Raw Dot Size", minval=1, maxval=5, group=groupR5, active=r5_showDots)
r5_showZag = input.bool(false, "Show ZAG", group=groupR5,
     tooltip="Display this R slot's confirmed turn-to-turn ZAG plus the causal active projection.")
r5_zagSegments = input.int(9, "ZAG Segments", minval=1, maxval=99, group=groupR5, active=r5_showZag,
     tooltip="How many completed ZAG legs this R slot retains on screen.")
r5_zagWidth = input.int(2, "ZAG Width", minval=1, maxval=4, group=groupR5, active=r5_showZag)
r5_showRays = input.bool(false, "Horizontal P/V Rays / Route Source", group=groupR5,
     tooltip="ON = this R slot casts horizontal peak/valley checkpoints and can participate in route/entry logic.")

groupR6 = "08B.R6 — 4H RAIL SLOT"
r6_on = input.bool(true, "Enable 4H (R6)", group=groupR6)
string r6_tf = "240"  // FIXED 4H timeframe bay
r6_type = input.string("WMA", "Rail Type", options=["HMA","WMA","KS","EMA"], group=groupR6)
r6_len = input.int(2, "Rail Length", minval=1, group=groupR6)
r6_useAdxDi = input.bool(false, "Use ADX/DI In Trade Logic", group=groupR6,
     tooltip="OFF = no effect. ON = this 4H slot is trade-qualified only when ADX is at/above its minimum and DI direction agrees with the working-rail direction.")
r6_adxMin = input.float(20.0, "ADX Minimum", minval=0.0, maxval=100.0, step=1.0, group=groupR6, active=r6_useAdxDi)
r6_workingRail = input.string("RAW", "Working Rail", options=["RAW","ZAG"], group=groupR6,
     tooltip="RAW = the selected HMA/WMA/KS/EMA rail itself. ZAG = this R slot's causal turn-to-turn ZAG becomes the working rail used by Guardian/Trigger/route logic.")
r6_useZag = r6_workingRail == "ZAG"
r6_showLine = input.bool(false, "Show Raw Rail Line", group=groupR6,
     tooltip="Display only. The working rail choice above controls logic.")
r6_showDots = input.bool(false, "Show Raw Rail Dots", group=groupR6,
     tooltip="Display only.")
r6_dotWidth = input.int(1, "Raw Dot Size", minval=1, maxval=5, group=groupR6, active=r6_showDots)
r6_showZag = input.bool(false, "Show ZAG", group=groupR6,
     tooltip="Display this R slot's confirmed turn-to-turn ZAG plus the causal active projection.")
r6_zagSegments = input.int(20, "ZAG Segments", minval=1, maxval=99, group=groupR6, active=r6_showZag,
     tooltip="How many completed ZAG legs this R slot retains on screen.")
r6_zagWidth = input.int(2, "ZAG Width", minval=1, maxval=4, group=groupR6, active=r6_showZag)
r6_showRays = input.bool(true, "Horizontal P/V Rays / Route Source", group=groupR6,
     tooltip="ON = this R slot casts horizontal peak/valley checkpoints and can participate in route/entry logic.")

groupR7 = "08B.R7 — 1H RAIL SLOT"
r7_on = input.bool(true, "Enable 1H (R7)", group=groupR7)
string r7_tf = "60"  // FIXED 1H timeframe bay
r7_type = input.string("KS", "Rail Type", options=["HMA","WMA","KS","EMA"], group=groupR7)
r7_len = input.int(27, "Rail Length", minval=1, group=groupR7)
r7_useAdxDi = input.bool(false, "Use ADX/DI In Trade Logic", group=groupR7,
     tooltip="OFF = no effect. ON = this 1H slot is trade-qualified only when ADX is at/above its minimum and DI direction agrees with the working-rail direction.")
r7_adxMin = input.float(20.0, "ADX Minimum", minval=0.0, maxval=100.0, step=1.0, group=groupR7, active=r7_useAdxDi)
r7_workingRail = input.string("RAW", "Working Rail", options=["RAW","ZAG"], group=groupR7,
     tooltip="RAW = the selected HMA/WMA/KS/EMA rail itself. ZAG = this R slot's causal turn-to-turn ZAG becomes the working rail used by Guardian/Trigger/route logic.")
r7_useZag = r7_workingRail == "ZAG"
r7_showLine = input.bool(false, "Show Raw Rail Line", group=groupR7,
     tooltip="Display only. The working rail choice above controls logic.")
r7_showDots = input.bool(false, "Show Raw Rail Dots", group=groupR7,
     tooltip="Display only.")
r7_dotWidth = input.int(3, "Raw Dot Size", minval=1, maxval=5, group=groupR7, active=r7_showDots)
r7_showZag = input.bool(false, "Show ZAG", group=groupR7,
     tooltip="Display this R slot's confirmed turn-to-turn ZAG plus the causal active projection.")
r7_zagSegments = input.int(9, "ZAG Segments", minval=1, maxval=99, group=groupR7, active=r7_showZag,
     tooltip="How many completed ZAG legs this R slot retains on screen.")
r7_zagWidth = input.int(2, "ZAG Width", minval=1, maxval=4, group=groupR7, active=r7_showZag)
r7_showRays = input.bool(true, "Horizontal P/V Rays / Route Source", group=groupR7,
     tooltip="ON = this R slot casts horizontal peak/valley checkpoints and can participate in route/entry logic.")

groupR8 = "08B.R8 — 15m RAIL SLOT"
r8_on = input.bool(true, "Enable 15m (R8)", group=groupR8)
string r8_tf = "15"  // FIXED 15m timeframe bay
r8_type = input.string("KS", "Rail Type", options=["HMA","WMA","KS","EMA"], group=groupR8)
r8_len = input.int(28, "Rail Length", minval=1, group=groupR8)
r8_useAdxDi = input.bool(false, "Use ADX/DI In Trade Logic", group=groupR8,
     tooltip="OFF = no effect. ON = this 15m slot is trade-qualified only when ADX is at/above its minimum and DI direction agrees with the working-rail direction.")
r8_adxMin = input.float(15.0, "ADX Minimum", minval=0.0, maxval=100.0, step=1.0, group=groupR8, active=r8_useAdxDi)
r8_workingRail = input.string("RAW", "Working Rail", options=["RAW","ZAG"], group=groupR8,
     tooltip="RAW = the selected HMA/WMA/KS/EMA rail itself. ZAG = this R slot's causal turn-to-turn ZAG becomes the working rail used by Guardian/Trigger/route logic.")
r8_useZag = r8_workingRail == "ZAG"
r8_showLine = input.bool(false, "Show Raw Rail Line", group=groupR8,
     tooltip="Display only. The working rail choice above controls logic.")
r8_showDots = input.bool(false, "Show Raw Rail Dots", group=groupR8,
     tooltip="Display only.")
r8_dotWidth = input.int(1, "Raw Dot Size", minval=1, maxval=5, group=groupR8, active=r8_showDots)
r8_showZag = input.bool(false, "Show ZAG", group=groupR8,
     tooltip="Display this R slot's confirmed turn-to-turn ZAG plus the causal active projection.")
r8_zagSegments = input.int(12, "ZAG Segments", minval=1, maxval=99, group=groupR8, active=r8_showZag,
     tooltip="How many completed ZAG legs this R slot retains on screen.")
r8_zagWidth = input.int(2, "ZAG Width", minval=1, maxval=4, group=groupR8, active=r8_showZag)
r8_showRays = input.bool(true, "Horizontal P/V Rays / Route Source", group=groupR8,
     tooltip="ON = this R slot casts horizontal peak/valley checkpoints and can participate in route/entry logic.")

groupR9 = "08B.R9 — 5m RAIL SLOT"
r9_on = input.bool(true, "Enable 5m (R9)", group=groupR9)
string r9_tf = "5"  // FIXED 5m timeframe bay
r9_type = input.string("KS", "Rail Type", options=["HMA","WMA","KS","EMA"], group=groupR9)
r9_len = input.int(27, "Rail Length", minval=1, group=groupR9)
r9_useAdxDi = input.bool(false, "Use ADX/DI In Trade Logic", group=groupR9,
     tooltip="OFF = no effect. ON = this 5m slot is trade-qualified only when ADX is at/above its minimum and DI direction agrees with the working-rail direction.")
r9_adxMin = input.float(40.0, "ADX Minimum", minval=0.0, maxval=100.0, step=1.0, group=groupR9, active=r9_useAdxDi)
r9_workingRail = input.string("RAW", "Working Rail", options=["RAW","ZAG"], group=groupR9,
     tooltip="RAW = the selected HMA/WMA/KS/EMA rail itself. ZAG = this R slot's causal turn-to-turn ZAG becomes the working rail used by Guardian/Trigger/route logic.")
r9_useZag = r9_workingRail == "ZAG"
r9_showLine = input.bool(false, "Show Raw Rail Line", group=groupR9,
     tooltip="Display only. The working rail choice above controls logic.")
r9_showDots = input.bool(false, "Show Raw Rail Dots", group=groupR9,
     tooltip="Display only.")
r9_dotWidth = input.int(1, "Raw Dot Size", minval=1, maxval=5, group=groupR9, active=r9_showDots)
r9_showZag = input.bool(false, "Show ZAG", group=groupR9,
     tooltip="Display this R slot's confirmed turn-to-turn ZAG plus the causal active projection.")
r9_zagSegments = input.int(12, "ZAG Segments", minval=1, maxval=99, group=groupR9, active=r9_showZag,
     tooltip="How many completed ZAG legs this R slot retains on screen.")
r9_zagWidth = input.int(2, "ZAG Width", minval=1, maxval=4, group=groupR9, active=r9_showZag)
r9_showRays = input.bool(true, "Horizontal P/V Rays / Route Source", group=groupR9,
     tooltip="ON = this R slot casts horizontal peak/valley checkpoints and can participate in route/entry logic.")

groupR10 = "08B.R10 — 1m RAIL SLOT"
r10_on = input.bool(true, "Enable 1m (R10)", group=groupR10)
string r10_tf = "1"  // FIXED 1m timeframe bay
r10_type = input.string("KS", "Rail Type", options=["HMA","WMA","KS","EMA"], group=groupR10)
r10_len = input.int(5, "Rail Length", minval=1, group=groupR10)
r10_useAdxDi = input.bool(false, "Use ADX/DI In Trade Logic", group=groupR10,
     tooltip="OFF = no effect. ON = this 1m slot is trade-qualified only when ADX is at/above its minimum and DI direction agrees with the working-rail direction.")
r10_adxMin = input.float(1.0, "ADX Minimum", minval=0.0, maxval=100.0, step=1.0, group=groupR10, active=r10_useAdxDi)
r10_workingRail = input.string("RAW", "Working Rail", options=["RAW","ZAG"], group=groupR10,
     tooltip="RAW = the selected HMA/WMA/KS/EMA rail itself. ZAG = this R slot's causal turn-to-turn ZAG becomes the working rail used by Guardian/Trigger/route logic.")
r10_useZag = r10_workingRail == "ZAG"
r10_showLine = input.bool(false, "Show Raw Rail Line", group=groupR10,
     tooltip="Display only. The working rail choice above controls logic.")
r10_showDots = input.bool(false, "Show Raw Rail Dots", group=groupR10,
     tooltip="Display only.")
r10_dotWidth = input.int(1, "Raw Dot Size", minval=1, maxval=5, group=groupR10, active=r10_showDots)
r10_showZag = input.bool(false, "Show ZAG", group=groupR10,
     tooltip="Display this R slot's confirmed turn-to-turn ZAG plus the causal active projection.")
r10_zagSegments = input.int(12, "ZAG Segments", minval=1, maxval=99, group=groupR10, active=r10_showZag,
     tooltip="How many completed ZAG legs this R slot retains on screen.")
r10_zagWidth = input.int(2, "ZAG Width", minval=1, maxval=4, group=groupR10, active=r10_showZag)
r10_showRays = input.bool(true, "Horizontal P/V Rays / Route Source", group=groupR10,
     tooltip="ON = this R slot casts horizontal peak/valley checkpoints and can participate in route/entry logic.")

//──────────────────────────────────────────────
//──────────────────────────────────────────────
// 08C — PAIR PROFILE LIBRARY
//
// Pine cannot permanently rewrite input() values per symbol. Instead, the existing
// inputs remain the MANUAL tuning surface and this layer resolves EFFECTIVE settings.
// AUTO BY SYMBOL selects the saved pair profile; unsupported symbols use MANUAL inputs.
//
// Seed profiles:
//   EURUSD CHAMPION V1 = supplied GT47 47/47 control geometry.
//   AUDUSD CHAMPION V2 = 51/51 control captured 2026-08-29: R1 EMA2 RAW G+T; R2 KS2 RAW; R6 HMA27 ZAG; R7 KS27 RAW; R8 KS27 RAW; R9 KS27 RAW; R10 KS2 RAW.
//
// The profile bank is intentionally centralized here so Sweeper winners can be pasted
// into one place without rewriting the trade engine.
//──────────────────────────────────────────────
// Pair Profile selector is declared above 05A so it can also own the exact champion validation window.

// Manual-input accessors. These preserve the existing UI as the tuning surface.
f_manual_r_on(_s) =>
     _s == 1 ? r1_on : _s == 2 ? r2_on : _s == 3 ? r3_on : _s == 4 ? r4_on : _s == 5 ? r5_on :
     _s == 6 ? r6_on : _s == 7 ? r7_on : _s == 8 ? r8_on : _s == 9 ? r9_on : r10_on
f_manual_r_type(_s) =>
     _s == 1 ? r1_type : _s == 2 ? r2_type : _s == 3 ? r3_type : _s == 4 ? r4_type : _s == 5 ? r5_type :
     _s == 6 ? r6_type : _s == 7 ? r7_type : _s == 8 ? r8_type : _s == 9 ? r9_type : r10_type
f_manual_r_len(_s) =>
     _s == 1 ? r1_len : _s == 2 ? r2_len : _s == 3 ? r3_len : _s == 4 ? r4_len : _s == 5 ? r5_len :
     _s == 6 ? r6_len : _s == 7 ? r7_len : _s == 8 ? r8_len : _s == 9 ? r9_len : r10_len
f_manual_r_working(_s) =>
     _s == 1 ? r1_workingRail : _s == 2 ? r2_workingRail : _s == 3 ? r3_workingRail : _s == 4 ? r4_workingRail : _s == 5 ? r5_workingRail :
     _s == 6 ? r6_workingRail : _s == 7 ? r7_workingRail : _s == 8 ? r8_workingRail : _s == 9 ? r9_workingRail : r10_workingRail
f_manual_r_rays(_s) =>
     _s == 1 ? r1_showRays : _s == 2 ? r2_showRays : _s == 3 ? r3_showRays : _s == 4 ? r4_showRays : _s == 5 ? r5_showRays :
     _s == 6 ? r6_showRays : _s == 7 ? r7_showRays : _s == 8 ? r8_showRays : _s == 9 ? r9_showRays : r10_showRays
f_manual_r_use_adx(_s) =>
     _s == 1 ? r1_useAdxDi : _s == 2 ? r2_useAdxDi : _s == 3 ? r3_useAdxDi : _s == 4 ? r4_useAdxDi : _s == 5 ? r5_useAdxDi :
     _s == 6 ? r6_useAdxDi : _s == 7 ? r7_useAdxDi : _s == 8 ? r8_useAdxDi : _s == 9 ? r9_useAdxDi : r10_useAdxDi
f_manual_r_adx_min(_s) =>
     _s == 1 ? r1_adxMin : _s == 2 ? r2_adxMin : _s == 3 ? r3_adxMin : _s == 4 ? r4_adxMin : _s == 5 ? r5_adxMin :
     _s == 6 ? r6_adxMin : _s == 7 ? r7_adxMin : _s == 8 ? r8_adxMin : _s == 9 ? r9_adxMin : r10_adxMin

// Saved champion geometry. Pair-specific branches are separate even where V1 values
// currently match, so one pair can be changed later without touching the other.
f_saved_r_on(_profile, _s) =>
     (_profile == 1 or _profile == 2) ? (_s == 1 or _s == 2 or _s == 6 or _s == 7 or _s == 8 or _s == 9 or _s == 10) : false
f_saved_r_type(_profile, _s) =>
     _profile == 1 ? (_s == 1 ? "WMA" : _s == 2 ? "WMA" : _s == 3 ? "HMA" : _s == 4 ? "WMA" : _s == 5 ? "KS" : _s == 6 ? "WMA" : "KS") :
     _profile == 2 ? (_s == 1 ? "EMA" : _s == 2 ? "KS" : _s == 3 ? "HMA" : _s == 4 ? "WMA" : _s == 5 ? "KS" : _s == 6 ? "HMA" : "KS") : "HMA"
f_saved_r_len(_profile, _s) =>
     _profile == 1 ? (_s == 1 ? 2 : _s == 2 ? 2 : _s == 3 ? 28 : _s == 4 ? 9 : _s == 5 ? 27 : _s == 6 ? 2 : _s == 7 ? 27 : _s == 8 ? 28 : _s == 9 ? 27 : 5) :
     _profile == 2 ? (_s == 1 ? 2 : _s == 2 ? 2 : _s == 3 ? 28 : _s == 4 ? 9 : _s == 5 ? 27 : _s == 6 ? 27 : _s == 7 ? 27 : _s == 8 ? 27 : _s == 9 ? 27 : 2) : 1
f_saved_r_working(_profile, _s) => _profile == 2 and _s == 6 ? "ZAG" : (_profile == 1 or _profile == 2) ? "RAW" : "RAW"
f_saved_r_rays(_profile, _s) =>
     (_profile == 1 or _profile == 2) ? (_s == 1 or _s == 2 or _s == 6 or _s == 7 or _s == 8 or _s == 9 or _s == 10) : false
f_saved_r_use_adx(_profile, _s) => false
f_saved_r_adx_min(_profile, _s) =>
     _s == 8 ? 15.0 : _s == 9 ? 40.0 : _s == 10 ? 1.0 : 20.0
f_pair_r_on(_s) => pairProfileActive ? f_saved_r_on(pairProfileId, _s) : f_manual_r_on(_s)
f_pair_r_type(_s) => pairProfileActive ? f_saved_r_type(pairProfileId, _s) : f_manual_r_type(_s)
f_pair_r_len(_s) => pairProfileActive ? f_saved_r_len(pairProfileId, _s) : f_manual_r_len(_s)
f_pair_r_working(_s) => pairProfileActive ? f_saved_r_working(pairProfileId, _s) : f_manual_r_working(_s)
f_pair_r_use_zag(_s) => f_pair_r_working(_s) == "ZAG"
f_pair_r_rays(_s) => pairProfileActive ? f_saved_r_rays(pairProfileId, _s) : f_manual_r_rays(_s)
f_pair_r_use_adx(_s) => pairProfileActive ? f_saved_r_use_adx(pairProfileId, _s) : f_manual_r_use_adx(_s)
f_pair_r_adx_min(_s) => pairProfileActive ? f_saved_r_adx_min(pairProfileId, _s) : f_manual_r_adx_min(_s)

// AUDUSD V2 51/51 non-R contract from the champion screen:
// Any Route R / Delayed Confirmation / 27 historical turns / stack lookback 38 /
// One Leg Only / Guardian R1 / Trigger R1 / independent role profiles OFF / ADX gates OFF.
// Effective non-R behavior. These values feed the unchanged TGIM engine downstream.
string effPivotTargetScope = pairProfileActive ? "Any Route R" : pivotTargetScope
string effPivotEntryQualification = pairProfileActive ? "Delayed Confirmation" : pivotEntryQualification
int effPivotMinEntryStack = pairProfileActive ? 4 : pivotMinEntryStack
int effPivotStackLookback = pairProfileActive ? 38 : pivotStackLookback
float effPivotStackTolerance = pairProfileActive ? 2.0 : pivotStackTolerance
int effHmaCrossRegistryLimit = pairProfileActive ? 27 : hmaCrossRegistryLimit
bool effAverageShallowHmaClutter = pairProfileActive ? false : averageShallowHmaClutter
int effHmaCrossClusterMaxBars = pairProfileActive ? 2 : hmaCrossClusterMaxBars
float effHmaCrossClusterMaxSpanPips = pairProfileActive ? 0.0 : hmaCrossClusterMaxSpanPips
string effCheckpointRouteMode = pairProfileActive ? "One Leg Only" : checkpointRouteMode
string effGuardianRailSlot = pairProfileActive ? "R1" : guardianRailSlot
bool effGuardianIndependentProfile = pairProfileActive ? false : guardianIndependentProfile
string effGuardianProfileType = pairProfileActive ? "WMA" : guardianProfileType
int effGuardianProfileLen = pairProfileActive ? 2 : guardianProfileLen
string effGuardianBreakDefinition = pairProfileActive ? "Guardian Direction Flip" : guardianBreakDefinition
string effTriggerRailSlot = pairProfileActive ? "R1" : triggerRailSlot
bool effTriggerIndependentProfile = pairProfileActive ? false : triggerIndependentProfile
string effTriggerProfileType = pairProfileActive ? "WMA" : triggerProfileType
int effTriggerProfileLen = pairProfileActive ? 2 : triggerProfileLen
float effGuardianBreakBuffer = pairProfileActive ? 0.0 : guardianBreakBuffer
float effCheckpointRetestTolerance = pairProfileActive ? 0.0 : checkpointRetestTolerance
float effCheckpointLeaveDistance = pairProfileActive ? 0.0 : checkpointLeaveDistance
bool effCheckpointRequireDiConfirm = pairProfileActive ? false : checkpointRequireDiConfirm
bool effCheckpointRequireAdx = pairProfileActive ? false : checkpointRequireAdx
float effCheckpointMinAdx = pairProfileActive ? 20.0 : checkpointMinAdx

// Compact status so it is always obvious whether the chart is using a saved pair brain.
var table pairProfileTbl = table.new(position.top_center, 2, 3, border_width=1)
if barstate.islast
    table.set_position(pairProfileTbl, f_tgim_table_position(pairProfileTablePositionInput))
if barstate.islast and showPairProfileStatus
    table.cell(pairProfileTbl, 0, 0, "CONFIG SOURCE", bgcolor=color.rgb(25, 30, 40), text_color=color.white)
    table.cell(pairProfileTbl, 1, 0, pairProfileName, bgcolor=pairProfileActive ? color.new(color.green, 25) : color.new(color.gray, 45), text_color=color.white)
    table.cell(pairProfileTbl, 0, 1, "SYMBOL", bgcolor=color.rgb(25, 30, 40), text_color=color.white)
    table.cell(pairProfileTbl, 1, 1, pairProfileSymbolKey, bgcolor=color.rgb(25, 30, 40), text_color=color.white)
    table.cell(pairProfileTbl, 0, 2, "TEST WINDOW", bgcolor=color.rgb(25, 30, 40), text_color=color.white)
    table.cell(pairProfileTbl, 1, 2, pairProfileActive ? "120D CHAMPION" : backtestWindowMode, bgcolor=pairProfileActive ? color.new(color.green, 35) : color.new(color.gray, 45), text_color=color.white)


//──────────────────────────────────────────────

//──────────────────────────────────────────────
// LEAN: legacy diagonal swing-ray display controls removed (visual only).

// Helpers
//──────────────────────────────────────────────
hma(_src, _len) =>
    _half = math.max(1, int(math.round(_len / 2.0)))
    _root = math.max(1, int(math.round(math.sqrt(_len))))
    ta.wma(2.0 * ta.wma(_src, _half) - ta.wma(_src, _len), _root)

f_slope_angle(_rail, _railPrev) =>
    // Legacy function name retained; returns raw one-bar rail change.
    not na(_rail) and not na(_railPrev) ? (_rail - _railPrev) : 0.0

f_slope_dir(_delta) =>
    _delta > 0.0 ? 1 : _delta < 0.0 ? -1 : 0

f_slope_color(_angle) =>
    _dir = f_slope_dir(_angle)
    _dir == 1 ? color.green : _dir == -1 ? color.red : color.gray

f_calc_r_rail(_src, _type, _len) =>
    _type == "HMA" ? hma(_src, _len) :
     _type == "WMA" ? ta.wma(_src, _len) :
     _type == "KS" ? ta.linreg(_src, _len, 0) :
     ta.ema(_src, _len)

f_r_pack(_type, _len) =>
    _rail = f_calc_r_rail(close, _type, _len)
    _inv = f_calc_r_rail(close[1], _type, _len)
    _delta = f_slope_angle(_rail, _rail[1])
    [_diP, _diM, _adx] = ta.dmi(adxDiLength, adxDiSmoothing)
    [_rail, _inv, _delta, _diP, _diM, _adx]

// R rails + ADX/DI share ONE source-timeframe request.
// Disabled bays are genuinely dormant. The only exception is when the optional
// ray-context classifier is explicitly enabled, because that feature intentionally
// asks the fixed timeframe ladder for broad market context.
rTickerId = useHeikinAshiMath ? ticker.heikinashi(standardTickerId) : standardTickerId

f_r_request(_needed, _tf, _type, _len) =>
    if _needed
        request.security(rTickerId, _tf, f_r_pack(_type, _len), barmerge.gaps_off, barmerge.lookahead_off)
    else
        [float(na), float(na), 0.0, float(na), float(na), float(na)]

_needR1 = f_pair_r_on(1) or enableRayContextClassifier
_needR2 = f_pair_r_on(2) or enableRayContextClassifier
_needR3 = f_pair_r_on(3) or enableRayContextClassifier
_needR4 = f_pair_r_on(4) or enableRayContextClassifier
_needR5 = f_pair_r_on(5) or enableRayContextClassifier
_needR6 = f_pair_r_on(6) or enableRayContextClassifier
_needR7 = f_pair_r_on(7) or enableRayContextClassifier
_needR8 = f_pair_r_on(8) or enableRayContextClassifier
_needR9 = f_pair_r_on(9) or enableRayContextClassifier
_needR10 = f_pair_r_on(10) or enableRayContextClassifier

[r1Rail, r1InverseRail, r1SlopeAngle, diP_1w, diM_1w, adx_1w] = f_r_request(_needR1, r1_tf, f_pair_r_type(1), f_pair_r_len(1))
[r2Rail, r2InverseRail, r2SlopeAngle, diP_1d, diM_1d, adx_1d] = f_r_request(_needR2, r2_tf, f_pair_r_type(2), f_pair_r_len(2))
[r3Rail, r3InverseRail, r3SlopeAngle, diP_12h, diM_12h, adx_12h] = f_r_request(_needR3, r3_tf, f_pair_r_type(3), f_pair_r_len(3))
[r4Rail, r4InverseRail, r4SlopeAngle, diP_8h, diM_8h, adx_8h] = f_r_request(_needR4, r4_tf, f_pair_r_type(4), f_pair_r_len(4))
[r5Rail, r5InverseRail, r5SlopeAngle, diP_6h, diM_6h, adx_6h] = f_r_request(_needR5, r5_tf, f_pair_r_type(5), f_pair_r_len(5))
[r6Rail, r6InverseRail, r6SlopeAngle, diP_4h, diM_4h, adx_4h] = f_r_request(_needR6, r6_tf, f_pair_r_type(6), f_pair_r_len(6))
[r7Rail, r7InverseRail, r7SlopeAngle, diP_1h, diM_1h, adx_1h] = f_r_request(_needR7, r7_tf, f_pair_r_type(7), f_pair_r_len(7))
[r8Rail, r8InverseRail, r8SlopeAngle, diP_15m, diM_15m, adx_15m] = f_r_request(_needR8, r8_tf, f_pair_r_type(8), f_pair_r_len(8))
[r9Rail, r9InverseRail, r9SlopeAngle, diP_5m, diM_5m, adx_5m] = f_r_request(_needR9, r9_tf, f_pair_r_type(9), f_pair_r_len(9))
[r10Rail, r10InverseRail, r10SlopeAngle, diP_1m, diM_1m, adx_1m] = f_r_request(_needR10, r10_tf, f_pair_r_type(10), f_pair_r_len(10))

r1Dir = f_slope_dir(r1SlopeAngle)
r2Dir = f_slope_dir(r2SlopeAngle)
r3Dir = f_slope_dir(r3SlopeAngle)
r4Dir = f_slope_dir(r4SlopeAngle)
r5Dir = f_slope_dir(r5SlopeAngle)
r6Dir = f_slope_dir(r6SlopeAngle)
r7Dir = f_slope_dir(r7SlopeAngle)
r8Dir = f_slope_dir(r8SlopeAngle)
r9Dir = f_slope_dir(r9SlopeAngle)
r10Dir = f_slope_dir(r10SlopeAngle)

r1Color = f_slope_color(r1SlopeAngle)
r2Color = f_slope_color(r2SlopeAngle)
r3Color = f_slope_color(r3SlopeAngle)
r4Color = f_slope_color(r4SlopeAngle)
r5Color = f_slope_color(r5SlopeAngle)
r6Color = f_slope_color(r6SlopeAngle)
r7Color = f_slope_color(r7SlopeAngle)
r8Color = f_slope_color(r8SlopeAngle)
r9Color = f_slope_color(r9SlopeAngle)
r10Color = f_slope_color(r10SlopeAngle)


r1CrossUp = ta.crossover(r1Rail, r1InverseRail)
r1CrossDown = ta.crossunder(r1Rail, r1InverseRail)
r2CrossUp = ta.crossover(r2Rail, r2InverseRail)
r2CrossDown = ta.crossunder(r2Rail, r2InverseRail)
r3CrossUp = ta.crossover(r3Rail, r3InverseRail)
r3CrossDown = ta.crossunder(r3Rail, r3InverseRail)
r4CrossUp = ta.crossover(r4Rail, r4InverseRail)
r4CrossDown = ta.crossunder(r4Rail, r4InverseRail)
r5CrossUp = ta.crossover(r5Rail, r5InverseRail)
r5CrossDown = ta.crossunder(r5Rail, r5InverseRail)
r6CrossUp = ta.crossover(r6Rail, r6InverseRail)
r6CrossDown = ta.crossunder(r6Rail, r6InverseRail)
r7CrossUp = ta.crossover(r7Rail, r7InverseRail)
r7CrossDown = ta.crossunder(r7Rail, r7InverseRail)
r8CrossUp = ta.crossover(r8Rail, r8InverseRail)
r8CrossDown = ta.crossunder(r8Rail, r8InverseRail)
r9CrossUp = ta.crossover(r9Rail, r9InverseRail)
r9CrossDown = ta.crossunder(r9Rail, r9InverseRail)
r10CrossUp = ta.crossover(r10Rail, r10InverseRail)
r10CrossDown = ta.crossunder(r10Rail, r10InverseRail)



f_pip_size() =>
    syminfo.type == "forex" ? (str.contains(str.upper(syminfo.ticker), "JPY") ? 0.01 : 0.0001) : syminfo.mintick



f_regime_state(_price, _rail, _railPrev) =>
    if na(_rail)
        0
    else
        _above = _price > _rail
        _dir = f_slope_dir(f_slope_angle(_rail, _railPrev))
        _dir == 0 ? (_above ? 3 : -3) :
         _above and _dir == 1 ? 1 :
         _above and _dir == -1 ? 2 :
         not _above and _dir == -1 ? -1 : -2

f_regime_state_text(_state) =>
    _state == 0 ? "OFF" :
     _state == 1 ? "A↑" :
     _state == 2 ? "A↓" :
     _state == -1 ? "B↓" :
     _state == -2 ? "B↑" :
     _state == 3 ? "A→" : "B→"

//──────────────────────────────────────────────
// Ray-context classifier helpers
// State scoring preserves the existing rail-regime meaning:
//   A↑ = +2, B↑ = +1, A↓ = -1, B↓ = -2, flat = 0.
// Structural weighting deliberately favors larger frames:
//   D=5, 12H=4, 8H=3, 6H=2, 4H=2.
//──────────────────────────────────────────────
f_context_state_score(_state) =>
    _state == 1 ? 2.0 :
     _state == -2 ? 1.0 :
     _state == 2 ? -1.0 :
     _state == -1 ? -2.0 : 0.0

f_context_structural_score(_sD, _s12H, _s8H, _s6H, _s4H) =>
    f_context_state_score(_sD) * 5.0 +
     f_context_state_score(_s12H) * 4.0 +
     f_context_state_score(_s8H) * 3.0 +
     f_context_state_score(_s6H) * 2.0 +
     f_context_state_score(_s4H) * 2.0

f_context_regime_dir(_score) =>
    _score >= structuralRegimeThreshold ? 1 : _score <= -structuralRegimeThreshold ? -1 : 0

f_context_regime_text(_dir) =>
    _dir == 1 ? "BULLISH" : _dir == -1 ? "BEARISH" : "TRANSITION"

f_context_move_text(_rayDir, _regimeDir) =>
    _rayDir == 0 or _regimeDir == 0 ? "TRANSITION" : _rayDir == _regimeDir ? "CONTINUATION" : "RETRACEMENT"

f_context_micro_dir(_s15, _s5, _s1) =>
    _score = f_context_state_score(_s15) + f_context_state_score(_s5) + f_context_state_score(_s1)
    _score >= 2.0 ? 1 : _score <= -2.0 ? -1 : 0

f_context_adx_vote(_adx, _p, _m, _weight) =>
    _adx >= contextAdxMin ? (_p > _m ? _weight : -_weight) * (_adx >= adxStrongThreshold ? 2.0 : 1.0) : 0.0

f_context_adx_score(_aD, _pD, _mD, _a12, _p12, _m12, _a8, _p8, _m8, _a6, _p6, _m6, _a4, _p4, _m4) =>
    f_context_adx_vote(_aD, _pD, _mD, 5.0) +
     f_context_adx_vote(_a12, _p12, _m12, 4.0) +
     f_context_adx_vote(_a8, _p8, _m8, 3.0) +
     f_context_adx_vote(_a6, _p6, _m6, 2.0) +
     f_context_adx_vote(_a4, _p4, _m4, 2.0)

f_context_adx_dir(_score) =>
    _score >= structuralRegimeThreshold ? 1 : _score <= -structuralRegimeThreshold ? -1 : 0

f_context_adx_relation(_regimeDir, _adxDir) =>
    _adxDir == 0 ? "MIXED" : _regimeDir == 0 ? f_context_regime_text(_adxDir) : _adxDir == _regimeDir ? "CONFIRM" : "CONFLICT"


//──────────────────────────────────────────────
// OANDA US FX tier helper — current 50:1 / 33.3:1 / 20:1 universe.
// Pair key is BASE+QUOTE, e.g. EURUSD. Lower-leverage pairs are intentionally
// outside this F6 hunting universe unless the tier restriction toggle is OFF.
//──────────────────────────────────────────────
f_oanda_leverage_tier(_pair) =>
    _p = str.upper(_pair)
    _tier50 = str.contains("|EURUSD|USDCAD|EURCAD|USDDKK|", "|" + _p + "|")
    _tier33 = str.contains("|AUDCHF|AUDUSD|EURNZD|NZDUSD|EURCHF|NZDCAD|AUDCAD|NZDCHF|USDSEK|EURAUD|USDCHF|AUDNZD|CADCHF|EURSEK|", "|" + _p + "|")
    _tier20 = str.contains("|SGDJPY|EURGBP|USDHUF|GBPCHF|USDTHB|CADJPY|USDCNH|USDPLN|GBPAUD|AUDJPY|EURPLN|EURHUF|USDJPY|GBPNZD|GBPCAD|AUDSGD|GBPJPY|GBPUSD|USDCZK|EURCZK|GBPPLN|GBPSGD|EURSGD|EURJPY|CADSGD|NZDJPY|CHFJPY|NZDSGD|USDSGD|", "|" + _p + "|")
    _tier50 ? 50.0 : _tier33 ? 33.3 : _tier20 ? 20.0 : na


//──────────────────────────────────────────────
// PEAK / VALLEY EVENT STATE — MINIMAL ADDITION
// Flat/gray bars do NOT reset the last meaningful direction.
// PEAK   = last meaningful direction UP, current meaningful direction DOWN.
// VALLEY = last meaningful direction DOWN, current meaningful direction UP.
//──────────────────────────────────────────────
var rLastMeaningfulDir = array.new_int(10, 0)
rDirNow = array.from(r1Dir,r2Dir,r3Dir,r4Dir,r5Dir,r6Dir,r7Dir,r8Dir,r9Dir,r10Dir)
for _ri = 0 to 9
    _rd = array.get(rDirNow, _ri)
    if _rd != 0
        array.set(rLastMeaningfulDir, _ri, _rd)

pipSize = f_pip_size()

// Count consecutive rail dots immediately BEFORE the turn that sit on/near the
// final pivot-ray price. The event is detected on the current bar while its ray
// origin is bar_index - 1, so the scan starts at rail[1]. Diagnostic only.
// IMPORTANT: this helper must be declared before the per-bar calls below.
f_origin_stack(_rail, _rayPrice, _tol, _lookback) =>
    int _count = 0
    bool _keepCounting = true
    int _i = 1
    while _i <= _lookback and _keepCounting
        _v = _rail[_i]
        if not na(_v) and math.abs(_v - _rayPrice) <= _tol
            _count += 1
        else
            _keepCounting := false
        _i += 1
    _count

// Global per-bar stack calculations for R1-R10.
_originStackTolNow = pipSize * effPivotStackTolerance
r1OriginStackNow = f_origin_stack(r1Rail, r1InverseRail, _originStackTolNow, effPivotStackLookback)
r2OriginStackNow = f_origin_stack(r2Rail, r2InverseRail, _originStackTolNow, effPivotStackLookback)
r3OriginStackNow = f_origin_stack(r3Rail, r3InverseRail, _originStackTolNow, effPivotStackLookback)
r4OriginStackNow = f_origin_stack(r4Rail, r4InverseRail, _originStackTolNow, effPivotStackLookback)
r5OriginStackNow = f_origin_stack(r5Rail, r5InverseRail, _originStackTolNow, effPivotStackLookback)
r6OriginStackNow = f_origin_stack(r6Rail, r6InverseRail, _originStackTolNow, effPivotStackLookback)
r7OriginStackNow = f_origin_stack(r7Rail, r7InverseRail, _originStackTolNow, effPivotStackLookback)
r8OriginStackNow = f_origin_stack(r8Rail, r8InverseRail, _originStackTolNow, effPivotStackLookback)
r9OriginStackNow = f_origin_stack(r9Rail, r9InverseRail, _originStackTolNow, effPivotStackLookback)
r10OriginStackNow = f_origin_stack(r10Rail, r10InverseRail, _originStackTolNow, effPivotStackLookback)

//──────────────────────────────────────────────
// OANDA PAIR CLASSIFICATION + ENTRY GUARDS
// A Pine strategy is one chart/symbol. Run one instance/alert per pair for
// simultaneous multi-pair hunting; the same F6 file recognizes all tiers below.
//──────────────────────────────────────────────
oandaPairKey = str.upper(syminfo.basecurrency + syminfo.currency)
oandaLeverageTier = f_oanda_leverage_tier(oandaPairKey)
oandaTierEligible = not restrictToOandaCoreTiers or not na(oandaLeverageTier)

oandaMarginRatePct =
     na(oandaLeverageTier) ? na :
     oandaLeverageTier == 50.0 ? 2.0 :
     oandaLeverageTier == 33.3 ? 3.0 :
     oandaLeverageTier == 20.0 ? 5.0 :
     100.0 / oandaLeverageTier

// V6.3 Strategy Tester margin basis. Unknown/unmapped symbols fall back to MANUAL.
effectiveTesterMarginPct =
     testerMarginMode == "AUTO OANDA TIER" and not na(oandaMarginRatePct) ?
          oandaMarginRatePct :
          testerMarginAllocationPct

// TradingView-side estimate for Strategy Tester order quantity ONLY.
// This formula is NOT authoritative for live OANDA sizing; broker/account conversion
// and portfolio headroom belong to the backend immediately before execution.
f_tester_units_estimate() =>
    float _lev = na(oandaLeverageTier) ? 1.0 : oandaLeverageTier
    float _marginDollars = strategy.equity * (effectiveTesterMarginPct * 0.01)
    math.max(1.0, math.round((_marginDollars * _lev) / realClose))

// Quantity supplied to TradingView's broker emulator only.
f_strategy_order_units() =>
    liveSizingMode == "EXACT Fixed Units" ? float(fixedUnits) : f_tester_units_estimate()


//──────────────────────────────────────────────
// V6.4 — FAIL-CLOSED OANDA ORDER / ATOMIC-FLIP PAYLOAD
// Dynamic portfolio sizing contract:
//   1) Pine supplies the signal + margin-allocation policy.
//   2) Pine supplies ZERO authoritative dynamic units.
//   3) Backend reads fresh OANDA account state, price, margin requirement and currency conversion.
//   4) Backend calculates final units immediately before BUY/SELL/FLIP.
//   5) If sizing cannot be completed, backend rejects. Never fall back to tester units.
// Atomic FLIP is the established OANDA-sync contract: target=long/short.
//──────────────────────────────────────────────
f_oanda_payload_core(_action, _target) =>
    bool _isEntryLike = _action == "buy" or _action == "sell" or _action == "flip"
    bool _exact = liveSizingMode == "EXACT Fixed Units"
    bool _backendDynamic = _isEntryLike and not _exact
    float _testerUnits = f_tester_units_estimate()
    float _authoritativeUnits = _exact ? float(fixedUnits) : 0.0
    string _mode = _exact ? "fixed_units" : "dynamic_margin"
    float _marginAllocationPct = _exact ? 0.0 : liveOandaPerTradeTargetPct
    float _lev = na(oandaLeverageTier) ? 0.0 : oandaLeverageTier
    float _marginPct = na(oandaMarginRatePct) ? 0.0 : oandaMarginRatePct
    string _unitsAuthority = _exact ? "pine_exact" : "backend_oanda_live_account"
    string _targetField = _action == "flip" ? ",\"target\":\"" + _target + "\"" : ""

    "{\"schema\":\"tgim-portfolio-v7.3\"" +
     ",\"build_id\":\"TFSTACK-ADX4-PAIRPROFILES-V6.5-FX-REALISM\"" +
     ",\"sizing_contract\":\"live_nav_margin_v2\"" +
     ",\"action\":\"" + _action + "\"" + _targetField +
     ",\"instrument\":\"" + f_oanda_instrument() + "\"" +
     ",\"units\":" + str.tostring(math.round(_authoritativeUnits)) +
     ",\"requested_units\":" + str.tostring(math.round(_authoritativeUnits)) +
     ",\"units_authority\":\"" + _unitsAuthority + "\"" +
     ",\"require_backend_sizing\":" + (_backendDynamic ? "true" : "false") +
     ",\"reject_if_backend_sizing_unavailable\":" + (_backendDynamic ? "true" : "false") +
     ",\"pine_tester_units_estimate\":" + str.tostring(math.round(_testerUnits)) +
     ",\"pine_tester_equity\":" + str.tostring(strategy.equity) +
     ",\"pine_tester_margin_mode\":\"" + testerMarginMode + "\"" +
     ",\"pine_tester_margin_pct\":" + str.tostring(effectiveTesterMarginPct) +
     ",\"pine_tester_manual_margin_pct\":" + str.tostring(testerMarginAllocationPct) +
     ",\"price_hint\":" + str.tostring(realClose) +
     ",\"sizing_mode\":\"" + _mode + "\"" +
     ",\"force_exact_units\":" + (_exact ? "true" : "false") +
     ",\"risk_pct\":" + str.tostring(_marginAllocationPct) +
     ",\"per_trade_margin_pct\":" + str.tostring(_marginAllocationPct) +
     ",\"portfolio_margin_ceiling_pct\":" + str.tostring(portfolioMarginCeilingPct) +
     ",\"max_concurrent_positions\":" + str.tostring(portfolioMaxConcurrent) +
     ",\"sizing_equity_mode\":\"" + portfolioSizingEquityMode + "\"" +
     ",\"block_ny_5pm_entry_hour\":" + (blockNy5pmEntryHour ? "true" : "false") +
     ",\"leverage_tier\":" + str.tostring(_lev) +
     ",\"margin_rate_pct\":" + str.tostring(_marginPct) +
     ",\"close_scope\":\"full_position\"" +
     ",\"position_policy\":\"sync\"" +
     ",\"ignore_if_flat\":true" +
     ",\"max_spread_pips\":" + str.tostring(maxSpreadPips) +
     ",\"max_drawdown_pct\":" + str.tostring(maxDDLimitPct) +
     ",\"drawdown_source\":\"TradingView Strategy Equity\"}"

f_oanda_payload(_action) =>
    f_oanda_payload_core(_action, "")

f_oanda_flip_payload(_target) =>
    f_oanda_payload_core("flip", _target)


f_oanda_close_action(_dir) =>
    _dir == 1 ? "close_buy" : "close_sell"

// Live spread gate. Backend Only is intentionally permissive inside Pine because
// broker bid/ask history does not exist on normal bars; execution must reject a
// new order when actual OANDA spread > maxSpreadPips. Manual mode is testable here.
pineSpreadPass = maxSpreadPips <= 0.0 or spreadGuardMode == "Backend Only" or manualCurrentSpreadPips <= maxSpreadPips

// Drawdown entry lock: running peak equity -> current DD -> running max DD.
// Once the configured max DD is reached, NEW entries stay locked for this run.
// Exit/TP/Guardian logic is deliberately not gated.
var float peakEq = na
var float maxDDPct = 0.0
peakEq := na(peakEq) ? strategy.equity : math.max(peakEq, strategy.equity)
curDDPct = peakEq > 0.0 ? math.max(0.0, (peakEq - strategy.equity) / peakEq * 100.0) : 0.0
maxDDPct := math.max(maxDDPct, curDDPct)
ddGateBlocked = useMaxDDTradeGate and maxDDLimitPct > 0.0 and maxDDPct >= maxDDLimitPct

// Realtime-clock rollover blackout only. Historical bars are never suppressed by wall clock.
bool ny5pmRolloverNow = barstate.isrealtime and hour(timenow, "America/New_York") == 17
bool rolloverEntryPass = not blockNy5pmEntryHour or not ny5pmRolloverNow

// Separate structural authority from live spread/rollover authority.
// Deferred memory deliberately ignores spread: a good setup is remembered even when
// the 5PM broker spread is precisely the reason we do NOT want to enter yet.
bool deferredCaptureBasePass = backtestCanEnter and oandaTierEligible and not ddGateBlocked
bool entryGuardPassNoRollover = deferredCaptureBasePass and pineSpreadPass

// ONE authority used by every normal fresh entry path in donor + F shuttle.
entryGuardPass = entryGuardPassNoRollover and rolloverEntryPass

// v12.44: selected Guardian R = direction/boundary; selected Trigger R = retrace/re-entry timing.
// Guardian break = exit/neutral, never auto-reverse. The six-pair competition/ranking
// layer is still intentionally separate and remains pending.
_entryModeShort = effPivotEntryQualification == "Raw" ? "RAW" :
     effPivotEntryQualification == "Stack Qualified" ? "STACK>=" + str.tostring(effPivotMinEntryStack) :
     effPivotEntryQualification == "Continuation Only" ? "CONT ONLY" : "DELAY CONF"


// Persistent current-chart strategy state.
varip float activePivotTarget = na
varip int activePivotSource = 0
varip int activePivotDirection = 0
varip int activePivotStack = 0
varip int lastPivotTradeExitBar = na
varip int lastPivotTradeExitLiveSeq = na
varip string lastPivotDecision = "WAITING FOR PIVOT RAY"
varip int pivotClosedTradesSeen = 0

// Active route-leg metadata. The active target price already existed in v12.41;
// v12.42 adds target/origin bar identity so the path can continue or reverse.
varip int activePivotTargetBar = na
varip int activePivotTargetType = 0
varip float activeLegStartPrice = na
varip int activeLegStartBar = na
varip int activeLegStartType = 0
varip int activeLegStartSource = 0

// Decision-checkpoint state after a target fills.
varip bool checkpointWaitActive = false
varip float checkpointDecisionPrice = na
varip int checkpointDecisionBar = na
varip int checkpointDecisionType = 0
varip int checkpointRouteSource = 0
varip int checkpointIncomingDirection = 0

// The checkpoint/node from which the just-completed leg began.
// An opposite-slope check returns toward this node.

// Must leave zone, then come back.
varip int checkpointAwaySide = 0
varip int checkpointAwayBar = na
varip int checkpointAwayLiveSeq = na
varip int checkpointWaitStartBar = na
varip string checkpointRouteStateText = "WAITING"


// Guardian R guardian state.
varip bool guardianExitPending = false
varip bool guardianNeutralWait = false
varip int guardianWaitStartBar = na
varip string pendingExitCause = "TARGET"

// Backtest-integrity / execution diagnostics.
// With process_orders_on_close=false, a market order generated at a confirmed
// signal-bar close is eligible to fill on the next bar, not retroactively.
varip int lastPivotSignalBar = na

//──────────────────────────────────────────────
// v12.41 entry-qualification lab state.
// Destination/exit logic is NOT changed.
//──────────────────────────────────────────────

varip bool delayedPivotArmed = false
varip int delayedPivotSource = 0
varip int delayedPivotType = 0
varip int delayedPivotStack = 0
varip int delayedPivotRayBar = na
varip int delayedPivotArmBar = na
varip float delayedPivotRayPrice = na
varip float delayedPivotTarget = na
varip string delayedPivotRailName = "WAITING"

// ADX4 — realtime-only deferred rollover candidate.
// This is deliberately separate from Strategy Tester state: during 5PM we remember, not fill.
varip bool deferredRolloverArmed = false
varip int deferredRolloverDir = 0
varip int deferredRolloverSource = 0
varip int deferredRolloverType = 0
varip int deferredRolloverStack = 0
varip int deferredRolloverOriginBar = na
varip int deferredRolloverTargetBar = na
varip float deferredRolloverOriginPrice = na
varip float deferredRolloverTarget = na
varip int deferredRolloverArmedMs = na
varip int deferredRolloverLastRetryMs = na
varip int deferredRolloverRetryCount = 0
varip bool deferredRolloverRetryAllowed = true
varip string deferredRolloverKind = "NONE"
varip string deferredRolloverStatus = "IDLE"

// Decision checkpoint is drawn with line objects, not plot(), so the existing
// TradingView 64-plot budget is not consumed.
var line checkpointDecisionLine = na
var line checkpointZoneUpperLine = na
var line checkpointZoneLowerLine = na

bool pivotLongSignalThisBar = false
bool pivotShortSignalThisBar = false

// Ordered / proximity-filtered MULTI-RAIL turn-ray engine — VISUAL ONLY.
//
// Source selection:
//   Fixed-timeframe R1-R10 bays with per-bay HMA/WMA/KS/EMA selection.
//
// Every rail uses the same turn definition:
//   rail crosses above its one-bar inverse = valley turn,
//   rail crosses below its one-bar inverse = peak turn.
//
// Registry order:
//   newest confirmed turn is Ray 1, then Ray 2, Ray 3, moving right-to-left.
//
// Display selection:
//   closest N consolidated/standalone rays ABOVE current price,
//   closest N consolidated/standalone rays BELOW current price.
//
// Clutter compression:
//   contiguous shallow groups containing at least one peak and one valley
//   are replaced by one arithmetic-average ray. The average receives the
//   newest member's chronological identity.
//──────────────────────────────────────────────
hmaCrossLineStyle = hmaCrossRayStyleInput == "Solid" ? line.style_solid : hmaCrossRayStyleInput == "Dashed" ? line.style_dashed : line.style_dotted

// Source IDs: 1 HMA, 2 WMA, 3 KS, 4 EMA.
var float[] hmaCrossStoredPrices = array.new_float()
var int[] hmaCrossStoredBars = array.new_int()
var int[] hmaCrossStoredTimes = array.new_int()
var int[] hmaCrossStoredTypes = array.new_int()    // +1 valley, -1 peak
var int[] hmaCrossStoredSources = array.new_int()

var float[] hmaCrossDisplayPrices = array.new_float()
var int[] hmaCrossDisplayBars = array.new_int()
var int[] hmaCrossDisplayTimes = array.new_int()
var int[] hmaCrossDisplayTypes = array.new_int()   // +1 valley, -1 peak, 0 averaged clutter
var int[] hmaCrossDisplaySources = array.new_int() // 0 averaged clutter
// Driver source/type preserve the newest raw rail turn behind each final display ray.
// For standalone rays they equal the display source/type. For a blue cluster ray
// they identify the newest member that caused/updated that final visible cluster.
var int[] hmaCrossDisplayDriverTypes = array.new_int()
var int[] hmaCrossDisplayDriverSources = array.new_int()
var line[] hmaCrossRayLines = array.new_line()

// V6.4.2 — deep DISPLAY-ONLY ZAG turn registry.
// The route-ray registry below is deliberately shallow; ZAG drawing cannot depend on it.
var float[] zagVisualStoredPrices = array.new_float()
var int[] zagVisualStoredBars = array.new_int()
var int[] zagVisualStoredTypes = array.new_int()
var int[] zagVisualStoredSources = array.new_int()
int zagVisualRegistryLimit = 3000

// Built downstream from the FINAL visible-ray selection. The alert block later in
// the script consumes these events only after the higher-timeframe context series exist.
string visibleRailRayAlertMessage = ""
var int[] visibleRayEventSources = array.new_int()
var int[] visibleRayEventTypes = array.new_int()
var int[] visibleRayEventDirs = array.new_int()
var bool[] visibleRayEventClusters = array.new_bool()
var float[] visibleRayEventPrices = array.new_float()
var int[] visibleRayEventBars = array.new_int()
var int[] visibleRayEventStacks = array.new_int()

// Persistent diagnostic readout for the most recently classified visible ray.

// V6.4.2 display-only store. Dedup by source + vertex bar so realtime recalculation
// cannot manufacture duplicate visual vertices. This registry never drives execution.
f_store_zag_visual_turn(_price, _bar, _type, _source) =>
    int _found = na
    int _n = array.size(zagVisualStoredBars)
    if _n > 0
        int _scan = _n - 1
        while _scan >= 0 and na(_found)
            if array.get(zagVisualStoredSources, _scan) == _source and array.get(zagVisualStoredBars, _scan) == _bar
                _found := _scan
            _scan -= 1
    if na(_found)
        array.push(zagVisualStoredPrices, _price)
        array.push(zagVisualStoredBars, _bar)
        array.push(zagVisualStoredTypes, _type)
        array.push(zagVisualStoredSources, _source)
    else
        array.set(zagVisualStoredPrices, _found, _price)
        array.set(zagVisualStoredTypes, _found, _type)
    while array.size(zagVisualStoredBars) > zagVisualRegistryLimit
        array.shift(zagVisualStoredPrices)
        array.shift(zagVisualStoredBars)
        array.shift(zagVisualStoredTypes)
        array.shift(zagVisualStoredSources)
    true

f_store_rail_turn(_price, _bar, _time, _type, _source) =>
    int _found = na
    _n = array.size(hmaCrossStoredBars)
    if _n > 0
        _scan = _n - 1
        while _scan >= 0 and na(_found)
            if array.get(hmaCrossStoredSources, _scan) == _source and array.get(hmaCrossStoredBars, _scan) == _bar
                _found := _scan
            _scan -= 1

    if na(_found)
        array.push(hmaCrossStoredPrices, _price)
        array.push(hmaCrossStoredBars, _bar)
        array.push(hmaCrossStoredTimes, _time)
        array.push(hmaCrossStoredTypes, _type)
        array.push(hmaCrossStoredSources, _source)
    else
        array.set(hmaCrossStoredPrices, _found, _price)
        array.set(hmaCrossStoredTimes, _found, _time)
        array.set(hmaCrossStoredTypes, _found, _type)
    f_store_zag_visual_turn(_price, _bar, _type, _source)
    true

// Compact R-bay configuration/state arrays.
// These replace repeated 10-way ternary selector functions and materially reduce
// compiled-token pressure while keeping the individual R inputs unchanged.
var rOnCfg = array.from(f_pair_r_on(1),f_pair_r_on(2),f_pair_r_on(3),f_pair_r_on(4),f_pair_r_on(5),f_pair_r_on(6),f_pair_r_on(7),f_pair_r_on(8),f_pair_r_on(9),f_pair_r_on(10))
var rShowRaysCfg = array.from(f_pair_r_rays(1),f_pair_r_rays(2),f_pair_r_rays(3),f_pair_r_rays(4),f_pair_r_rays(5),f_pair_r_rays(6),f_pair_r_rays(7),f_pair_r_rays(8),f_pair_r_rays(9),f_pair_r_rays(10))
var rTypeCfg = array.from(f_pair_r_type(1),f_pair_r_type(2),f_pair_r_type(3),f_pair_r_type(4),f_pair_r_type(5),f_pair_r_type(6),f_pair_r_type(7),f_pair_r_type(8),f_pair_r_type(9),f_pair_r_type(10))
var rLenCfg = array.from(f_pair_r_len(1),f_pair_r_len(2),f_pair_r_len(3),f_pair_r_len(4),f_pair_r_len(5),f_pair_r_len(6),f_pair_r_len(7),f_pair_r_len(8),f_pair_r_len(9),f_pair_r_len(10))
var rTfCfg = array.from(r1_tf,r2_tf,r3_tf,r4_tf,r5_tf,r6_tf,r7_tf,r8_tf,r9_tf,r10_tf)
var rTfLabelCfg = array.from("1W","1D","12H","8H","6H","4H","1H","15m","5m","1m")
var rShowZagCfg = array.from(r1_showZag,r2_showZag,r3_showZag,r4_showZag,r5_showZag,r6_showZag,r7_showZag,r8_showZag,r9_showZag,r10_showZag)
var rZagSegmentsCfg = array.from(r1_zagSegments,r2_zagSegments,r3_zagSegments,r4_zagSegments,r5_zagSegments,r6_zagSegments,r7_zagSegments,r8_zagSegments,r9_zagSegments,r10_zagSegments)
var rZagWidthCfg = array.from(r1_zagWidth,r2_zagWidth,r3_zagWidth,r4_zagWidth,r5_zagWidth,r6_zagWidth,r7_zagWidth,r8_zagWidth,r9_zagWidth,r10_zagWidth)
var rUseZagCfg = array.from(f_pair_r_use_zag(1),f_pair_r_use_zag(2),f_pair_r_use_zag(3),f_pair_r_use_zag(4),f_pair_r_use_zag(5),f_pair_r_use_zag(6),f_pair_r_use_zag(7),f_pair_r_use_zag(8),f_pair_r_use_zag(9),f_pair_r_use_zag(10))
var rUseAdxCfg = array.from(f_pair_r_use_adx(1),f_pair_r_use_adx(2),f_pair_r_use_adx(3),f_pair_r_use_adx(4),f_pair_r_use_adx(5),f_pair_r_use_adx(6),f_pair_r_use_adx(7),f_pair_r_use_adx(8),f_pair_r_use_adx(9),f_pair_r_use_adx(10))
var rAdxMinCfg = array.from(f_pair_r_adx_min(1),f_pair_r_adx_min(2),f_pair_r_adx_min(3),f_pair_r_adx_min(4),f_pair_r_adx_min(5),f_pair_r_adx_min(6),f_pair_r_adx_min(7),f_pair_r_adx_min(8),f_pair_r_adx_min(9),f_pair_r_adx_min(10))

rRailNow = array.from(r1Rail,r2Rail,r3Rail,r4Rail,r5Rail,r6Rail,r7Rail,r8Rail,r9Rail,r10Rail)
rAdxNow = array.from(adx_1w,adx_1d,adx_12h,adx_8h,adx_6h,adx_4h,adx_1h,adx_15m,adx_5m,adx_1m)
rDiPNow = array.from(diP_1w,diP_1d,diP_12h,diP_8h,diP_6h,diP_4h,diP_1h,diP_15m,diP_5m,diP_1m)
rDiMNow = array.from(diM_1w,diM_1d,diM_12h,diM_8h,diM_6h,diM_4h,diM_1h,diM_15m,diM_5m,diM_1m)

f_r_slot_id(_slot) =>
    _slot == "R1" ? 1 : _slot == "R2" ? 2 : _slot == "R3" ? 3 : _slot == "R4" ? 4 : _slot == "R5" ? 5 :
     _slot == "R6" ? 6 : _slot == "R7" ? 7 : _slot == "R8" ? 8 : _slot == "R9" ? 9 : 10

f_r_enabled(_source) => array.get(rOnCfg, _source - 1)
f_r_show_rays(_source) => array.get(rShowRaysCfg, _source - 1)
f_r_route_rays(_source) => f_r_show_rays(_source)
f_r_type(_source) => array.get(rTypeCfg, _source - 1)
f_r_len(_source) => array.get(rLenCfg, _source - 1)
f_r_tf(_source) => array.get(rTfCfg, _source - 1)
f_r_show_zag(_source) => array.get(rShowZagCfg, _source - 1)
f_r_zag_segments(_source) => array.get(rZagSegmentsCfg, _source - 1)
f_r_zag_width(_source) => array.get(rZagWidthCfg, _source - 1)
f_r_use_zag(_source) => array.get(rUseZagCfg, _source - 1)
f_r_raw_rail(_source) => array.get(rRailNow, _source - 1)
f_r_raw_dir(_source) => array.get(rDirNow, _source - 1)
f_r_raw_last_meaningful_dir(_source) => array.get(rLastMeaningfulDir, _source - 1)

// Causal ZAG rail: latest confirmed turn is the anchor. The previous completed
// turn-to-turn leg supplies slope MAGNITUDE; the current meaningful raw-R direction
// supplies the active-leg SIGN. This creates a real alternative working rail without
// retroactively drawing a future pivot endpoint into earlier strategy bars.
f_r_zag_state(_source) =>
    float _latestPrice = na
    float _prevPrice = na
    int _latestBar = na
    int _prevBar = na
    int _found = 0
    int _i = array.size(hmaCrossStoredBars) - 1
    while _i >= 0 and _found < 2
        if array.get(hmaCrossStoredSources, _i) == _source
            if _found == 0
                _latestPrice := array.get(hmaCrossStoredPrices, _i)
                _latestBar := array.get(hmaCrossStoredBars, _i)
            else
                _prevPrice := array.get(hmaCrossStoredPrices, _i)
                _prevBar := array.get(hmaCrossStoredBars, _i)
            _found += 1
        _i -= 1

    float _zag = f_r_raw_rail(_source)
    int _zagDir = f_r_raw_last_meaningful_dir(_source)
    if _found == 2 and _latestBar > _prevBar
        float _mag = math.abs((_latestPrice - _prevPrice) / (_latestBar - _prevBar))
        int _activeDir = f_r_raw_last_meaningful_dir(_source)
        if _activeDir == 0
            _activeDir := _latestPrice >= _prevPrice ? -1 : 1
        _zag := _latestPrice + _activeDir * _mag * math.max(0, bar_index - _latestBar)
        _zagDir := _activeDir
    [_zag, _zagDir]

f_r_rail(_source) =>
    [_zag, _zagDir] = f_r_zag_state(_source)
    f_r_use_zag(_source) ? _zag : f_r_raw_rail(_source)

f_r_dir(_source) =>
    [_zag, _zagDir] = f_r_zag_state(_source)
    f_r_use_zag(_source) ? _zagDir : f_r_raw_dir(_source)

f_r_last_meaningful_dir(_source) =>
    f_r_use_zag(_source) ? f_r_dir(_source) : f_r_raw_last_meaningful_dir(_source)

// V6.4 ZAG FLIP source/event helpers.
f_zag_flip_source() =>
    if zagFlipRailSlot == "AUTO CHART TF"
        timeframe.isweekly ? 1 :
         timeframe.isdaily ? 2 :
         timeframe.period == "720" ? 3 :
         timeframe.period == "480" ? 4 :
         timeframe.period == "360" ? 5 :
         timeframe.period == "240" ? 6 :
         timeframe.period == "60" ? 7 :
         timeframe.period == "15" ? 8 :
         timeframe.period == "5" ? 9 :
         timeframe.period == "1" ? 10 : 8
    else if zagFlipRailSlot != "AUTO SHOWN ZAG"
        f_r_slot_id(zagFlipRailSlot)
    else
        int _src = 0
        int _i = 1
        while _i <= 10 and _src == 0
            if f_r_enabled(_i) and f_r_show_zag(_i)
                _src := _i
            _i += 1
        // If nothing is displayed, use the first enabled R rather than silently inventing geometry.
        if _src == 0
            _i := 1
            while _i <= 10 and _src == 0
                if f_r_enabled(_i)
                    _src := _i
                _i += 1
        _src == 0 ? 1 : _src

f_zag_flip_up(_source) =>
    _source == 1 ? r1CrossUp : _source == 2 ? r2CrossUp : _source == 3 ? r3CrossUp : _source == 4 ? r4CrossUp : _source == 5 ? r5CrossUp :
     _source == 6 ? r6CrossUp : _source == 7 ? r7CrossUp : _source == 8 ? r8CrossUp : _source == 9 ? r9CrossUp : r10CrossUp

f_zag_flip_down(_source) =>
    _source == 1 ? r1CrossDown : _source == 2 ? r2CrossDown : _source == 3 ? r3CrossDown : _source == 4 ? r4CrossDown : _source == 5 ? r5CrossDown :
     _source == 6 ? r6CrossDown : _source == 7 ? r7CrossDown : _source == 8 ? r8CrossDown : _source == 9 ? r9CrossDown : r10CrossDown


f_r_tf_label(_source) => array.get(rTfLabelCfg, _source - 1)
f_r_use_adx_di(_source) => array.get(rUseAdxCfg, _source - 1)
f_r_adx_min(_source) => array.get(rAdxMinCfg, _source - 1)
f_r_adx_value(_source) => array.get(rAdxNow, _source - 1)
f_r_di_plus(_source) => array.get(rDiPNow, _source - 1)
f_r_di_minus(_source) => array.get(rDiMNow, _source - 1)

f_r_adx_di_pass(_source, _dir) =>
    if not f_r_use_adx_di(_source)
        true
    else
        _a = f_r_adx_value(_source)
        _p = f_r_di_plus(_source)
        _m = f_r_di_minus(_source)
        _strong = not na(_a) and _a >= f_r_adx_min(_source)
        _agree = _dir == 1 ? _p > _m : _dir == -1 ? _m > _p : false
        _strong and _agree

f_r_logic_dir(_source) =>
    _d = f_r_dir(_source)
    f_r_adx_di_pass(_source, _d) ? _d : 0

//──────────────────────────────────────────────
// GT47 — ROLE-SPECIFIC GUARDIAN / TRIGGER MATH
// The selected R supplies TIMEFRAME identity. Independent role profiles use RAW MA math
// only and NEVER feed hmaCrossStored* / route-ray geometry.
//──────────────────────────────────────────────
f_role_pack(_type, _len) =>
    _rail = f_calc_r_rail(close, _type, _len)
    _delta = f_slope_angle(_rail, _rail[1])
    [_rail, _delta]

f_r_adx_text(_source) =>
    if not f_r_use_adx_di(_source)
        "OFF"
    else
        _a = f_r_adx_value(_source)
        _p = f_r_di_plus(_source)
        _m = f_r_di_minus(_source)
        (na(_a) ? "—" : str.tostring(_a, "#")) + " " + (_p >= _m ? "DI+" : "DI-")


f_r_stack(_source) =>
    _source == 1 ? r1OriginStackNow : _source == 2 ? r2OriginStackNow : _source == 3 ? r3OriginStackNow : _source == 4 ? r4OriginStackNow : _source == 5 ? r5OriginStackNow :
     _source == 6 ? r6OriginStackNow : _source == 7 ? r7OriginStackNow : _source == 8 ? r8OriginStackNow : _source == 9 ? r9OriginStackNow : r10OriginStackNow

f_rail_source_enabled(_source) =>
    f_r_enabled(_source) and (f_r_show_rays(_source) or f_r_route_rays(_source))

f_rail_source_visual(_source) =>
    f_r_enabled(_source) and f_r_show_rays(_source)

f_rail_source_tradeable(_source) =>
    _d = f_r_dir(_source)
    f_r_enabled(_source) and f_r_route_rays(_source) and f_r_adx_di_pass(_source, _d)


f_rail_ray_color(_source, _type) =>
    _source == 0 ? railTurnAverageColor : (_type == 1 ? railTurnValleyColor : railTurnPeakColor)

f_rail_source_name(_source) =>
    _source <= 0 ? "R-CLUSTER" :
     "R" + str.tostring(_source) + " " + f_r_type(_source) + str.tostring(f_r_len(_source)) +
     (str.length(f_r_tf(_source)) > 0 ? " " + f_r_tf(_source) : " CHART")

f_rail_source_dir(_source, _fallbackType) =>
    _dir = _source > 0 ? f_r_dir(_source) : 0
    _dir == 1 ? "UP" : _dir == -1 ? "DOWN" : _dir == 0 ? "FLAT" : (_fallbackType == 1 ? "UP" : "DOWN")

// Find the immediately previous opposite standalone pivot ray to the left.
// Display arrays are chronological oldest→newest. Blue clusters (type 0) are
// deliberately skipped as exit targets in this first logic.
f_previous_pivot_target(_prices, _bars, _types, _sources, _currentBar, _currentType, _currentSource, _sameRailOnly) =>
    float _target = na
    _wantedType = -_currentType
    _i = array.size(_prices) - 1
    while _i >= 0 and na(_target)
        _bar = array.get(_bars, _i)
        _type = array.get(_types, _i)
        _source = array.get(_sources, _i)
        _sourceOk = _source > 0 and f_rail_source_tradeable(_source) and (not _sameRailOnly or _source == _currentSource)
        if _bar < _currentBar and _type == _wantedType and _sourceOk
            _target := array.get(_prices, _i)
        _i -= 1
    _target

// Same search as above, but returns the origin bar of the selected target.
// v12.42 needs the bar identity so a continuation leg can look farther left
// from the checkpoint it just reached.
f_previous_pivot_target_bar(_bars, _types, _sources, _currentBar, _currentType, _currentSource, _sameRailOnly) =>
    int _targetBar = na
    _wantedType = -_currentType
    _i = array.size(_bars) - 1
    while _i >= 0 and na(_targetBar)
        _bar = array.get(_bars, _i)
        _type = array.get(_types, _i)
        _source = array.get(_sources, _i)
        _sourceOk = _source > 0 and f_rail_source_tradeable(_source) and (not _sameRailOnly or _source == _currentSource)
        if _bar < _currentBar and _type == _wantedType and _sourceOk
            _targetBar := _bar
        _i -= 1
    _targetBar

// After a checkpoint is accepted in the SAME direction, move one checkpoint
// farther left through the historical route map.
// Up routes travel PEAK checkpoints; down routes travel VALLEY checkpoints.
// We skip checkpoints that are not actually farther ahead in price.
f_next_forward_checkpoint(_prices, _bars, _types, _sources, _fromBar, _fromPrice, _direction, _routeSource, _sameRailOnly) =>
    float _target = na
    int _targetBar = na
    _wantedType = _direction == 1 ? -1 : 1
    _i = array.size(_prices) - 1
    while _i >= 0 and na(_target)
        _bar = array.get(_bars, _i)
        _type = array.get(_types, _i)
        _source = array.get(_sources, _i)
        _price = array.get(_prices, _i)
        _sourceOk = _source > 0 and f_rail_source_tradeable(_source) and (not _sameRailOnly or _source == _routeSource)
        _ahead = _direction == 1 ? _price > _fromPrice : _price < _fromPrice
        if _bar < _fromBar and _type == _wantedType and _sourceOk and _ahead
            _target := _price
            _targetBar := _bar
        _i -= 1
    [_target, _targetBar]

var int guardianConfirmedMeaningfulDir = 0
var int guardianLastCommittedPeriodId = na

f_guardian_source() =>
    f_r_slot_id(effGuardianRailSlot)

f_trigger_source() =>
    f_r_slot_id(effTriggerRailSlot)

_guardianRoleSource = f_guardian_source()
_triggerRoleSource = f_trigger_source()
_guardianRoleTf = f_r_tf(_guardianRoleSource)
_triggerRoleTf = f_r_tf(_triggerRoleSource)

[guardianIndependentRail, guardianIndependentDelta] = request.security(
     rTickerId, _guardianRoleTf, f_role_pack(effGuardianProfileType, effGuardianProfileLen),
     barmerge.gaps_off, barmerge.lookahead_off)
[triggerIndependentRail, triggerIndependentDelta] = request.security(
     rTickerId, _triggerRoleTf, f_role_pack(effTriggerProfileType, effTriggerProfileLen),
     barmerge.gaps_off, barmerge.lookahead_off)

guardianIndependentDir = f_slope_dir(guardianIndependentDelta)
triggerIndependentDir = f_slope_dir(triggerIndependentDelta)
var int guardianIndependentLastMeaningfulDir = 0
if guardianIndependentDir != 0
    guardianIndependentLastMeaningfulDir := guardianIndependentDir

f_guardian_role_value() =>
    effGuardianIndependentProfile ? guardianIndependentRail : f_r_rail(f_guardian_source())

f_guardian_role_dir() =>
    _src = f_guardian_source()
    _base = effGuardianIndependentProfile ?
         (guardianIndependentLastMeaningfulDir != 0 ? guardianIndependentLastMeaningfulDir : guardianIndependentDir) :
         (f_r_last_meaningful_dir(_src) != 0 ? f_r_last_meaningful_dir(_src) : f_r_dir(_src))
    f_r_enabled(_src) and f_r_adx_di_pass(_src, _base) ? _base : 0

f_trigger_role_dir() =>
    _src = f_trigger_source()
    _d = effTriggerIndependentProfile ? triggerIndependentDir : f_r_dir(_src)
    f_r_enabled(_src) and f_r_adx_di_pass(_src, _d) ? _d : 0

f_guardian_profile_text() =>
    effGuardianIndependentProfile ? effGuardianProfileType + str.tostring(effGuardianProfileLen) : "R-RAIL"

f_trigger_profile_text() =>
    effTriggerIndependentProfile ? effTriggerProfileType + str.tostring(effTriggerProfileLen) : "R-RAIL"

f_guardian_value() =>
    f_guardian_role_value()

f_guardian_dir() =>
    f_guardian_role_dir()

f_trigger_dir() =>
    f_trigger_role_dir()

f_guardian_intact(_dir, _bufferPrice) =>
    if effGuardianBreakDefinition == "Guardian Direction Flip"
        // Direction-flip authority is committed only at the selected Guardian
        // source-timeframe close. Exact-flat does not erase the last meaningful dir.
        _gDir = guardianConfirmedMeaningfulDir
        _dir == 1 ? _gDir == 1 :
         _dir == -1 ? _gDir == -1 : false
    else
        _g = f_guardian_value()
        _guardClose = realClose
        _dir == 1 ? (not na(_guardClose) and _guardClose >= _g - _bufferPrice) :
         _dir == -1 ? (not na(_guardClose) and _guardClose <= _g + _bufferPrice) : false

f_guardian_broken_for_dir(_dir, _bufferPrice) =>
    if effGuardianBreakDefinition == "Guardian Direction Flip"
        _gDir = guardianConfirmedMeaningfulDir
        _dir == 1 ? _gDir == -1 :
         _dir == -1 ? _gDir == 1 : false
    else
        _g = f_guardian_value()
        _guardClose = realClose
        _dir == 1 ? (not na(_guardClose) and _guardClose < _g - _bufferPrice) :
         _dir == -1 ? (not na(_guardClose) and _guardClose > _g + _bufferPrice) : false

_guardianCommitSource = f_guardian_source()
_guardianCommitTfInput = f_r_tf(_guardianCommitSource)
_guardianCommitTf = str.length(_guardianCommitTfInput) == 0 ? timeframe.period : _guardianCommitTfInput
_guardianCommitPeriodId = time_close(_guardianCommitTf)
_guardianSourceCloseWindow = barstate.isconfirmed and not na(_guardianCommitPeriodId) and time_close == _guardianCommitPeriodId
_guardianSourceCommitNow = _guardianSourceCloseWindow and (na(guardianLastCommittedPeriodId) or _guardianCommitPeriodId != guardianLastCommittedPeriodId)

if _guardianSourceCommitNow and f_r_enabled(_guardianCommitSource)
    guardianLastCommittedPeriodId := _guardianCommitPeriodId
    _guardianDirAtSourceClose = f_guardian_role_dir()
    if _guardianDirAtSourceClose != 0
        guardianConfirmedMeaningfulDir := _guardianDirAtSourceClose

// Store R1-R10 turn rays. Each R slot owns its own rail type/timeframe/length.
// Source ID is the R number, not the rail family.
if f_pair_r_on(1) and (r1CrossUp or r1CrossDown)
    f_store_rail_turn(r1InverseRail, bar_index - 1, time[1], r1CrossUp ? 1 : -1, 1)
if f_pair_r_on(2) and (r2CrossUp or r2CrossDown)
    f_store_rail_turn(r2InverseRail, bar_index - 1, time[1], r2CrossUp ? 1 : -1, 2)
if f_pair_r_on(3) and (r3CrossUp or r3CrossDown)
    f_store_rail_turn(r3InverseRail, bar_index - 1, time[1], r3CrossUp ? 1 : -1, 3)
if f_pair_r_on(4) and (r4CrossUp or r4CrossDown)
    f_store_rail_turn(r4InverseRail, bar_index - 1, time[1], r4CrossUp ? 1 : -1, 4)
if f_pair_r_on(5) and (r5CrossUp or r5CrossDown)
    f_store_rail_turn(r5InverseRail, bar_index - 1, time[1], r5CrossUp ? 1 : -1, 5)
if f_pair_r_on(6) and (r6CrossUp or r6CrossDown)
    f_store_rail_turn(r6InverseRail, bar_index - 1, time[1], r6CrossUp ? 1 : -1, 6)
if f_pair_r_on(7) and (r7CrossUp or r7CrossDown)
    f_store_rail_turn(r7InverseRail, bar_index - 1, time[1], r7CrossUp ? 1 : -1, 7)
if f_pair_r_on(8) and (r8CrossUp or r8CrossDown)
    f_store_rail_turn(r8InverseRail, bar_index - 1, time[1], r8CrossUp ? 1 : -1, 8)
if f_pair_r_on(9) and (r9CrossUp or r9CrossDown)
    f_store_rail_turn(r9InverseRail, bar_index - 1, time[1], r9CrossUp ? 1 : -1, 9)
if f_pair_r_on(10) and (r10CrossUp or r10CrossDown)
    f_store_rail_turn(r10InverseRail, bar_index - 1, time[1], r10CrossUp ? 1 : -1, 10)

while array.size(hmaCrossStoredPrices) > effHmaCrossRegistryLimit
    array.shift(hmaCrossStoredPrices)
    array.shift(hmaCrossStoredBars)
    array.shift(hmaCrossStoredTimes)
    array.shift(hmaCrossStoredTypes)
    array.shift(hmaCrossStoredSources)

// V6.4.2 visual ZAG state. Same causal projection formula as the working ZAG,
// but its history comes from the deep DISPLAY registry so drawing cannot disappear
// when the route-ray scan depth is intentionally small.
f_visual_zag_state(_source) =>
    float _latestPrice = na
    float _prevPrice = na
    int _latestBar = na
    int _prevBar = na
    int _found = 0
    int _i = array.size(zagVisualStoredBars) - 1
    while _i >= 0 and _found < 2
        if array.get(zagVisualStoredSources, _i) == _source
            if _found == 0
                _latestPrice := array.get(zagVisualStoredPrices, _i)
                _latestBar := array.get(zagVisualStoredBars, _i)
            else
                _prevPrice := array.get(zagVisualStoredPrices, _i)
                _prevBar := array.get(zagVisualStoredBars, _i)
            _found += 1
        _i -= 1

    float _zag = f_r_raw_rail(_source)
    int _zagDir = f_r_raw_last_meaningful_dir(_source)
    if _found == 2 and _latestBar > _prevBar
        float _mag = math.abs((_latestPrice - _prevPrice) / (_latestBar - _prevBar))
        int _activeDir = f_r_raw_last_meaningful_dir(_source)
        if _activeDir == 0
            _activeDir := _latestPrice >= _prevPrice ? -1 : 1
        _zag := _latestPrice + _activeDir * _mag * math.max(0, bar_index - _latestBar)
        _zagDir := _activeDir
    [_zag, _zagDir]

// R1-R10 ZAG display. Each R controls its own segment count and width.
// The final dashed segment is the same causal ZAG projection available as a working rail.
var line[] rZagLines = array.new_line()

f_render_r_zags() =>
    while array.size(rZagLines) > 0
        line.delete(array.pop(rZagLines))

    int _source = 1
    while _source <= 10
        bool _isTradedZag = enableZagFlipTradeLogic and forcePlotTradedZag and _source == f_zag_flip_source()
        if f_r_enabled(_source) and (f_r_show_zag(_source) or _isTradedZag)
            int _newerIdx = na
            int _drawn = 0
            int _maxSegments = f_r_zag_segments(_source)
            int _zagWidth = f_r_zag_width(_source)
            int _scan = array.size(zagVisualStoredBars) - 1
            while _scan >= 0 and _drawn < _maxSegments
                if array.get(zagVisualStoredSources, _scan) == _source
                    if not na(_newerIdx)
                        int _b1 = array.get(zagVisualStoredBars, _scan)
                        float _p1 = array.get(zagVisualStoredPrices, _scan)
                        int _b2 = array.get(zagVisualStoredBars, _newerIdx)
                        float _p2 = array.get(zagVisualStoredPrices, _newerIdx)
                        color _c = _p2 > _p1 ? color.green : _p2 < _p1 ? color.red : color.gray
                        line _seg = line.new(_b1, _p1, _b2, _p2, xloc=xloc.bar_index, extend=extend.none, color=_c, width=_zagWidth)
                        array.push(rZagLines, _seg)
                        _drawn += 1
                    _newerIdx := _scan
                _scan -= 1

            // Active causal projection from latest confirmed turn.
            if not na(_newerIdx)
                int _anchorBar = array.get(zagVisualStoredBars, _newerIdx)
                float _anchorPrice = array.get(zagVisualStoredPrices, _newerIdx)
                [_zagNow, _zagDirNow] = f_visual_zag_state(_source)
                color _activeColor = _zagDirNow == 1 ? color.green : _zagDirNow == -1 ? color.red : color.gray
                line _active = line.new(_anchorBar, _anchorPrice, bar_index, _zagNow, xloc=xloc.bar_index, extend=extend.none,
                     color=color.new(_activeColor, 25), width=_zagWidth, style=line.style_dashed)
                array.push(rZagLines, _active)
        _source += 1

if barstate.islast or barstate.islastconfirmedhistory
    f_render_r_zags()

// V6.4.1 visual-only source badge. This reports the exact source selected by the
// same f_zag_flip_source() function used by the execution engine.
var label zagFlipSourceBadge = na
if barstate.islast and enableZagFlipTradeLogic and forcePlotTradedZag
    if not na(zagFlipSourceBadge)
        label.delete(zagFlipSourceBadge)
    int _badgeSrc = f_zag_flip_source()
    int _badgeTurns = 0
    int _badgeScan = array.size(zagVisualStoredSources) - 1
    while _badgeScan >= 0
        if array.get(zagVisualStoredSources, _badgeScan) == _badgeSrc
            _badgeTurns += 1
        _badgeScan -= 1
    string _badgeText = "ZAG FLIP SOURCE  R" + str.tostring(_badgeSrc) + "  " + f_r_tf_label(_badgeSrc) +
         "  " + f_r_type(_badgeSrc) + str.tostring(f_r_len(_badgeSrc)) + "  |  vertices " + str.tostring(_badgeTurns)
    zagFlipSourceBadge := label.new(bar_index, realHigh, _badgeText, xloc=xloc.bar_index, yloc=yloc.abovebar,
         style=label.style_label_left, color=color.new(color.black, 15), textcolor=color.white, size=size.tiny)

//──────────────────────────────────────────────
// V6.4 — PURE ZAG FLIP v1 EXECUTION
// IMPORTANT CAUSAL RULE:
// The plotted ZAG vertex is stored at bar_index-1 for visual geometry, but the trade is
// submitted HERE, on the current update where rCrossUp/rCrossDown becomes known.
// No order is back-dated to the pretty vertex. This prevents look-ahead execution.
//
// Valley confirmation (CrossUp)  -> desired position LONG.
// Peak confirmation   (CrossDown)-> desired position SHORT.
// Opposite position uses one TradingView reversal order + one atomic OANDA `flip` payload.
// Flat entries use ordinary buy/sell payloads. One accepted turn per chart bar prevents
// realtime oscillation from submitting repeated reversals on the same candle.
//──────────────────────────────────────────────
varip int zagFlipLastSubmittedBar = na
varip int zagFlipLastSubmittedDir = 0

int _zagFlipSourceNow = f_zag_flip_source()
bool _zagFlipSourceEnabled = f_r_enabled(_zagFlipSourceNow)
bool _zagFlipUpNow = enableZagFlipTradeLogic and _zagFlipSourceEnabled and f_zag_flip_up(_zagFlipSourceNow)
bool _zagFlipDownNow = enableZagFlipTradeLogic and _zagFlipSourceEnabled and f_zag_flip_down(_zagFlipSourceNow)
int _zagFlipDirNow = _zagFlipUpNow and not _zagFlipDownNow ? 1 : _zagFlipDownNow and not _zagFlipUpNow ? -1 : 0
bool _zagFlipFreshBar = na(zagFlipLastSubmittedBar) or bar_index != zagFlipLastSubmittedBar
float _pipRaw = f_r_raw_rail(_zagFlipSourceNow)
[_pipZag, _pipZagDir] = f_r_zag_state(_zagFlipSourceNow)
float _pipTick = syminfo.mintick
float _pipGapTicks = not na(_pipRaw) and not na(_pipZag) and _pipTick > 0 ? math.abs(_pipRaw - _pipZag) / _pipTick : na
float _pipRawStep = not na(_pipRaw[1]) and _pipTick > 0 ? (_pipRaw - _pipRaw[1]) / _pipTick : na
float _pipZagStep = not na(_pipZag[1]) and _pipTick > 0 ? (_pipZag - _pipZag[1]) / _pipTick : na
float _pipMismatch = not na(_pipRawStep) and not na(_pipZagStep) ? math.abs(_pipRawStep - _pipZagStep) : na
bool _pipSameTravel = not pipmanMergeRequireSameTravel or (not na(_pipRawStep) and not na(_pipZagStep) and _pipRawStep * _pipZagStep >= 0)
float _pipSpread = _pipRaw - _pipZag
float _pipSpreadPrev = _pipRaw[1] - _pipZag[1]
bool _pipCross = not na(_pipSpread) and not na(_pipSpreadPrev) and ((_pipSpread > 0 and _pipSpreadPrev < 0) or (_pipSpread < 0 and _pipSpreadPrev > 0))
bool _pipMergedBar = not na(_pipGapTicks) and _pipGapTicks <= pipmanMergeMaxGapTicks and not na(_pipMismatch) and _pipMismatch <= pipmanMergeMaxTrajectoryMismatchTicks and _pipSameTravel and (not pipmanMergeCrossDoesNotCount or not _pipCross)
int _pipMergeStreakPreTurn = nz(ta.barssince(not _pipMergedBar)[1], 0)
bool _pipPhysicalMerge = pipmanMergeEnable and _pipMergeStreakPreTurn >= pipmanMergeRequiredBars
bool _pipTurnBlocked = _zagFlipDirNow != 0 and _pipPhysicalMerge

varip int pipmanMergeSkippedTurns = 0
varip int pipmanMergeLastBlockedBar = na
if _pipTurnBlocked and (na(pipmanMergeLastBlockedBar) or pipmanMergeLastBlockedBar != bar_index)
    pipmanMergeLastBlockedBar := bar_index
    pipmanMergeSkippedTurns += 1
    if pipmanMergeShowSkipped
        label.new(bar_index, _zagFlipDirNow == 1 ? realLow : realHigh, "PIPMAN MERGE SKIP\n" + str.tostring(_pipMergeStreakPreTurn) + " bars", xloc=xloc.bar_index, yloc=_zagFlipDirNow == 1 ? yloc.belowbar : yloc.abovebar, style=_zagFlipDirNow == 1 ? label.style_label_up : label.style_label_down, color=color.black, textcolor=color.orange, size=size.tiny)

var label[] zagFlipRecentVisualLabels = array.new_label()
varip int zagFlipLastVisualBar = na
bool _zagFlipVisualFresh = _zagFlipDirNow != 0 and (na(zagFlipLastVisualBar) or zagFlipLastVisualBar != bar_index)
if showZagFlipMarkers and _zagFlipVisualFresh
    label _zfVisual = label.new(bar_index, _zagFlipDirNow == 1 ? realLow : realHigh, _zagFlipDirNow == 1 ? "ZAG FLIP S→L\nR" + str.tostring(_zagFlipSourceNow) : "ZAG FLIP L→S\nR" + str.tostring(_zagFlipSourceNow), xloc=xloc.bar_index, yloc=_zagFlipDirNow == 1 ? yloc.belowbar : yloc.abovebar, style=_zagFlipDirNow == 1 ? label.style_label_up : label.style_label_down, color=_zagFlipDirNow == 1 ? color.green : color.red, textcolor=color.white, size=size.small)
    zagFlipLastVisualBar := bar_index
    if showOnlyLastTwoZagFlipLabels
        array.push(zagFlipRecentVisualLabels, _zfVisual)
        while array.size(zagFlipRecentVisualLabels) > 2
            label.delete(array.shift(zagFlipRecentVisualLabels))

bool _zagFlipOperationalPass = enableZagFlipTradeLogic and entryGuardPass and executionEntryUpdate and not deferredRolloverArmed and not _pipTurnBlocked
float _zagFlipQty = f_strategy_order_units()
bool _zagFlipQtyOk = not na(_zagFlipQty) and _zagFlipQty > 0.0

// Retired trade engines have no order authority in this build.
if _zagFlipOperationalPass and _zagFlipQtyOk and _zagFlipFreshBar and _zagFlipDirNow != 0
    if _zagFlipDirNow == 1 and zagFlipAllowLongs and strategy.position_size <= 0
        bool _reversing = strategy.position_size < 0
        string _msg = _reversing ? f_oanda_flip_payload("long") : f_oanda_payload("buy")
        if zagFlipExecutionWebhookEnabled and barstate.isrealtime
            // Broker-state sync: always use FLIP for the webhook. Render/app.py decides
            // whether it needs to close short first, open long from flat, or ignore
            // an already-long same-side position.
            alert(f_oanda_flip_payload("long"), alert.freq_once_per_bar)
        strategy.entry("ZF-L", strategy.long, qty=_zagFlipQty,
             comment=_reversing ? "ZAG FLIP S→L" : "ZAG VALLEY → LONG",
             alert_message=_msg)
        zagFlipLastSubmittedBar := bar_index
        zagFlipLastSubmittedDir := 1
        lastPivotDecision := "ZAG FLIP R" + str.tostring(_zagFlipSourceNow) + " CONFIRMED VALLEY → LONG"

    else if _zagFlipDirNow == -1 and zagFlipAllowShorts and strategy.position_size >= 0
        bool _reversing = strategy.position_size > 0
        string _msg = _reversing ? f_oanda_flip_payload("short") : f_oanda_payload("sell")
        if zagFlipExecutionWebhookEnabled and barstate.isrealtime
            // Same broker-state synchronization contract for shorts.
            alert(f_oanda_flip_payload("short"), alert.freq_once_per_bar)
        strategy.entry("ZF-S", strategy.short, qty=_zagFlipQty,
             comment=_reversing ? "ZAG FLIP L→S" : "ZAG PEAK → SHORT",
             alert_message=_msg)
        zagFlipLastSubmittedBar := bar_index
        zagFlipLastSubmittedDir := -1
        lastPivotDecision := "ZAG FLIP R" + str.tostring(_zagFlipSourceNow) + " CONFIRMED PEAK → SHORT"


// Rebuild the FINAL consolidated ray registry on every bar so the exact same
// ray geometry can drive historical strategy testing, live alerts, and visuals.
// Only line-object drawing remains restricted to barstate.islast.
array.clear(visibleRayEventSources)
array.clear(visibleRayEventTypes)
array.clear(visibleRayEventDirs)
array.clear(visibleRayEventClusters)
array.clear(visibleRayEventPrices)
array.clear(visibleRayEventBars)
array.clear(visibleRayEventStacks)

array.clear(hmaCrossDisplayPrices)
array.clear(hmaCrossDisplayBars)
array.clear(hmaCrossDisplayTimes)
array.clear(hmaCrossDisplayTypes)
array.clear(hmaCrossDisplaySources)
array.clear(hmaCrossDisplayDriverTypes)
array.clear(hmaCrossDisplayDriverSources)

// Build a filtered chronological stream using only enabled rail sources.
_activePrices = array.new_float()
_activeBars = array.new_int()
_activeTimes = array.new_int()
_activeTypes = array.new_int()
_activeSources = array.new_int()

_storedCount = array.size(hmaCrossStoredPrices)
if _storedCount > 0
    _filterIdx = 0
    while _filterIdx < _storedCount
        _source = array.get(hmaCrossStoredSources, _filterIdx)
        if f_rail_source_enabled(_source)
            array.push(_activePrices, array.get(hmaCrossStoredPrices, _filterIdx))
            array.push(_activeBars, array.get(hmaCrossStoredBars, _filterIdx))
            array.push(_activeTimes, array.get(hmaCrossStoredTimes, _filterIdx))
            array.push(_activeTypes, array.get(hmaCrossStoredTypes, _filterIdx))
            array.push(_activeSources, _source)
        _filterIdx += 1

_activeCount = array.size(_activePrices)

// Consolidate enabled rail turns from oldest to newest.
if _activeCount > 0
    if not effAverageShallowHmaClutter
        _copyIdx = 0
        while _copyIdx < _activeCount
            _copyType = array.get(_activeTypes, _copyIdx)
            _copySource = array.get(_activeSources, _copyIdx)
            array.push(hmaCrossDisplayPrices, array.get(_activePrices, _copyIdx))
            array.push(hmaCrossDisplayBars, array.get(_activeBars, _copyIdx))
            array.push(hmaCrossDisplayTimes, array.get(_activeTimes, _copyIdx))
            array.push(hmaCrossDisplayTypes, _copyType)
            array.push(hmaCrossDisplaySources, _copySource)
            array.push(hmaCrossDisplayDriverTypes, _copyType)
            array.push(hmaCrossDisplayDriverSources, _copySource)
            _copyIdx += 1
    else
        _clusterIdx = 0
        while _clusterIdx < _activeCount
            _clusterStart = _clusterIdx
            _clusterEnd = _clusterIdx + 1
            _clusterSum = array.get(_activePrices, _clusterIdx)
            _clusterMin = array.get(_activePrices, _clusterIdx)
            _clusterMax = _clusterMin
            _clusterPeaks = array.get(_activeTypes, _clusterIdx) == -1 ? 1 : 0
            _clusterValleys = array.get(_activeTypes, _clusterIdx) == 1 ? 1 : 0
            _clusterCount = 1
            _clusterNewestBar = array.get(_activeBars, _clusterIdx)
            _clusterNewestTime = array.get(_activeTimes, _clusterIdx)
            _continueCluster = true

            while _clusterEnd < _activeCount and _continueCluster
                _nextPrice = array.get(_activePrices, _clusterEnd)
                _nextBar = array.get(_activeBars, _clusterEnd)
                _nextMin = math.min(_clusterMin, _nextPrice)
                _nextMax = math.max(_clusterMax, _nextPrice)
                _nextSpanPips = pipSize > 0.0 ? (_nextMax - _nextMin) / pipSize : 0.0
                _withinBars = _nextBar - array.get(_activeBars, _clusterStart) <= effHmaCrossClusterMaxBars
                _withinSpan = effHmaCrossClusterMaxSpanPips <= 0.0 or _nextSpanPips <= effHmaCrossClusterMaxSpanPips

                if _withinBars and _withinSpan
                    _nextType = array.get(_activeTypes, _clusterEnd)
                    _clusterSum += _nextPrice
                    _clusterMin := _nextMin
                    _clusterMax := _nextMax
                    _clusterPeaks += _nextType == -1 ? 1 : 0
                    _clusterValleys += _nextType == 1 ? 1 : 0
                    _clusterCount += 1
                    _clusterNewestBar := _nextBar
                    _clusterNewestTime := array.get(_activeTimes, _clusterEnd)
                    _clusterEnd += 1
                else
                    _continueCluster := false

            _mixedShallowCluster = _clusterCount >= 2 and _clusterPeaks > 0 and _clusterValleys > 0

            if _mixedShallowCluster
                _clusterDriverIdx = _clusterEnd - 1
                _clusterDriverType = array.get(_activeTypes, _clusterDriverIdx)
                _clusterDriverSource = array.get(_activeSources, _clusterDriverIdx)
                array.push(hmaCrossDisplayPrices, _clusterSum / _clusterCount)
                array.push(hmaCrossDisplayBars, _clusterNewestBar)
                array.push(hmaCrossDisplayTimes, _clusterNewestTime)
                array.push(hmaCrossDisplayTypes, 0)
                array.push(hmaCrossDisplaySources, 0)
                array.push(hmaCrossDisplayDriverTypes, _clusterDriverType)
                array.push(hmaCrossDisplayDriverSources, _clusterDriverSource)
            else
                _memberIdx = _clusterStart
                while _memberIdx < _clusterEnd
                    _memberType = array.get(_activeTypes, _memberIdx)
                    _memberSource = array.get(_activeSources, _memberIdx)
                    array.push(hmaCrossDisplayPrices, array.get(_activePrices, _memberIdx))
                    array.push(hmaCrossDisplayBars, array.get(_activeBars, _memberIdx))
                    array.push(hmaCrossDisplayTimes, array.get(_activeTimes, _memberIdx))
                    array.push(hmaCrossDisplayTypes, _memberType)
                    array.push(hmaCrossDisplaySources, _memberSource)
                    array.push(hmaCrossDisplayDriverTypes, _memberType)
                    array.push(hmaCrossDisplayDriverSources, _memberSource)
                    _memberIdx += 1

            _clusterIdx := _clusterEnd

_candidateCount = array.size(hmaCrossDisplayPrices)

// New FINAL ray events are created here on EVERY bar. A newly finalized candidate
// is guaranteed visible at formation by the drawing rule below, so this remains 1:1
// with the visual ray while also making historical strategy testing possible.
if _candidateCount > 0
    _evtIdx = 0
    while _evtIdx < _candidateCount
        _evtBar = array.get(hmaCrossDisplayBars, _evtIdx)
        if _evtBar == bar_index - 1
            _evtPrice = array.get(hmaCrossDisplayPrices, _evtIdx)
            _evtRaySource = array.get(hmaCrossDisplaySources, _evtIdx)
            _evtDriverType = array.get(hmaCrossDisplayDriverTypes, _evtIdx)
            _evtDriverSource = array.get(hmaCrossDisplayDriverSources, _evtIdx)
            _evtDriverName = f_rail_source_name(_evtDriverSource)
            _evtEventName = _evtDriverType == 1 ? "VALLEY" : "PEAK"
            _evtDriverDir = _evtDriverSource > 0 ? f_r_dir(_evtDriverSource) : 0
            _evtDirectionName = f_rail_source_dir(_evtDriverSource, _evtDriverType)
            _evtCluster = _evtRaySource == 0
            _evtStack = _evtCluster ? 0 : f_r_stack(_evtDriverSource)
            _evtText = _evtDriverName + " " + _evtEventName + (_evtCluster ? " → CLUSTER RAY" : " RAY") + " | " + _evtDirectionName + (_evtCluster ? "" : " | STACK " + str.tostring(_evtStack))

            // Alerts and trade events follow the per-R Route Rays permission.
            if _evtDriverSource > 0 and f_rail_source_tradeable(_evtDriverSource)
                visibleRailRayAlertMessage += (str.length(visibleRailRayAlertMessage) > 0 ? " || " : "") + _evtText
                array.push(visibleRayEventSources, _evtDriverSource)
                array.push(visibleRayEventTypes, _evtDriverType)
                array.push(visibleRayEventDirs, _evtDriverDir)
                array.push(visibleRayEventClusters, _evtCluster)
                array.push(visibleRayEventPrices, _evtPrice)
                array.push(visibleRayEventBars, _evtBar)
                array.push(visibleRayEventStacks, _evtStack)
        _evtIdx += 1

// Draw on the realtime last bar OR the last confirmed historical bar.
// This keeps line-object rays visible even though the strategy intentionally uses
// realtime execution is tick-driven; historical execution still follows the selected History Bar Tick setting.
f_scope_render_hma_rays() =>
    while array.size(hmaCrossRayLines) > 0
        line.delete(array.pop(hmaCrossRayLines))

    if showHmaCrossingRays and _candidateCount > 0
        _selected = array.new_bool(_candidateCount, false)

        // A newly finalized ray is guaranteed visible on the bar it forms.
        _newAboveCount = 0
        _newBelowCount = 0
        _forceIdx = 0
        while _forceIdx < _candidateCount
            _forceBar = array.get(hmaCrossDisplayBars, _forceIdx)
            if _forceBar == bar_index - 1
                _forceDriverSource = array.get(hmaCrossDisplayDriverSources, _forceIdx)
                if _forceDriverSource > 0 and f_rail_source_visual(_forceDriverSource)
                    array.set(_selected, _forceIdx, true)
                    _forcePrice = array.get(hmaCrossDisplayPrices, _forceIdx)
                    if _forcePrice >= realClose
                        _newAboveCount += 1
                    else
                        _newBelowCount += 1
            _forceIdx += 1

        _aboveSlot = math.min(_newAboveCount, hmaCrossRaysPerSide)
        while _aboveSlot < hmaCrossRaysPerSide
            int _bestAbove = na
            float _bestAboveDist = na
            int _bestAboveBar = na
            _scanAbove = 0
            while _scanAbove < _candidateCount
                _candidatePrice = array.get(hmaCrossDisplayPrices, _scanAbove)
                _candidateBar = array.get(hmaCrossDisplayBars, _scanAbove)
                _candidateDriverSource = array.get(hmaCrossDisplayDriverSources, _scanAbove)
                _eligibleAbove = not array.get(_selected, _scanAbove) and _candidatePrice >= realClose and _candidateDriverSource > 0 and f_rail_source_visual(_candidateDriverSource)
                _candidateDist = math.abs(_candidatePrice - realClose)
                _betterAbove = _eligibleAbove and (na(_bestAboveDist) or _candidateDist < _bestAboveDist or
                     (_candidateDist == _bestAboveDist and _candidateBar > _bestAboveBar))
                if _betterAbove
                    _bestAbove := _scanAbove
                    _bestAboveDist := _candidateDist
                    _bestAboveBar := _candidateBar
                _scanAbove += 1
            if na(_bestAbove)
                _aboveSlot := hmaCrossRaysPerSide
            else
                array.set(_selected, _bestAbove, true)
                _aboveSlot += 1

        _belowSlot = math.min(_newBelowCount, hmaCrossRaysPerSide)
        while _belowSlot < hmaCrossRaysPerSide
            int _bestBelow = na
            float _bestBelowDist = na
            int _bestBelowBar = na
            _scanBelow = 0
            while _scanBelow < _candidateCount
                _candidatePrice = array.get(hmaCrossDisplayPrices, _scanBelow)
                _candidateBar = array.get(hmaCrossDisplayBars, _scanBelow)
                _candidateDriverSource = array.get(hmaCrossDisplayDriverSources, _scanBelow)
                _eligibleBelow = not array.get(_selected, _scanBelow) and _candidatePrice < realClose and _candidateDriverSource > 0 and f_rail_source_visual(_candidateDriverSource)
                _candidateDist = math.abs(realClose - _candidatePrice)
                _betterBelow = _eligibleBelow and (na(_bestBelowDist) or _candidateDist < _bestBelowDist or
                     (_candidateDist == _bestBelowDist and _candidateBar > _bestBelowBar))
                if _betterBelow
                    _bestBelow := _scanBelow
                    _bestBelowDist := _candidateDist
                    _bestBelowBar := _candidateBar
                _scanBelow += 1
            if na(_bestBelow)
                _belowSlot := hmaCrossRaysPerSide
            else
                array.set(_selected, _bestBelow, true)
                _belowSlot += 1

        _drawn = array.new_bool(_candidateCount, false)
        _drawRank = 0
        while _drawRank < _candidateCount
            int _newestSelected = na
            int _newestSelectedBar = na
            _scanDraw = 0
            while _scanDraw < _candidateCount
                _canDraw = array.get(_selected, _scanDraw) and not array.get(_drawn, _scanDraw)
                _candidateBar = array.get(hmaCrossDisplayBars, _scanDraw)
                if _canDraw and (na(_newestSelectedBar) or _candidateBar > _newestSelectedBar)
                    _newestSelected := _scanDraw
                    _newestSelectedBar := _candidateBar
                _scanDraw += 1

            if na(_newestSelected)
                _drawRank := _candidateCount
            else
                _rayPrice = array.get(hmaCrossDisplayPrices, _newestSelected)
                _rayTime = array.get(hmaCrossDisplayTimes, _newestSelected)
                _rayType = array.get(hmaCrossDisplayTypes, _newestSelected)
                _raySource = array.get(hmaCrossDisplaySources, _newestSelected)
                _rayColor = f_rail_ray_color(_raySource, _rayType)
                _ray = line.new(_rayTime, _rayPrice, time, _rayPrice, xloc=xloc.bar_time, extend=extend.right,
                     color=_rayColor, width=hmaCrossRayWidth, style=hmaCrossLineStyle)
                array.push(hmaCrossRayLines, _ray)
                array.set(_drawn, _newestSelected, true)
                _drawRank += 1
if barstate.islast or barstate.islastconfirmedhistory
    f_scope_render_hma_rays()

//──────────────────────────────────────────────
// LEAN: legacy diagonal swing-ray plotting removed (visual only).

// Six-pair scanner removed in v12.44E5. Current-chart rail/ray engine continues below.
//──────────────────────────────────────────────
//
// Plots — VISUAL ONLY
//──────────────────────────────────────────────
// R1-R10 are now the primary visual rails.
// Legacy backend rail plots/data-window rails were removed to preserve TradingView's plot-count budget.
plot(f_pair_r_on(1) and r1_showLine ? r1Rail : na, "R1 Line", color=r1Color, linewidth=2)
plot(f_pair_r_on(1) and r1_showDots ? r1Rail : na, "R1 Dots", color=r1Color, linewidth=r1_dotWidth, style=plot.style_circles)
plot(f_pair_r_on(2) and r2_showLine ? r2Rail : na, "R2 Line", color=r2Color, linewidth=2)
plot(f_pair_r_on(2) and r2_showDots ? r2Rail : na, "R2 Dots", color=r2Color, linewidth=r2_dotWidth, style=plot.style_circles)
plot(f_pair_r_on(3) and r3_showLine ? r3Rail : na, "R3 Line", color=r3Color, linewidth=2)
plot(f_pair_r_on(3) and r3_showDots ? r3Rail : na, "R3 Dots", color=r3Color, linewidth=r3_dotWidth, style=plot.style_circles)
plot(f_pair_r_on(4) and r4_showLine ? r4Rail : na, "R4 Line", color=r4Color, linewidth=2)
plot(f_pair_r_on(4) and r4_showDots ? r4Rail : na, "R4 Dots", color=r4Color, linewidth=r4_dotWidth, style=plot.style_circles)
plot(f_pair_r_on(5) and r5_showLine ? r5Rail : na, "R5 Line", color=r5Color, linewidth=2)
plot(f_pair_r_on(5) and r5_showDots ? r5Rail : na, "R5 Dots", color=r5Color, linewidth=r5_dotWidth, style=plot.style_circles)
plot(f_pair_r_on(6) and r6_showLine ? r6Rail : na, "R6 Line", color=r6Color, linewidth=2)
plot(f_pair_r_on(6) and r6_showDots ? r6Rail : na, "R6 Dots", color=r6Color, linewidth=r6_dotWidth, style=plot.style_circles)
plot(f_pair_r_on(7) and r7_showLine ? r7Rail : na, "R7 Line", color=r7Color, linewidth=2)
plot(f_pair_r_on(7) and r7_showDots ? r7Rail : na, "R7 Dots", color=r7Color, linewidth=r7_dotWidth, style=plot.style_circles)
plot(f_pair_r_on(8) and r8_showLine ? r8Rail : na, "R8 Line", color=r8Color, linewidth=2)
plot(f_pair_r_on(8) and r8_showDots ? r8Rail : na, "R8 Dots", color=r8Color, linewidth=r8_dotWidth, style=plot.style_circles)
plot(f_pair_r_on(9) and r9_showLine ? r9Rail : na, "R9 Line", color=r9Color, linewidth=2)
plot(f_pair_r_on(9) and r9_showDots ? r9Rail : na, "R9 Dots", color=r9Color, linewidth=r9_dotWidth, style=plot.style_circles)
plot(f_pair_r_on(10) and r10_showLine ? r10Rail : na, "R10 Line", color=r10Color, linewidth=2)
plot(f_pair_r_on(10) and r10_showDots ? r10Rail : na, "R10 Dots", color=r10Color, linewidth=r10_dotWidth, style=plot.style_circles)

plotshape(showBreakMarkers and realBullCloseBreak and not realBullOwnWickBreak, title="Close Above Previous Real Wick", style=shape.circle,
     location=location.abovebar, size=size.tiny, color=bullCloseBreakColor, text="W↑")
plotshape(showBreakMarkers and realBearCloseBreak and not realBearOwnWickBreak, title="Close Below Previous Real Wick", style=shape.circle,
     location=location.belowbar, size=size.tiny, color=bearCloseBreakColor, text="W↓")
plotshape(showBreakMarkers and realBullOwnWickBreak, title="Close Above Prev Wick + Own Upper Wick", style=shape.diamond,
     location=location.abovebar, size=size.tiny, color=bullOwnWickBreakColor, text="W+↑")
plotshape(showBreakMarkers and realBearOwnWickBreak, title="Close Below Prev Wick + Own Lower Wick", style=shape.diamond,
     location=location.belowbar, size=size.tiny, color=bearOwnWickBreakColor, text="W+↓")

// Unified R / ADX regime state.
// The fixed timeframe bay itself is now the regime source; no second H/W/K/E grid.
f_r_regime_state(_source) =>
    _rail = f_r_rail(_source)
    f_r_enabled(_source) and not na(_rail) ? f_regime_state(realClose, _rail, _rail[1]) : 0

rReg1 = f_r_regime_state(1)
rReg2 = f_r_regime_state(2)
rReg3 = f_r_regime_state(3)
rReg4 = f_r_regime_state(4)
rReg5 = f_r_regime_state(5)
rReg6 = f_r_regime_state(6)
rReg7 = f_r_regime_state(7)
rReg8 = f_r_regime_state(8)
rReg9 = f_r_regime_state(9)
rReg10 = f_r_regime_state(10)

//──────────────────────────────────────────────
// LEAN: informational ray/context alert formatting removed; trade context math remains.


//──────────────────────────────────────────────
// 09 — PIPMAN DIAGNOSTIC TABLE
//──────────────────────────────────────────────
var table pipmanMergeTable = table.new(position.bottom_left, 2, 9, border_width=1)
f_render_pipman_merge_table() =>
    table.set_position(pipmanMergeTable, f_tgim_table_position(pipmanMergeTablePositionInput))
    if pipmanMergeShowTable
        table.cell(pipmanMergeTable, 0, 0, "PIPMAN PHYSICAL MERGE", bgcolor=color.rgb(40,46,57), text_color=color.white)
        table.cell(pipmanMergeTable, 1, 0, pipmanMergeEnable ? "ON" : "OFF", bgcolor=color.rgb(40,46,57), text_color=pipmanMergeEnable ? color.lime : color.gray)
        table.cell(pipmanMergeTable, 0, 1, "RAW↔ZAG GAP")
        table.cell(pipmanMergeTable, 1, 1, na(_pipGapTicks) ? "—" : str.tostring(_pipGapTicks, "#.00") + " ticks")
        table.cell(pipmanMergeTable, 0, 2, "MAX GAP")
        table.cell(pipmanMergeTable, 1, 2, str.tostring(pipmanMergeMaxGapTicks, "#.00") + " ticks")
        table.cell(pipmanMergeTable, 0, 3, "TRAJECTORY MISMATCH")
        table.cell(pipmanMergeTable, 1, 3, na(_pipMismatch) ? "—" : str.tostring(_pipMismatch, "#.00") + " ticks/bar")
        table.cell(pipmanMergeTable, 0, 4, "MAX MISMATCH")
        table.cell(pipmanMergeTable, 1, 4, str.tostring(pipmanMergeMaxTrajectoryMismatchTicks, "#.00") + " ticks/bar")
        table.cell(pipmanMergeTable, 0, 5, "PRE-TURN MERGE STREAK")
        table.cell(pipmanMergeTable, 1, 5, str.tostring(_pipMergeStreakPreTurn) + " / " + str.tostring(pipmanMergeRequiredBars))
        table.cell(pipmanMergeTable, 0, 6, "CROSS / X-TOUCH")
        table.cell(pipmanMergeTable, 1, 6, _pipCross ? "YES — NOT MERGE" : "NO", text_color=_pipCross ? color.orange : color.lime)
        table.cell(pipmanMergeTable, 0, 7, "SKIPPED TURNS")
        table.cell(pipmanMergeTable, 1, 7, str.tostring(pipmanMergeSkippedTurns))
        table.cell(pipmanMergeTable, 0, 8, "STATE")
        table.cell(pipmanMergeTable, 1, 8, _pipPhysicalMerge ? "MERGED / BLOCK NEXT TURN" : "TOUCH / SEPARATED", text_color=_pipPhysicalMerge ? color.orange : color.lime)

if barstate.islast
    f_render_pipman_merge_table()


//──────────────────────────────────────────────
// 10 — FOREX COMPOUND / $1M TRAJECTORY
// FX-specific research model. It does not override live OANDA backend sizing.
//──────────────────────────────────────────────
groupCompound = "10 — FOREX COMPOUND / $1M"
compoundModelEnable = input.bool(true, "Enable Compounding Model", group=groupCompound)
compoundFrequency = input.string("Per Trade", "Compounding Frequency", options=["Per Trade","Daily"], group=groupCompound)
compoundGoal = input.float(1000000.0, "Compound Goal ($)", minval=1000.0, step=10000.0, group=groupCompound)
compoundStartEquityInput = input.float(100.0, "Research Starting Equity ($)", minval=1.0, step=50.0, group=groupCompound)
compoundFreezeAtGoal = input.bool(true, "Freeze Projection At First Goal Hit", group=groupCompound)
compoundBenchmarkCalendarDays = input.int(90, "Record Benchmark (calendar days)", minval=1, maxval=3650, group=groupCompound)
compoundMinSampleDays = input.int(30, "Minimum Sample Days Before Mature Trajectory", minval=1, maxval=500, group=groupCompound)
compoundShowTable = input.bool(true, "Show Compound / $1M Table", group=groupCompound)
compoundTablePositionInput = input.string("Bottom Center", "Compound Table Position", options=["Top Left","Top Center","Top Right","Middle Left","Middle Center","Middle Right","Bottom Left","Bottom Center","Bottom Right"], group=groupCompound)

groupDollarLabels = "10A — COMPOUND DOLLAR LABELS"
showCompoundDollarLabels = input.bool(true, "Show Dollar Compounding Labels", group=groupDollarLabels)
compoundDollarLabelFormat = input.string("Equity Only", "Dollar Label Format", options=["Equity Only","P/L + Equity","P/L Only"], group=groupDollarLabels)
compoundDollarLabelSize = input.string("Normal", "Dollar Label Size", options=["Tiny","Small","Normal"], group=groupDollarLabels)
compoundDollarLabelOffsetTicks = input.int(27, "Dollar Label Offset (ticks)", minval=0, maxval=250, group=groupDollarLabels)

f_cmp_label_size() =>
    compoundDollarLabelSize == "Tiny" ? size.tiny : compoundDollarLabelSize == "Small" ? size.small : size.normal
f_cmp_money(_v) => "$" + str.tostring(_v, "#,###.##")
f_cmp_signed(_v) => (_v >= 0 ? "+" : "-") + "$" + str.tostring(math.abs(_v), "#,###.##")
f_cmp_day_key(_ts) => year(_ts, "America/New_York") * 10000 + month(_ts, "America/New_York") * 100 + dayofmonth(_ts, "America/New_York")

varip float cmpEquity = compoundStartEquityInput
varip float cmpDayStartEquity = compoundStartEquityInput
varip float cmpDayRawPnl = 0.0
varip int cmpDayKey = na
varip int cmpDays = 0
varip int cmpTrades = 0
varip int cmpClosedSeen = 0
varip int cmpStartTime = na
varip bool cmpGoalHit = false
varip int cmpGoalHitDay = na
varip int cmpGoalHitTrade = na
varip int cmpGoalHitTime = na
varip float cmpGoalHitEquity = na
varip int cmpWins = 0
varip int cmpLosses = 0

f_cmp_scale(_equity) =>
    compoundStartEquityInput > 0 ? math.max(0.0, _equity / compoundStartEquityInput) : 1.0

if strategy.closedtrades > cmpClosedSeen
    int _ci = cmpClosedSeen
    while _ci < strategy.closedtrades
        float _rawPnl = strategy.closedtrades.profit(_ci)
        int _exitBar = strategy.closedtrades.exit_bar_index(_ci)
        int _exitTime = strategy.closedtrades.exit_time(_ci)
        int _k = f_cmp_day_key(_exitTime)
        bool _newDay = na(cmpDayKey) or _k != cmpDayKey
        cmpWins += _rawPnl > 0 ? 1 : 0
        cmpLosses += _rawPnl < 0 ? 1 : 0

        if compoundModelEnable and not (compoundFreezeAtGoal and cmpGoalHit)
            if na(cmpStartTime)
                cmpStartTime := _exitTime
            if _newDay
                cmpDayKey := _k
                cmpDays += 1
                cmpDayStartEquity := cmpEquity
                cmpDayRawPnl := 0.0

            float _basis = compoundFrequency == "Daily" ? cmpDayStartEquity : cmpEquity
            float _scale = f_cmp_scale(_basis)
            if compoundFrequency == "Daily"
                cmpDayRawPnl += _rawPnl
                cmpEquity := math.max(0.0, cmpDayStartEquity + cmpDayRawPnl * _scale)
            else
                cmpEquity := math.max(0.0, cmpEquity + _rawPnl * _scale)

            cmpTrades += 1
            if not cmpGoalHit and cmpEquity >= compoundGoal
                cmpGoalHit := true
                cmpGoalHitDay := cmpDays
                cmpGoalHitTrade := cmpTrades
                cmpGoalHitTime := _exitTime
                cmpGoalHitEquity := cmpEquity

        if showCompoundDollarLabels
            string _txt = compoundDollarLabelFormat == "Equity Only" ? f_cmp_money(cmpEquity) : compoundDollarLabelFormat == "P/L Only" ? f_cmp_signed(_rawPnl) : f_cmp_signed(_rawPnl) + "\n" + f_cmp_money(cmpEquity)
            float _off = syminfo.mintick * compoundDollarLabelOffsetTicks
            label.new(_exitBar, _rawPnl >= 0 ? high + _off : low - _off, _txt, xloc=xloc.bar_index, yloc=yloc.price, style=label.style_none, textcolor=color.rgb(24,31,42), size=f_cmp_label_size())

        _ci += 1
    cmpClosedSeen := strategy.closedtrades

var table compoundTrajectoryTable = table.new(position.bottom_center, 2, 15, border_width=1)

f_render_compound_table() =>
    table.set_position(compoundTrajectoryTable, f_tgim_table_position(compoundTablePositionInput))
    if compoundShowTable
        int _obsDays = math.max(1, cmpDays)
        int _growthDays = cmpGoalHit ? math.max(1, cmpGoalHitDay) : _obsDays
        float _growthEq = cmpGoalHit ? cmpGoalHitEquity : cmpEquity
        float _geo = _growthEq > 0 and compoundStartEquityInput > 0 ? math.pow(_growthEq / compoundStartEquityInput, 1.0 / float(_growthDays)) - 1.0 : na
        int _remain = -1
        int _total = -1
        if cmpGoalHit
            _remain := 0
            _total := cmpGoalHitDay
        else if not na(_geo) and _geo > 0 and cmpEquity > 0 and compoundGoal > cmpEquity
            _remain := int(math.ceil(math.log(compoundGoal / cmpEquity) / math.log(1.0 + _geo)))
            _total := cmpDays + _remain
        int _calendar = cmpGoalHit and not na(cmpGoalHitTime) and not na(cmpStartTime) ? int(math.floor(math.max(0.0, float(cmpGoalHitTime - cmpStartTime)) / 86400000.0)) + 1 : _total >= 0 ? int(math.ceil(float(_total) * 7.0 / 5.0)) : -1
        string _benchmark = _calendar < 0 ? "N/A" : _calendar < compoundBenchmarkCalendarDays ? "BEATS " + str.tostring(compoundBenchmarkCalendarDays) + "D BY " + str.tostring(compoundBenchmarkCalendarDays - _calendar) + "D" : _calendar == compoundBenchmarkCalendarDays ? "MATCHES " + str.tostring(compoundBenchmarkCalendarDays) + "D" : "OVER " + str.tostring(compoundBenchmarkCalendarDays) + "D BY " + str.tostring(_calendar - compoundBenchmarkCalendarDays) + "D"
        string _status = cmpGoalHit ? "GOAL HIT" : _total >= 0 ? "PROJECTED" : "NO POSITIVE TRAJECTORY"
        string _quality = cmpDays >= compoundMinSampleDays ? "MATURE" : "EARLY"

        table.cell(compoundTrajectoryTable,0,0,"TGIM FOREX COMPOUND / $1M",bgcolor=color.rgb(40,46,57),text_color=color.white)
        table.cell(compoundTrajectoryTable,1,0,_status+" — "+_quality,bgcolor=color.rgb(40,46,57),text_color=cmpGoalHit?color.lime:color.orange)
        table.cell(compoundTrajectoryTable,0,1,"Sample")
        table.cell(compoundTrajectoryTable,1,1,backtestWindowMode)
        table.cell(compoundTrajectoryTable,0,2,"Model / Frequency")
        table.cell(compoundTrajectoryTable,1,2,"FX PROPORTIONAL / "+compoundFrequency)
        table.cell(compoundTrajectoryTable,0,3,"Research Base Equity")
        table.cell(compoundTrajectoryTable,1,3,f_cmp_money(compoundStartEquityInput))
        table.cell(compoundTrajectoryTable,0,4,"Compound Model Equity")
        table.cell(compoundTrajectoryTable,1,4,f_cmp_money(cmpEquity)+(cmpGoalHit and compoundFreezeAtGoal?" [FROZEN]":""))
        table.cell(compoundTrajectoryTable,0,5,"Observed Days / Trades")
        table.cell(compoundTrajectoryTable,1,5,str.tostring(cmpDays)+" / "+str.tostring(cmpTrades))
        table.cell(compoundTrajectoryTable,0,6,"Sample Quality")
        table.cell(compoundTrajectoryTable,1,6,str.tostring(cmpDays)+" / "+str.tostring(compoundMinSampleDays)+" days — "+_quality,text_color=cmpDays>=compoundMinSampleDays?color.lime:color.orange)
        table.cell(compoundTrajectoryTable,0,7,"Geometric Growth / Day")
        table.cell(compoundTrajectoryTable,1,7,na(_geo)?"—":str.tostring(_geo*100,"#.###")+"%")
        table.cell(compoundTrajectoryTable,0,8,"Goal")
        table.cell(compoundTrajectoryTable,1,8,f_cmp_money(compoundGoal))
        table.cell(compoundTrajectoryTable,0,9,"First Goal Hit")
        table.cell(compoundTrajectoryTable,1,9,cmpGoalHit?"DAY "+str.tostring(cmpGoalHitDay)+" | TRADE #"+str.tostring(cmpGoalHitTrade):_total>=0?"PROJECTED DAY "+str.tostring(_total):"N/A")
        table.cell(compoundTrajectoryTable,0,10,"First Hit Date ET")
        table.cell(compoundTrajectoryTable,1,10,cmpGoalHit?str.format_time(cmpGoalHitTime,"yyyy-MM-dd HH:mm","America/New_York"):"N/A")
        table.cell(compoundTrajectoryTable,0,11,"Equity At First Hit")
        table.cell(compoundTrajectoryTable,1,11,cmpGoalHit?f_cmp_money(cmpGoalHitEquity):"—")
        table.cell(compoundTrajectoryTable,0,12,"Trading Days To Goal")
        table.cell(compoundTrajectoryTable,1,12,_total<0?"N/A":str.tostring(_total))
        table.cell(compoundTrajectoryTable,0,13,str.tostring(compoundBenchmarkCalendarDays)+"-Day Benchmark")
        table.cell(compoundTrajectoryTable,1,13,_benchmark,text_color=str.contains(_benchmark,"BEATS")?color.lime:str.contains(_benchmark,"OVER")?color.red:color.white)
        table.cell(compoundTrajectoryTable,0,14,"Wins / Losses")
        table.cell(compoundTrajectoryTable,1,14,str.tostring(cmpWins)+" / "+str.tostring(cmpLosses))

if barstate.islast
    f_render_compound_table()

//──────────────────────────────────────────────
// V6.5.1 FX FULL-LAB CONTRACT
// Only the old ORDER logic/language was retired.
// R1-R10, all MA choices, lines, dots, ZAG options, rays, angle/slope math,
// ADX/DI, context, pair profiles, OANDA friction/sizing/guards/payloads,
// and the current causal ZAG FLIP engine remain.
//──────────────────────────────────────────────

//──────────────────────────────────────────────
// V6.5.3 — RENDER WEBHOOK EXECUTION CONTRACT
//
// TradingView alert setup:
//   Condition: this strategy -> Any alert() function call
//   Webhook URL: your deployed Render /webhook endpoint
//   Message box: leave it alone; alert() supplies the complete JSON dynamically.
//
// Execution behavior:
//   • alert fires ONLY after the ZAG turn passes the actual operational gates
//   • webhook always sends action="flip", target="long"/"short"
//   • Render/OANDA remains broker-position authority
//   • no separate human-only alert() channel in this build
//   • strategy.order alert_message remains present for audit/backward compatibility,
//     but DO NOT select "Order fills and alert() function calls" for the execution alert,
//     or TradingView could send two webhook events for one accepted strategy event.
//
// Backend compatibility repair:
//   dynamic sizing_mode is "dynamic_margin" (recognized directly by app.py),
//   not the older "portfolio_compound" alias.
//──────────────────────────────────────────────
