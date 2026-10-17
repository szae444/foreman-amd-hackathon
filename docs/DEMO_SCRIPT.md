# Demo video: 2:30 target

Record **live mode only** (badge shows `gemma-4-E2B-it`, no yellow mock banner, bottom rail shows **AMD Ryzen 7 7435HS · CPU only**) at 1440–1536 px wide, with the light theme. Set `FOREMAN_TICK_S=3` so the fault develops on camera without dead air. Close other apps first (Gemma needs ~4 GB of free RAM), and do one dry run: the first Gemma call after a cold start is slower.

**The diagnosis takes about 1.5–3 minutes on the CPU (median 2.8 min; longer if other apps are using RAM).** Don't hide it: record it in real time, then speed up only that stretch in the editor and put a caption on screen while it plays, e.g. *"Sped up 8× · real time 1:42 on an AMD Ryzen 7 CPU"* (use the elapsed time the ticket shows).

| Time | On screen | Voiceover |
|---|---|---|
| 0:00–0:15 | Title card: "Foreman". Cut to the UI, line idle. | "A worn die makes scrap long before anyone notices, and then a technician still has to work out why. Foreman closes that gap." |
| 0:15–0:35 | **Start line.** Parts stream past; drag the photo/heatmap slider on a good part. | "Every part from camera three goes through PatchCore, trained only on good parts. The heatmap shows where a part differs from anything good it has seen." |
| 0:35–0:55 | **Inject: Lubricant degradation.** Die temperature climbs, lube pressure drops; the sensor chip turns to ALARM. | "Now the lubricant degrades. The sensors move first: die temperature up, lube pressure down. Foreman opens an early warning before a single bad part exists." |
| 0:55–1:20 | The camera flags a discoloured nut, the bounding box appears, the ticket shows *Reasoning* (sped-up stretch with the caption), then fills in. Trigger reads **Sensors → camera**. | "Then the camera confirms it. Foreman escalates the same incident and Gemma 4 reads the photo, the heatmap, the sensor trends and the right pages of the manual." |
| 1:20–1:50 | Scroll the ticket: cause and confidence, evidence chips (camera / sensor / manual), work order steps with real torques, citations with ✓, the Italian operator message. | "It returns a cause with a confidence value, evidence by source, the work order with tools and downtime, and the operator message in Italian. Every citation is checked against the manual, and anything invented would be struck through." |
| 1:50–2:05 | **Approve work order.** The stamp lands; a few seconds later the sensor traces return to baseline. | "A supervisor stays in charge. On approval the repair runs and you can watch the press come back to normal." |
| 2:05–2:25 | Hold on the bottom rail: AMD Ryzen 7 7435HS, CPU only, CPU load, RAM, tokens/s, PatchCore ms/part. | "All of this runs on one AMD Ryzen laptop processor, with no GPU and no cloud: Gemma 4 and the vision model, side by side. That's an edge box next to the press, and no camera footage ever leaves the plant. For a whole plant, the same code runs Gemma 4 31B on an AMD Instinct MI300X." |
| 2:25–2:30 | End card: repo URL, live URL. | "Foreman. Find it, explain it, fix it." |

## Deck: 7 slides
1. **Title.** Foreman: find it, explain it, fix it. Track: Intelligent Industry.
2. **Problem.** Scrap until noticed, plus downtime until understood. Vision says *bad part*, not *why*.
3. **Product.** A UI screenshot with the five pipeline steps labelled.
4. **How it works.** Pipeline diagram: PatchCore (PyTorch) → sensor fusion → manual retrieval with cross-refs → Gemma 4 vision (llama.cpp / vLLM) → citation check → supervisor.
5. **Why AMD.** One AMD Ryzen CPU running both models (live rail); self-hosted open models; EU data residency; scale-up to Instinct MI300X (built, not yet run).
6. **Evidence.** AUROC 0.996, 0 % false alarms on good parts, ms/part and Gemma tokens/s on the Ryzen, 34 tests. Honest scope: real images, simulated sensors, fictional manual.
7. **Business value and next steps.** Plug in a plant's own manuals and historian (OPC UA), CMMS export for work orders, multi-line. Close with the ask.

## Numbers (AMD Ryzen 7 7435HS, CPU only)
- [x] PatchCore: AUROC 0.9956, 0 % false alarms, ~184 ms/image
- [x] `scripts/smoke_live`: PASS; Gemma 4 E2B ~12 tok/s decode, ~64 tok/s prompt, median 2.8 min per diagnosis
- [x] `scripts/eval_live --per-fault 3` on the Ryzen: 12/12 defect, agree, citation; action 9/12 (+3 flagged by Foreman)
- [ ] A screenshot of the rail during reasoning (CPU load, tok/s) → slide 5
