# lablab.ai submission copy

## Project title
Foreman: the shop-floor inspection agent on AMD

## Short description (≤ 255 chars)
Foreman finds a defect, explains why it happened and drafts the repair. PatchCore flags the part, Gemma 4 vision reads the photo, sensors and manual, and a supervisor signs off. Both models run on one AMD Ryzen CPU.

## Long description
**Problem.** On a forming line, a worn die or a misaligned transfer finger costs twice: scrap until someone notices, then downtime while a technician works out what the symptom means. Vision systems can say a part is bad, but they can't say why. The link between "scratches on the hex flats + rising ram vibration" and "die wear: polish per procedure 6.1, torque 85 Nm" is in a PDF manual and in senior technicians' heads.

**Solution.** Foreman closes the loop from camera image to work order:
1. **Detect.** PatchCore, trained only on good parts, scores every part and outlines the anomaly on a heatmap (image AUROC 0.996 on MVTec AD metal_nut, zero false alarms on good parts).
2. **Fuse.** Press sensors are checked against the commissioning baseline with robust statistics, not an LLM.
3. **Retrieve.** The defect catalogue, the troubleshooting sections that match the sensor signature, and the repair procedures they cross-reference.
4. **Reason.** Gemma 4 (vision) reads the photo, the heatmap, the sensors and the manual. It returns a structured diagnosis: cause with a confidence value, evidence by source, alternatives ruled out, a work order, containment steps, and operator messages in English and Italian.
5. **Verify.** Every manual citation is checked against what the model was actually given. Invented references are shown as unverified.
6. **Approve.** A supervisor approves or rejects. The fault clears and the sensors visibly return to baseline.

Because faults show up in the sensors before the camera sees defects, Foreman opens an early-warning incident from the sensors alone. When the camera confirms a defect, it escalates the same incident instead of flooding the floor with alerts.

**Why AMD.** The whole pipeline runs on one AMD Ryzen 7 7435HS laptop CPU, with no GPU and no cloud: Gemma 4 E2B on llama.cpp and the PatchCore detector on PyTorch, both CPU-only (the laptop's NVIDIA card is switched off for the run). That is the shape of a real edge box beside a press: the plant runs open models on hardware it controls, so camera footage never goes to a third-party API, which is a hard requirement for many EU manufacturers. The UI names the AMD processor and shows its live load and the model server's metrics. The repo also ships a ROCm deployment that serves Gemma 4 31B and the detector together on one AMD Instinct MI300X for plant-wide scale; it is built but not yet run, because we had no Developer Cloud credits during the build week.

**Honest scope.** Camera images are real (MVTec AD). Press sensors are simulated with physically plausible fault signatures, and the machine manual is fictional. The UI and README say both. 34 automated tests cover the detector loop, retrieval, citation checking and the live-model request path.

## Technology tags
AMD Ryzen · ROCm · llama.cpp · vLLM · Gemma 4 · PyTorch · PatchCore · FastAPI · Computer Vision · AI Agents · RAG

## Category tags
Intelligent Industry · Manufacturing · Predictive Maintenance · Quality Inspection

## Prize eligibility to mention
- AMD: both models run on an AMD Ryzen 7 7435HS (CPU only), shown live in the demo; ROCm/MI300X deployment included for scale-up.
- Google: Gemma 4 (E2B-it on the Ryzen; 31B-it on Instinct) is the reasoning model.
- Vibe Generation special prize: Intelligent Industry track.

## Assets
- **Cover image:** `docs/cover.png` (1410×793, 16:9). Regenerate from `docs/cover.html` if the screenshot changes.
- **Product screenshot:** `docs/screenshot-vision-sensors.png` (real MVTec part + simulated sensors). Swap it for a real-Gemma ticket screenshot after deploying.
- **Slide deck:** the Claude Slides deck "Foreman — AMD Developer Hackathon ACT III" (8 slides with speaker notes). It exports to PDF/PPTX. Its numbers are the measured Ryzen numbers.

## lablab requirements (checked 2026-10-16)
- **Deadline:** not published on the event page or in the general guidelines; the event page only says "Online Build: 12–18 October 2026" and the schedule is "To be announced". Confirm the exact cutoff and timezone on the lablab Discord. Plan for the morning of Oct 18, Italian time (CEST), to be safe.
- **Video:** under 5 minutes and under 300 MB (lablab hackathon guidelines). The demo script targets 2:30.
- **Cover image:** 16:9 recommended. `docs/cover.png` is 16:9.
- **Repo:** a public GitHub link; mention any extra repos in README.md.
