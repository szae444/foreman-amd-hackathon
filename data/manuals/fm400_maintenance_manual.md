<!-- Fictional manual written for the Foreman hackathon demo. Machine, part numbers and values are illustrative. -->
# FM-400 Cold Forming Press — Maintenance & Troubleshooting Manual (Rev C)

## 1. Safety and lockout/tagout (LOTO) [p.3]
Before any intervention inside the tooling area: stop the press at top dead centre, engage the mechanical ram block, isolate main electrical supply at disconnect Q1, bleed hydraulic accumulator HA-2 to 0 bar (gauge PG-4), and apply personal locks. Verify zero energy by attempting a jog start. Die temperature may exceed 70 °C after production; wear cut-resistant, heat-rated gloves (EN 407 level 2). Never reach past the light curtain with the ram unblocked. Two-person rule applies to transfer finger work above 1.5 m.

## 2. Machine overview [p.6]
The FM-400 is a 4-station horizontal cold former producing M8–M12 hex nuts from wire coil. Stations: (1) cut-off and squaring, (2) pre-form, (3) hex form, (4) pierce. Parts are moved between stations by the pneumatic transfer fingers TF-1 to TF-4. Finished nuts drop to the vibratory orientation feeder OF-1 which presents them face-up to the inline vision camera CAM-3 before packing. Nominal rate: 140 parts/min.

## 3. Sensor reference and normal operating bands [p.9]
| Sensor | Tag | Normal band | Notes |
|---|---|---|---|
| Ram vibration RMS | VT-101 | 2.4–3.2 mm/s | Rises with die wear, loose tooling, debris in die |
| Ram peak force | FT-102 | 113–123 kN | Spikes with misfeed or transfer misalignment |
| Die temperature | TT-103 | 60–64 °C | Rises with lubricant degradation or low flow |
| Lube pressure | PT-104 | 4.05–4.35 bar | Falls with clogged filter F-7 or pump wear |
| Feeder misfeeds | OF-1 counter | < 1.2 /min | Rises with orientation track wear or bowl amplitude drift |
A reading outside its band for more than 2 minutes must be logged. Two correlated out-of-band sensors indicate a developing fault and require supervisor review.

## 4.1 Visual defect catalogue — surface scratches [p.14]
Appearance: fine linear or arc-shaped marks on the hex flats or bearing face, typically 0.5–3 mm long, bright against the forged surface. Most common causes: worn or chipped hex-form punch (station 3), metal debris trapped in the die cavity, or insufficient lubricant film. Scratches accompanied by rising ram vibration (VT-101) strongly indicate die wear or debris — see section 5.1. Scratched parts are cosmetic rejects for automotive customers (spec QS-12 class B).

## 4.2 Visual defect catalogue — bent or deformed parts [p.16]
Appearance: nut is warped out of plane, a hex corner is folded, or the bore is oval. Most common causes: transfer finger TF-3 gripping off-centre so the blank enters station 3 at an angle, worn finger pads, or a double-hit after a misfeed. Bent parts accompanied by ram force spikes (FT-102 above 125 kN) indicate transfer misalignment — see section 5.2. Bent parts are critical rejects (functional failure risk).

## 4.3 Visual defect catalogue — discoloration [p.18]
Appearance: brown, blue or dark staining on faces, sometimes a dull grey patch. Most common causes: lubricant degradation (oxidised or water-contaminated forming oil), overheated die, or residue from a dirty quench/wash stage. Discoloration with die temperature above 64 °C and lube pressure below 4.05 bar indicates lubrication system fault — see section 5.3. Discoloured parts are cosmetic rejects but may also indicate reduced corrosion protection.

## 4.4 Visual defect catalogue — inverted / flipped parts [p.20]
Appearance: nut presented upside down to CAM-3 (chamfered face down), so the bearing face pattern looks mirrored. Most common causes: orientation feeder OF-1 track wear, bowl vibration amplitude drift, or a bent rejection wiper. Flipped parts with rising feeder misfeed rate indicate orientation feeder fault — see section 5.4. The part itself is usually good; the risk is incorrect downstream assembly.

## 5.1 Troubleshooting — die wear and debris in die [p.24]
Symptoms: scratches on hex flats, ram vibration VT-101 trending upward (> 3.2 mm/s), slight increase in ram force variance. Diagnosis: (1) Stop at top dead centre and apply LOTO (section 1). (2) Inspect hex-form punch P3 and die D3 with a 10× loupe for chips, pick-up or galling. (3) Check the die cavity for slugs or wire debris; blow out with dry air at < 2 bar. (4) Check the punch holder bolts for torque (85 Nm). Corrective action: remove debris; if galling < 0.2 mm, polish per procedure 6.1; if chips are present or punch wear exceeds 0.05 mm on the flats, replace the punch (spare P3-M10-HSS). Expected downtime: 25–40 min (polish) or 60–75 min (replace).

## 5.2 Troubleshooting — transfer finger misalignment [p.28]
Symptoms: bent or folded nuts, ram peak force spikes FT-102 > 125 kN, occasional double-hit alarm. Diagnosis: (1) LOTO. (2) Inch the transfer through one cycle with the setup jog and watch TF-3 enter station 3. (3) Measure finger centring with gauge block G-TF; acceptable offset ≤ 0.1 mm. (4) Inspect the polyurethane finger pads for wear or cracks. Corrective action: realign TF-3 per procedure 6.2 and replace pads if worn below 2.5 mm. Expected downtime: 30–45 min.

## 5.3 Troubleshooting — lubrication system [p.32]
Symptoms: discoloured parts, die temperature TT-103 > 64 °C, lube pressure PT-104 < 4.05 bar, oil looks dark or milky. Diagnosis: (1) Check reservoir level and oil appearance; take a 100 ml sample for water content (limit 0.1 %). (2) Check differential pressure across filter F-7; replace if > 0.8 bar. (3) Check nozzle N3 spray pattern at station 3. Corrective action: replace filter F-7, flush and refill per procedure 6.3 if oil is contaminated. Expected downtime: 20 min (filter) or 90 min (full flush).

## 5.4 Troubleshooting — orientation feeder [p.36]
Symptoms: flipped parts at CAM-3, misfeed counter > 1.2 /min, jams at the feeder exit. Diagnosis: (1) Check bowl amplitude on controller OFC-1 (set point 62 %). (2) Inspect the orientation track and rejection wiper W-2 for wear or bending. (3) Confirm the air-jet reject J-1 fires on every flipped part. Corrective action: re-tune amplitude; adjust or replace wiper W-2 per procedure 6.4. The press itself does not need to stop: switch OF-1 to bypass and divert to manual sort while adjusting. Expected downtime: 10–20 min (feeder only).

## 5.5 Troubleshooting — sensor anomaly with no visual defect [p.38]
An out-of-band sensor without visual rejects is an early warning. Increase CAM-3 sampling to 100 %, log the trend, and schedule inspection at the next planned stop if the reading stays below the alarm limit. If two sensors are out of band, treat as a developing fault and follow the section matching the signature.

## 6.1 Procedure — die inspection and polishing [p.42]
Tools: 10× loupe, diamond paste 6 µm and 3 µm, felt bob, torque wrench 20–100 Nm, die gauge DG-10. Steps: (1) LOTO. (2) Remove punch holder (4× M12, 85 Nm). (3) Clean with solvent and inspect. (4) Polish galled areas with 6 µm then 3 µm paste along the forming direction only. (5) Measure flats with DG-10; reject if worn > 0.05 mm. (6) Reinstall, torque to 85 Nm in cross pattern. (7) Run 50 trial parts at 50 % speed; inspect 10 at CAM-3 and by hand before releasing to production.

## 6.2 Procedure — transfer finger realignment [p.46]
Tools: gauge block G-TF, 5 mm hex key, feeler gauges, pad kit TF-PAD-PU. Steps: (1) LOTO. (2) Loosen TF-3 carriage clamp screws (2× M8). (3) Seat gauge block G-TF in station 3 and bring fingers closed with manual valve V-TF3. (4) Adjust carriage until both fingers contact the gauge evenly (≤ 0.1 mm feeler). (5) Torque clamp screws to 25 Nm. (6) Replace pads if worn. (7) Inch through 5 cycles, then run 50 trial parts and check for bend.

## 6.3 Procedure — lubricant flush and filter change [p.50]
Tools: drain pump, 40 L forming oil FO-46, filter cartridge F-7, nitrile gloves. Steps: (1) Stop press; LOTO not required for filter change only. (2) Isolate filter housing valves. (3) Replace F-7 cartridge, record date. (4) For contaminated oil: drain reservoir, wipe sump, refill with FO-46, bleed pump. (5) Restart and confirm PT-104 at 4.2 ± 0.1 bar and TT-103 back below 64 °C within 15 minutes.

## 6.4 Procedure — feeder bowl and track adjustment [p.54]
Steps: (1) Switch OF-1 to bypass. (2) Set bowl amplitude to 62 % on OFC-1. (3) Inspect wiper W-2; straighten or replace (spare W-2-M10). (4) Test with 100 parts; misfeeds must be < 1 per 100. (5) Return OF-1 to auto.

## 7. Quality containment after a confirmed defect [p.58]
When CAM-3 confirms a defect linked to a machine fault: (1) Quarantine all parts produced since the last good inspection (red bin, tag QH). (2) Record lot number, defect type and suspected cause in the shift log. (3) After the corrective action, 100 % inspect the first 200 parts. (4) Critical rejects (bent parts) require a quality engineer sign-off before the lot is released. Cosmetic rejects (scratch, discoloration) may be sorted by operators.

## 8. Spare parts reference [p.62]
P3-M10-HSS hex-form punch, M10 (stock: crib B-12). D3-M10 hex die. TF-PAD-PU transfer finger pad kit. F-7 lubricant filter cartridge. FO-46 forming oil, 20 L drum. W-2-M10 orientation wiper. G-TF transfer gauge block (tool crib).
