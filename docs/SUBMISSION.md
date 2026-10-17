# lablab.ai submission copy

## Project title
Foreman: Find it. Explain it. Fix it.

## Short description (≤ 255 chars)
Foreman finds a defective part, explains why it happened and drafts the repair from the machine manual. PatchCore flags the part, Gemma 4 reads the photo, sensors and manual, and a supervisor signs off. All on one AMD Ryzen CPU.

## Long description (≤ 2000 chars, this is 1850)
On a metal-forming line, a worn die or failing lubrication costs twice: scrap made before anyone notices, then downtime while a technician works out what the symptom means. Cameras can say a part is bad, but not why. That answer lives in a thick manual and in senior technicians' heads.

Foreman takes a plant from "this part looks wrong" to an approved work order:
1. Detect: PatchCore, trained only on good parts, scores every part and outlines the defect on a heatmap.
2. Fuse: press sensors are checked against the machine's baseline with plain statistics.
3. Retrieve: the manual sections that match the defect and sensor pattern.
4. Reason: Gemma 4 vision reads the photo, heatmap, sensors and manual, and writes the cause with a confidence, the evidence, what it ruled out, repair steps and an operator message.
5. Verify: every manual citation is checked against what the model was shown.
6. Approve: a supervisor signs off, and the sensors return to normal.

Sensors usually drift before the camera sees bad parts, so Foreman raises an early warning first and escalates the same incident when the camera confirms it.

Why AMD: everything runs on one AMD Ryzen 7 7435HS CPU, with no GPU and no cloud. Gemma 4 E2B runs on llama.cpp and PatchCore on PyTorch, both CPU-only. Camera images never leave the building, which many manufacturers require. A ROCm + vLLM setup for Gemma 4 31B on AMD Instinct MI300X is included for scale; it is built but not yet run.

Measured on the Ryzen: 0.996 image AUROC on MVTec AD metal_nut, 0% false alarms, about 184 ms per part. In the live eval, 12 of 12 faults got the right defect, camera/sensor agreement and manual citation. Median diagnosis time is 2.8 minutes, with 34 automated tests.

Honest scope: the camera images are real (MVTec AD); the sensors are simulated and the machine manual is fictional.

## Additional info (1488 chars)
How to try the demo (2 minutes): open the demo URL, press START LINE, then inject "Lubricant degradation". Watch the sensors raise an early warning before the camera flags a part, then read Gemma 4's work order and press APPROVE WORK ORDER. The demo page is the real Foreman UI replaying a run recorded live on our AMD Ryzen laptop. Every image, sensor reading and diagnosis is real output from that run. The ~5-minute Gemma wait is fast-forwarded, and the screen shows the real time. We can run the fully live app on the Ryzen during a call on request.

Hardware and models: AMD Ryzen 7 7435HS (8 cores / 16 threads), CPU only. The laptop's NVIDIA GPU is switched off for the run. Gemma 4 E2B-it (Q4_0 GGUF + vision projector) runs on llama.cpp. PatchCore runs on PyTorch CPU with a WideResNet-50 backbone and a 2% coreset. The dashboard reads the processor's live load and the model server's metrics.

What is real and what is simulated: the camera images are real (MVTec AD metal_nut, CC BY-NC-SA 4.0). The press sensors are simulated with physically plausible fault signatures, and the FM-400 machine manual is fictional. The app and README say both.

Reproducible: the repo includes the training script, a scored live-model evaluation (12/12, results in data/eval_ryzen/), 34 automated tests, the scripts that recorded the demo, and a ROCm + vLLM setup for AMD Instinct MI300X (Gemma 4 31B). That setup is built but not yet run, because we had no cloud credits during the build week.

## Demo application URL
https://szae444.github.io/foreman-amd-hackathon/

## Technology tags
AMD Ryzen · ROCm · llama.cpp · vLLM · Gemma 4 · PyTorch · PatchCore · FastAPI · Computer Vision · AI Agents · RAG

## Category tags
Intelligent Industry · Manufacturing · Predictive Maintenance · Quality Inspection

## Prize eligibility to mention
- AMD: both models run on an AMD Ryzen 7 7435HS (CPU only), shown live in the demo; ROCm/MI300X deployment included for scale-up.
- Google: Gemma 4 (E2B-it on the Ryzen; 31B-it on Instinct) is the reasoning model.
- Vibe Generation special prize: Intelligent Industry track.

## Assets
- **Cover image:** `docs/cover.png` (1920×1080, 16:9). It is slide 1 of the deck.
- **Slide deck:** `docs/deck/Foreman_deck.pdf` (8 slides) and `docs/deck/Foreman_deck.pptx` (same slides, with speaker notes). Source: `docs/deck/deck.html`; rebuild with `python docs/deck/render_deck.py`. All screenshots are real captures of the app running Gemma 4 E2B CPU-only on the Ryzen.
- **Demo video:** `foreman_demo.mp4` (2:33, 1080p), built from real captures of the same run.

## lablab requirements (checked 2026-10-16)
- **Deadline:** not published on the event page or in the general guidelines; the event page only says "Online Build: 12–18 October 2026" and the schedule is "To be announced". Confirm the exact cutoff and timezone on the lablab Discord. Plan for the morning of Oct 18, Italian time (CEST), to be safe.
- **Video:** under 5 minutes and under 300 MB (lablab hackathon guidelines). The demo script targets 2:30.
- **Cover image:** 16:9 recommended. `docs/cover.png` is 16:9.
- **Repo:** a public GitHub link; mention any extra repos in README.md.
