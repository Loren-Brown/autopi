# SSM collector — real ECU safety test plan

High-level plan to gain confidence that **ssm-collector** can run against a real Subaru ECU without damaging it, interrupting drivability, or overloading the ECU/CAN bus.

This is a **read-only logging** stack today. The plan below treats that as a hypothesis to verify, then validates load under controlled conditions before any road use.

---

## What “safe” means here

| Goal | Meaning |
|------|--------|
| **No damage** | No flash, tune write, clear-DTC, or other mutating SSM commands |
| **No interrupt** | Engine keeps idling/running; no stalls, CEL storms, limp mode, or loss of throttle response tied to logging |
| **No overload** | ECU answers consistently; no sustained timeouts, bus-off, or rising error rate as poll load increases |

**Out of scope for this plan:** proving absolute impossibility of ECU bugs under all conditions; OEM warranty; every ROM variant.

---

## Threat model (what could go wrong)

1. **Mutating protocol** — accidental send of SSM write / programming / clear commands  
2. **Wrong ECU / address map** — garbage values (usually not destructive for reads, but false confidence)  
3. **CAN / ECU overload** — too many address slots or too high poll Hz → missed FC, timeouts, ECU busy  
4. **Bus contention** — shared powertrain CAN; logger competes with other modules  
5. **Bad physical layer** — wiring faults, termination, ground loops (can cause bus-off; rare damage path)  
6. **Software hang / retry storms** — client spamming after errors

---

## Current software facts (baseline)

Verify these before any car test (code review + bench):

| Item | Expected (autopi today) |
|------|-------------------------|
| SSM commands used | **Init `0xBF`**, **batch read `0xA8` only** |
| Forbidden in client | Memory write, block write, reflash, clear DTC, any non-read SSM opcode |
| CAN IDs | Request `0x7E0`, response `0x7E8` |
| Poll target | ~**50 Hz** (`POLL_INTERVAL = 0.020`) when the bus keeps up |
| Channel set | Only **enabled** ids in `channels.json` (keep this **small** for first car runs) |

**Gate A — static:** confirm `ssm_client.py` (and any callers) cannot send anything except `0xBF` / `0xA8`. Fail the plan if new opcodes appear without a new review.

---

## Test phases

### Phase 0 — Desk / CI (no car)

1. Confirm command allowlist (Gate A).  
2. Confirm enabled channel count and total **address slots** (sum of param lengths + switches).  
3. Run Teensy offline validation (`validate_teensy_ssm.py --offline`) so maps match intent.  
4. Optional: capture a CAN dump of one collector session on the Teensy and assert **only** `0x7E0`/`0x7E8` SSM-looking traffic from the Pi (no unexpected IDs from this stack).

**Pass:** no write opcodes in code path; channel set documented; Teensy map OK.

---

### Phase 1 — Bench soak (Teensy, hours)

Simulate car load before touching the vehicle.

1. Flash Teensy SSM sim; run collector + dashboard as in normal use.  
2. Use the **same** `channels.json` planned for the car.  
3. Soak **≥ 30–60 minutes** at full poll rate.  
4. Watch for: sustained FC errors, poll thread death, rising warning rate, UI freezes.  
5. Exercise parking switch / pots so values change (proves live path, not stuck cache).

**Pass:** stable Hz, no hard poll death, recoverable warnings only (if any).  
**Fail:** repeated FC failures, bus errors, or collector crash under steady load → fix before car.

---

### Phase 2 — Car, ignition ON / engine OFF (key-on, not running)

Lowest risk live ECU contact.

**Setup**

- Battery healthy; prefer battery tender if sitting long.  
- PiCAN3 wired correctly; terminate/bus topology as designed.  
- **Minimal** channel pack (e.g. 3–5 channels: coolant, RPM, speed, 1–2 extended).  
- Start with **reduced poll rate** if easy to configure; otherwise keep channels tiny so ISO-TP stays light.  
- Have a second person ready to pull the OBD plug.

**Steps**

1. Key ON, engine OFF. Confirm no collector running yet.  
2. Start collector; confirm ECU ID matches expected (`SSM_ECU_ID` / init response).  
3. Run **2 minutes** → check values look sane (not all NaN).  
4. Run **15–30 minutes** soak.  
5. Capture: poll rate achieved, timeout/error count, any dashboards CEL (should stay off for read-only).  
6. Stop collector; key OFF; wait; key ON again — car should behave normally.

**Pass:** stable reads, no CEL, no odd module behavior, clean stop.  
**Abort immediately:** CEL, battery voltage collapse, CAN errors flooding, unresponsive dash/cluster, smoke/heat at adapter.

---

### Phase 3 — Car, engine IDLE (parked, safe area)

Only after Phase 2 pass.

1. Engine at idle, transmission Park/Neutral, parking brake set, outdoors/ventilated.  
2. Same minimal channel pack; collector on.  
3. Watch idle quality for **10+ minutes** (RPM smoothness, no stumble when logging starts/stops).  
4. Toggle collector **off/on** several times while idling.  
5. Optionally bump channel count one step; re-check idle and error rate.  
6. Optionally raise effective load (more channels) toward the production set; stay at idle.

**Pass:** idle unchanged with logger on/off; errors rare; ECU ID stable.  
**Abort:** stall, surge, CEL, limp, or sustained poll failures.

---

### Phase 4 — Overload / headroom characterization (idle or key-on)

Goal: know the **safe envelope**, not the maximum possible. Run the **limit experiments** below (bench first, then car key-on/idle). Do not use “absolute max that still sometimes works” as the daily config.

**Pass:** production config sustains target rate with **low** error rate (define a threshold, e.g. &lt; 0.1% failed polls over 10 minutes).  
**Fail:** need to drop channels or Hz to stay stable — document the ceiling; do not “push through” on the road.

---

### Phase 5 — Fault / resilience scenarios (bench first, then car key-on)

Goal: prove the ECU and car keep running when the **Pi/logger side misbehaves**, and that the collector recovers without a retry storm that overloads the ECU.

Run each scenario **on Teensy first**. Repeat on the car only at **key-on / engine off**, then (if clean) once at **idle**. Abort using the hard criteria below if the vehicle complains.

#### R1 — OBD-II port disconnects randomly

| | |
|--|--|
| **How** | While polling, unplug OBD (or PiCAN) for 1–10 s at random intervals; repeat ≥ 20 cycles. Mix short blips and longer (&gt;5 s) disconnects. |
| **Expect** | Collector shows errors/NaNs while unplugged; **no** CEL / limp from disconnect alone. On reconnect, init + polling resume (or clean restart) without spamming the bus. |
| **Watch** | Retry backoff (not a tight send loop), CAN bus-off counters, ECU still answers after reconnect. |
| **Pass** | Car unaffected; logger recovers within one restart or automatic re-init; no sustained flood after reconnect. |

#### R2 — Pi powers down randomly

| | |
|--|--|
| **How** | Hard cut Pi power (USB-C / PSU) while collector is polling; restore power; boot; service comes back. Repeat ≥ 10 cycles. On car: prefer key-on first. |
| **Expect** | CAN traffic from Pi stops immediately on power loss. ECU continues normal operation. After boot, single clean SSM init + poll — not a burst of stale multi-frame junk. |
| **Watch** | Half-written ISO-TP sequences at kill time; whether ECU ignores incomplete requests; battery drain if Pi hard-reboots in a loop. |
| **Pass** | No vehicle symptoms across cycles; collector returns to steady poll without manual ECU reset. |

#### R3 — Pi locks up and resumes randomly

| | |
|--|--|
| **How** | Induce lockups that freeze userspace/CAN TX for seconds–minutes, then resume (e.g. pause collector process with `SIGSTOP`/`SIGCONT`, block the poll thread, or simulate a hung socketcand path). Mix short (~2 s) and long (~60 s) freezes. ≥ 15 cycles. |
| **Expect** | While frozen: no new requests (or stalled mid-ISO-TP). ECU stays happy. On resume: either continue cleanly or re-init; no backlog of queued requests dumped at once. |
| **Watch** | “Thundering herd” after resume; FC timeout storms; need for process kill vs self-heal. |
| **Pass** | Idle/key-on unchanged; post-resume error rate returns to baseline within ~30 s. |

#### R4 — Pi overheats and slows down

| | |
|--|--|
| **How** | Thermal throttle the Pi (stress + restricted airflow, or `cpufreq` capped low) so poll loop and CAN userspace run **late/jittery** while still “alive.” Hold 15–30 minutes with production channel set. |
| **Expect** | Achieved Hz drops; timeouts may rise; ECU must **not** be hammered harder as the Pi slows (no catch-up burst). Dashboard may lag; car must remain normal. |
| **Watch** | Poll interval stretching vs stacking; CPU freq / temps; FC miss rate vs thermal state. |
| **Pass** | Effective rate falls gracefully; no overload spike; car idle/key-on OK. Document degraded Hz under heat. |

#### R5 — Pi requests incorrect address (malformed request)

| | |
|--|--|
| **How (controlled)** | On **bench/Teensy first**, send deliberate bad traffic from a one-off script or test hook — not from production `channels.json`. Cases: (1) valid `0xA8` with **nonsense addresses**; (2) truncated ISO-TP (FF then silence); (3) wrong PCI / length; (4) unknown SSM opcode (must remain non-write); (5) oversized address list. Then, separately, point production loader at a **wrong ECU map** (mismatched `SSM_ECU_ID`) and confirm values are garbage/NaN, not destructive. |
| **Expect** | ECU ignores or NACK/times out; **no** flash/write side effects; no limp/CEL from bad reads alone. Production client still only emits `0xBF`/`0xA8`. |
| **Watch** | Any unexpected positive response that looks like programming; bus-off; need to key-cycle ECU. |
| **Pass** | Vehicle unaffected; Gate A still holds; production path cannot emit write opcodes even under bad config. Malformed cases are **test-only** tools, not shipped behavior. |

**Phase 5 pass:** all R1–R5 clean on Teensy; R1–R4 clean on car key-on; R5 malformed suite bench-only unless a reviewer explicitly approves a minimal nonsense-address read on key-on.

---

### Phase 6 — Short moving test (optional, after phases 2–5)

Parked-lot / private road only at first.

1. Production channel set within **safe max limits** (below).  
2. Drive gently; note any hesitation correlated with logging.  
3. Prefer a passenger watching collector logs / error pill.  
4. Stop test at first drivability anomaly.

**Pass:** no correlation between logger and drivability issues over a short loop.  
**Do not** treat this as proof for track/WOT until more soak exists.

---

## Limit experiments (assign safe max)

Run on **Teensy first**, then confirm on car **key-on**, then **idle**. Hold each point **≥ 2 minutes** (longer at the chosen “safe max”). Record achieved Hz, failed-poll %, FC timeouts, and idle quality.

### Experiment L1 — Max poll rate

1. Fix a **small** channel set (e.g. 3–5 single-byte params).  
2. Sweep target poll interval downward (examples: 10 Hz → 20 → 50 → 75 → 100 Hz) as configuration allows.  
3. At each step log: target vs achieved period, error %, CAN stats if available.  
4. Stop increasing when errors exceed threshold or idle quality changes (car).

**Output:** `max_poll_hz_observed` (last unstable or last stable — label clearly) and `safe_poll_hz` (see assignment rules).

### Experiment L2 — Max items to poll

1. Fix poll target at a moderate rate that passed L1 (e.g. 20 or 50 Hz).  
2. Grow the enabled set by **address slots** (not just channel count): add params/switches until ISO-TP multi-frame grows. Suggested steps: 5 → 10 → 20 → 40 → 80 slots (stop earlier if failing).  
3. At each step log: slot count, request/response frame count, achieved Hz, error %.  
4. Note cliff where FC failures or Hz collapse.

**Output:** `max_address_slots_observed` and `safe_address_slots`.

### Experiment L3 — Assign safe max limits

Do **not** set daily limits at the cliff. Apply a margin:

| Limit | Assignment rule (starting point) |
|-------|----------------------------------|
| **Safe max poll rate** | ≤ **70%** of the highest Hz that sustained &lt; 0.1% failed polls for ≥ 10 minutes on **car idle** (or key-on if idle not yet cleared). Cap at a product default (e.g. 50 Hz) even if the bench goes higher. |
| **Safe max items** | ≤ **70%** of the largest **address-slot** count that sustained the same error threshold at `safe_poll_hz` on car idle. Prefer documenting both **channel count** and **address slots** (4-byte params cost 4 slots). |
| **Combined envelope** | Re-validate the **pair** (`safe_poll_hz` × `safe_address_slots`) together for ≥ 15 minutes idle — limits are not fully independent. |

Write the chosen numbers into a short “Safe operating envelope” note (date, ECU ID, ROM, hardware):

```text
safe_poll_hz:        <n>
safe_address_slots:  <n>
safe_channel_count:  <n>   # informational; slots are authoritative
validated_on:        <ECU ID / date / key-on|idle>
margin_rule:         70% of max stable @ <0.1% failures
```

Until L3 is done, treat the **Recommended first-car configuration** as the interim envelope.

---

## Hard abort criteria (any phase on car)

Stop collector and disconnect OBD if any of these occur:

- Check engine light / flashing CEL  
- Stall, severe idle stumble, or throttle anomaly  
- Cluster / ABS / other warning lights appearing with logger start  
- Sustained CAN bus-off or nonstop FC / timeout spam  
- Smell of electronics, hot connector, or battery voltage diving  
- Any evidence of **write** or unexpected CAN IDs from the Pi

---

## Recommended first-car configuration

Until Phase 4 + **L3 safe max** are assigned:

- **Few channels** (prefer single-byte params; avoid huge extended batches)  
- Keep **S142 / switches** only if needed (they still cost one address slot each)  
- Do **not** enable the full `channels.generated.json` catalog  
- Prefer Pi **on-car** (`CAN_MODE=native`) over long socketcand tunnels for first tests  
- One collector instance only (no double-polling from laptop + Pi)  
- After L3: never exceed `safe_poll_hz` / `safe_address_slots` in production `channels.json` / collector config

---

## Evidence to keep

For each car phase, note:

1. Date, ROM/ECU ID, channel list, poll interval  
2. Duration and pass/fail  
3. Error counts / log excerpts  
4. Any vehicle symptoms  
5. Decision: proceed / hold / reduce load  

---

## Residual risk (be honest)

- Read-only SSM is widely used (RomRaider, etc.), but **rate and batch size** are the real stress knobs.  
- A read cannot “flash” the ECU via this client, but a **buggy cable, wrong tool, or future code change** could. Re-run Gate A after any SSM client change.  
- Some ECUs are fussier than others; passing on one STI ROM does not automatically clear every car.

---

## Suggested go / no-go for “daily driver logging”

**Go** when:

- Gate A current  
- Phase 1 soak clean  
- Phase 2 + 3 pass  
- Phase 4 / L1–L3 complete with written **safe max** limits  
- Production config **inside** those limits  
- Phase 5 resilience scenarios (R1–R4) passed on car key-on; R5 bench suite passed  

**No-go** if production set only works by ignoring frequent timeouts, by stressing idle quality, or by running at the overload cliff without margin.
